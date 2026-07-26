from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services import bpa_service
from app.services.bpa_service import NoConfigurationError
from app.services.device_service import DeviceNotFoundError

router = APIRouter(prefix="/api/v1/devices/{device_id}/best-practice", tags=["best-practice"])


@router.get("")
async def analyze(device_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await bpa_service.analyze(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoConfigurationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
