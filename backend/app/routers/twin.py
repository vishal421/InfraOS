from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user
from app.db.session import get_db
from app.schemas.schemas import DigitalTwinResponse
from app.services import twin_service
from app.services.device_service import DeviceNotFoundError

router = APIRouter(prefix="/api/v1/devices/{device_id}/twin", tags=["digital-twin"])


@router.get("", response_model=DigitalTwinResponse)
async def get_digital_twin(
    device_id: str, use_cache: bool = Query(default=True), _: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        return await twin_service.get_digital_twin(db, device_id, use_cache=use_cache)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
