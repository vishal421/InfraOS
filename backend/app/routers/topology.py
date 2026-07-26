from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services import topology_service
from app.services.device_service import DeviceNotFoundError
from app.services.topology_service import NoConfigurationError

router = APIRouter(prefix="/api/v1/devices/{device_id}/topology", tags=["topology"])


@router.get("")
async def get_topology(device_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await topology_service.build_topology(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoConfigurationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
