from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugin_registry import get_registry
from app.models.log_entry import LogEntryRecord
from app.services import config_service
from app.services.device_service import build_credentials, get_device

VALID_LOG_TYPES = {"traffic", "threat", "system", "config", "tunnel"}


async def collect_logs(db: AsyncSession, device_id: str, log_type: str, since_minutes: int = 60) -> int:
    if log_type not in VALID_LOG_TYPES:
        raise ValueError(f"log_type must be one of {sorted(VALID_LOG_TYPES)}")

    device = await get_device(db, device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    count = 0
    async for entry in plugin.stream_logs(creds, log_type, since):
        db.add(
            LogEntryRecord(
                device_id=device_id,
                log_type=entry.log_type,
                raw=entry.raw,
                logged_at=entry.logged_at,
            )
        )
        count += 1

    if count:
        await db.commit()
    return count


async def search_logs(
    db: AsyncSession,
    device_id: str,
    log_type: str | None = None,
    query: str | None = None,
    since_minutes: int = 1440,
    limit: int = 200,
) -> list[LogEntryRecord]:
    since = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    stmt = select(LogEntryRecord).where(LogEntryRecord.device_id == device_id, LogEntryRecord.logged_at >= since)
    if log_type:
        stmt = stmt.where(LogEntryRecord.log_type == log_type)
    stmt = stmt.order_by(LogEntryRecord.logged_at.desc()).limit(limit)

    result = await db.execute(stmt)
    entries = list(result.scalars().all())

    if query:
        # Simple substring match across the raw log fields — fine at Phase 1
        # volumes stored in Postgres; a real search index (or the ClickHouse
        # migration flagged in the architecture doc) is the upgrade path once
        # log volume makes this scan too slow.
        query_lower = query.lower()
        entries = [e for e in entries if query_lower in " ".join(str(v) for v in e.raw.values()).lower()]

    return entries


async def correlate_traffic_to_policy(db: AsyncSession, device_id: str, since_minutes: int = 1440) -> dict:
    """
    Answers "which policy matched this traffic" by joining traffic log
    entries (which PAN-OS already tags with the matched rule name) against
    the latest collected policy list — this is exactly the kind of
    deterministic lookup the AI Assistant's grounding layer should call
    instead of asking an LLM to guess, per the architecture doc's RAG design.
    """
    latest = await config_service.get_latest_config_version(db, device_id)
    policy_names = {p["name"] for p in latest.policies} if latest else set()

    entries = await search_logs(db, device_id, log_type="traffic", since_minutes=since_minutes, limit=1000)
    matched: dict[str, int] = {}
    unmatched_count = 0
    for entry in entries:
        rule = entry.raw.get("rule") or entry.raw.get("rule_matched")
        if rule and rule in policy_names:
            matched[rule] = matched.get(rule, 0) + 1
        else:
            unmatched_count += 1

    return {
        "total_traffic_logs": len(entries),
        "matched_by_policy": matched,
        "unmatched_count": unmatched_count,
    }
