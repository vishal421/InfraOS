from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_admin, require_operator
from app.db.session import get_db
from app.schemas.schemas import (
    ConnectivityTestResponse,
    DeviceCreateRequest,
    DeviceResponse,
    DeviceUpdateRequest,
)
from app.services import connectivity_service, device_service, twin_service
from app.services.connectivity_service import DeviceDiscoveryError
from app.services.device_service import DeviceNotFoundError

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.post("", response_model=DeviceResponse, status_code=201)
async def create_device(payload: DeviceCreateRequest, _: CurrentUser = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    device = await device_service.create_device(db, payload)
    return DeviceResponse.model_validate(device)


@router.get("", response_model=list[DeviceResponse])
async def list_devices(db: AsyncSession = Depends(get_db)):
    devices = await device_service.list_devices(db)
    return [DeviceResponse.model_validate(d) for d in devices]


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, db: AsyncSession = Depends(get_db)):
    try:
        device = await device_service.get_device(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeviceResponse.model_validate(device)


@router.patch("/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: str, payload: DeviceUpdateRequest, _: CurrentUser = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    try:
        device = await device_service.update_device(db, device_id, payload)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await twin_service.invalidate_twin_cache(device_id)
    return DeviceResponse.model_validate(device)


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: str, _: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        await device_service.delete_device(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await twin_service.invalidate_twin_cache(device_id)


@router.post("/{device_id}/test-connectivity", response_model=ConnectivityTestResponse)
async def test_connectivity(device_id: str, _: CurrentUser = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    try:
        result = await connectivity_service.test_connectivity(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConnectivityTestResponse(
        status=result.status.value,
        reachable=result.reachable,
        tls_valid=result.tls_valid,
        authenticated=result.authenticated,
        latency_ms=result.latency_ms,
        error_detail=result.error_detail,
    )


@router.post("/{device_id}/discover", response_model=DeviceResponse)
async def discover_device(device_id: str, _: CurrentUser = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    try:
        await connectivity_service.discover_device(db, device_id)
        device = await device_service.get_device(db, device_id)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DeviceDiscoveryError as exc:
        # Previously uncaught plugin errors (auth failure, unreachable host,
        # unsupported OS version, etc.) reached this point unhandled and
        # FastAPI returned a bare 500. connectivity_service now converts them
        # into DeviceDiscoveryError with an appropriate status_code.
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await twin_service.invalidate_twin_cache(device_id)
    return DeviceResponse.model_validate(device)
