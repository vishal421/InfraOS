from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_operator
from app.db.session import get_db
from app.schemas.schemas import HealthEventResponse, InterfaceStatusResponse, MetricPoint
from app.services import monitoring_service, twin_service
from app.services.device_service import DeviceNotFoundError

router = APIRouter(prefix="/api/v1/devices/{device_id}", tags=["monitoring"])


@router.post("/metrics/collect", response_model=list[MetricPoint])
async def collect_metrics(device_id: str, _: CurrentUser = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    try:
        records = await monitoring_service.collect_metrics(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await twin_service.invalidate_twin_cache(device_id)
    return [MetricPoint.model_validate(r) for r in records]


@router.get("/metrics/latest", response_model=dict[str, MetricPoint])
async def get_latest_metrics(device_id: str, db: AsyncSession = Depends(get_db)):
    latest = await monitoring_service.get_latest_metrics(db, device_id)
    return {name: MetricPoint.model_validate(r) for name, r in latest.items()}


@router.get("/metrics/history", response_model=list[MetricPoint])
async def get_metric_history(
    device_id: str,
    metric_name: str = Query(...),
    since_minutes: int = Query(default=60, ge=1, le=10080),
    plane: str | None = Query(default=None, description="Filter to 'control' or 'data' for plane-tagged metrics (cpu/mem utilization)."),
    db: AsyncSession = Depends(get_db),
):
    history = await monitoring_service.get_metric_history(db, device_id, metric_name, since_minutes, plane)
    return [MetricPoint.model_validate(r) for r in history]


@router.get("/health-events", response_model=list[HealthEventResponse])
async def list_health_events(
    device_id: str, active_only: bool = Query(default=True), db: AsyncSession = Depends(get_db)
):
    events = await monitoring_service.list_health_events(db, device_id, active_only)
    return [HealthEventResponse.model_validate(e) for e in events]


@router.get("/interfaces", response_model=list[InterfaceStatusResponse])
async def get_interfaces(device_id: str, db: AsyncSession = Depends(get_db)):
    """Live interface monitor: link state, configured IP(s), and traffic
    (cumulative counters plus a derived bits/sec rate from the previous
    poll). Call this on an interval from the UI for a live-updating view —
    each call is a fresh poll of the device, not a cached snapshot."""
    try:
        views = await monitoring_service.get_interface_status(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        InterfaceStatusResponse(
            name=v.status.name,
            zone=v.status.zone,
            admin_up=v.status.admin_up,
            oper_up=v.status.oper_up,
            ip_addresses=v.status.ip_addresses,
            speed_mbps=v.status.speed_mbps,
            duplex=v.status.duplex,
            mtu=v.status.mtu,
            in_bytes=v.status.in_bytes,
            out_bytes=v.status.out_bytes,
            in_packets=v.status.in_packets,
            out_packets=v.status.out_packets,
            in_errors=v.status.in_errors,
            out_errors=v.status.out_errors,
            in_drops=v.status.in_drops,
            out_drops=v.status.out_drops,
            in_bps=v.in_bps,
            out_bps=v.out_bps,
            collected_at=v.status.collected_at,
        )
        for v in views
    ]
