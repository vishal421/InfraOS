from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_operator
from app.db.session import get_db
from app.plugins.base import ConfigSnapshotType
from app.schemas.schemas import ConfigVersionDetail, ConfigVersionSummary
from app.services import config_service, twin_service
from app.services.device_service import DeviceNotFoundError

router = APIRouter(prefix="/api/v1/devices/{device_id}/config", tags=["configuration"])


@router.post("/collect", response_model=ConfigVersionDetail)
async def collect_configuration(
    device_id: str,
    snapshot_type: ConfigSnapshotType = Query(default=ConfigSnapshotType.RUNNING),
    _: CurrentUser = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    try:
        version = await config_service.collect_configuration(db, device_id, snapshot_type)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await twin_service.invalidate_twin_cache(device_id)
    return ConfigVersionDetail.model_validate(version)


@router.get("/versions", response_model=list[ConfigVersionSummary])
async def list_versions(
    device_id: str,
    snapshot_type: str = Query(default="running"),
    db: AsyncSession = Depends(get_db),
):
    versions = await config_service.list_config_versions(db, device_id, snapshot_type)
    return [ConfigVersionSummary.model_validate(v) for v in versions]


@router.get("/versions/{version_id}", response_model=ConfigVersionDetail)
async def get_version(device_id: str, version_id: str, db: AsyncSession = Depends(get_db)):
    version = await config_service.get_config_version(db, version_id)
    if version is None or version.device_id != device_id:
        raise HTTPException(status_code=404, detail="Config version not found")
    return ConfigVersionDetail.model_validate(version)


@router.get("/latest", response_model=ConfigVersionDetail)
async def get_latest(
    device_id: str, snapshot_type: str = Query(default="running"), db: AsyncSession = Depends(get_db)
):
    version = await config_service.get_latest_config_version(db, device_id, snapshot_type)
    if version is None:
        raise HTTPException(status_code=404, detail="No configuration collected yet for this device")
    return ConfigVersionDetail.model_validate(version)
