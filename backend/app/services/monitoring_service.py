from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugin_registry import get_registry
from app.models.entities import HealthEvent, MetricRecord
from app.services.device_service import build_credentials, get_device

# Simple static thresholds for Phase 1. The architecture calls these out as
# configurable per tenant/device-class — fine as a fixed default for a
# single-user pass, but not meant to be the permanent story.
THRESHOLDS = {
    "cpu_utilization_pct": 90.0,
    "mem_utilization_pct": 90.0,
}

# Cumulative traffic counters we persist per interface so a later poll can
# derive a bits-per-second rate by diffing against the last sample, the same
# way any SNMP-based bandwidth graph works (PAN-OS/FortiOS don't expose a
# live bps figure directly — only running octet counters).
_INTERFACE_COUNTER_METRICS = {
    "in_bytes": "interface_in_bytes",
    "out_bytes": "interface_out_bytes",
}


async def collect_metrics(db: AsyncSession, device_id: str) -> list[MetricRecord]:
    device = await get_device(db, device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    metrics = await plugin.collect_metrics(creds)

    records: list[MetricRecord] = []
    for metric in metrics:
        record = MetricRecord(
            device_id=device_id,
            metric_name=metric.metric_name,
            value=metric.value,
            unit=metric.unit,
            dimensions=metric.dimensions,
            recorded_at=metric.recorded_at,
        )
        db.add(record)
        records.append(record)

        threshold = THRESHOLDS.get(metric.metric_name)
        if threshold is not None and metric.value >= threshold:
            db.add(
                HealthEvent(
                    device_id=device_id,
                    severity="warning",
                    category="resource",
                    message=f"{metric.metric_name} at {metric.value:.1f}{metric.unit or ''} (threshold {threshold})",
                )
            )

    await db.commit()
    return records


async def get_latest_metrics(db: AsyncSession, device_id: str) -> dict[str, MetricRecord]:
    """Returns the single most recent record per distinct (metric_name, plane)
    combination. Some metrics (cpu_utilization_pct, mem_utilization_pct) are
    now reported for both the control plane and the data plane under the
    same metric_name, distinguished by a `plane` dimension — without this,
    a plain per-name query would nondeterministically clobber one plane's
    reading with the other's. The returned dict key is `metric_name` for
    plane-less metrics (e.g. active_sessions) and `metric_name:plane` for
    plane-tagged ones (e.g. `cpu_utilization_pct:data`), so callers can
    still do simple lookups without guessing which plane won a race.
    Simple per-key query rather than a window function — fine at this scale
    (one device's recent metrics), revisit if metric cardinality grows a lot."""
    result = await db.execute(
        select(MetricRecord.metric_name, MetricRecord.dimensions)
        .where(MetricRecord.device_id == device_id)
        .distinct()
    )
    keys: set[tuple[str, Optional[str]]] = set()
    for name, dimensions in result.all():
        keys.add((name, (dimensions or {}).get("plane")))

    latest: dict[str, MetricRecord] = {}
    for name, plane in keys:
        query = select(MetricRecord).where(MetricRecord.device_id == device_id, MetricRecord.metric_name == name)
        if plane is not None:
            query = query.where(MetricRecord.dimensions["plane"].as_string() == plane)
        else:
            query = query.where(MetricRecord.dimensions["plane"].as_string().is_(None))
        query = query.order_by(MetricRecord.recorded_at.desc()).limit(1)

        row_result = await db.execute(query)
        record = row_result.scalars().first()
        if record:
            key = f"{name}:{plane}" if plane is not None else name
            latest[key] = record
    return latest


async def get_metric_history(
    db: AsyncSession, device_id: str, metric_name: str, since_minutes: int = 60, plane: Optional[str] = None
) -> list[MetricRecord]:
    """`plane` disambiguates metrics reported for both control and data
    plane under the same metric_name (see get_latest_metrics) — e.g. pass
    plane="data" to chart dataplane CPU separately from control-plane CPU.
    Leave unset for metrics that were never plane-tagged (active_sessions,
    interface_drop_packets, ...)."""
    since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    query = select(MetricRecord).where(
        MetricRecord.device_id == device_id,
        MetricRecord.metric_name == metric_name,
        MetricRecord.recorded_at >= since,
    )
    if plane is not None:
        query = query.where(MetricRecord.dimensions["plane"].as_string() == plane)
    query = query.order_by(MetricRecord.recorded_at.asc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def list_health_events(db: AsyncSession, device_id: str, active_only: bool = True) -> list[HealthEvent]:
    query = select(HealthEvent).where(HealthEvent.device_id == device_id)
    if active_only:
        query = query.where(HealthEvent.resolved_at.is_(None))
    query = query.order_by(HealthEvent.occurred_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


class InterfaceStatusView:
    """Plain data holder returned to the router: the plugin's live
    InterfaceStatus plus the derived throughput this poll produced. Kept
    separate from the plugin's own model since in_bps/out_bps are a
    platform-side derivation (delta of two polls), not something any single
    device call returns."""

    def __init__(self, status, in_bps: Optional[float], out_bps: Optional[float]):
        self.status = status
        self.in_bps = in_bps
        self.out_bps = out_bps


async def get_interface_status(db: AsyncSession, device_id: str) -> list[InterfaceStatusView]:
    device = await get_device(db, device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    statuses = await plugin.get_interface_status(creds)
    now = datetime.now(timezone.utc)

    views: list[InterfaceStatusView] = []
    for status in statuses:
        in_bps = await _persist_counter_and_get_rate(db, device_id, status.name, "in_bytes", status.in_bytes, now)
        out_bps = await _persist_counter_and_get_rate(db, device_id, status.name, "out_bytes", status.out_bytes, now)
        views.append(InterfaceStatusView(status, in_bps, out_bps))

    await db.commit()
    return views


async def _persist_counter_and_get_rate(
    db: AsyncSession,
    device_id: str,
    interface_name: str,
    counter_key: str,
    current_value: Optional[int],
    now: datetime,
) -> Optional[float]:
    """Looks up the last stored sample for this interface/counter, derives a
    bits-per-second rate from the delta, then stores the current cumulative
    value for next time. Returns None on the first-ever sample for an
    interface (no prior point to diff against) or if the counter appears to
    have reset (device reboot / interface flap resets octet counters to 0,
    which would otherwise show as a nonsensical negative rate)."""
    if current_value is None:
        return None

    metric_name = _INTERFACE_COUNTER_METRICS[counter_key]
    result = await db.execute(
        select(MetricRecord)
        .where(
            MetricRecord.device_id == device_id,
            MetricRecord.metric_name == metric_name,
            MetricRecord.dimensions["interface"].as_string() == interface_name,
        )
        .order_by(MetricRecord.recorded_at.desc())
        .limit(1)
    )
    previous = result.scalars().first()

    rate_bps: Optional[float] = None
    if previous is not None:
        elapsed_seconds = (now - previous.recorded_at).total_seconds()
        delta_bytes = current_value - previous.value
        if elapsed_seconds > 0 and delta_bytes >= 0:
            rate_bps = (delta_bytes * 8) / elapsed_seconds

    db.add(
        MetricRecord(
            device_id=device_id,
            metric_name=metric_name,
            value=float(current_value),
            unit="bytes",
            dimensions={"interface": interface_name},
            recorded_at=now,
        )
    )
    return rate_bps
