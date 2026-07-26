from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_operator
from app.db.session import get_db
from app.schemas.schemas import LogEntryResponse
from app.services import log_service
from app.services.device_service import DeviceNotFoundError

router = APIRouter(prefix="/api/v1/devices/{device_id}/logs", tags=["logs"])


@router.post("/collect")
async def collect_logs(
    device_id: str,
    log_type: str = Query(default="traffic"),
    since_minutes: int = Query(default=60, ge=1, le=10080),
    _: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    try:
        count = await log_service.collect_logs(db, device_id, log_type, since_minutes)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"collected": count}


@router.get("/search", response_model=list[LogEntryResponse])
async def search_logs(
    device_id: str,
    log_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    since_minutes: int = Query(default=1440, ge=1, le=43200),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    entries = await log_service.search_logs(db, device_id, log_type, q, since_minutes, limit)
    return [LogEntryResponse.model_validate(e) for e in entries]


@router.get("/correlate")
async def correlate(
    device_id: str,
    since_minutes: int = Query(default=1440, ge=1, le=43200),
    db: AsyncSession = Depends(get_db),
):
    return await log_service.correlate_traffic_to_policy(db, device_id, since_minutes)
