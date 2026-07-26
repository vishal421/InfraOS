from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_admin, require_operator
from app.db.session import get_db
from app.schemas.schemas import (
    ApproveRequest,
    ChangeRequestCreate,
    ChangeRequestResponse,
    RejectRequest,
    RollbackRequest,
)
from app.services import config_change_service
from app.services.config_change_service import ChangeNotFoundError, InvalidStateTransitionError
from app.services.device_service import DeviceNotFoundError
from app.services.twin_service import invalidate_twin_cache

router = APIRouter(tags=["config-changes"])


@router.post("/api/v1/devices/{device_id}/changes", response_model=ChangeRequestResponse, status_code=201)
async def create_change(device_id: str, payload: ChangeRequestCreate, user: CurrentUser = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    try:
        change = await config_change_service.create_change_request(
            db,
            device_id=device_id,
            action=payload.action,
            target_type=payload.target_type,
            target_name=payload.target_name,
            element_xml=payload.element_xml,
            payload=payload.payload,
            requested_by=user.username,
        )
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChangeRequestResponse.model_validate(change)


@router.get("/api/v1/devices/{device_id}/changes", response_model=list[ChangeRequestResponse])
async def list_changes(device_id: str, db: AsyncSession = Depends(get_db)):
    changes = await config_change_service.list_changes(db, device_id)
    return [ChangeRequestResponse.model_validate(c) for c in changes]


@router.get("/api/v1/changes/{change_id}", response_model=ChangeRequestResponse)
async def get_change(change_id: str, db: AsyncSession = Depends(get_db)):
    try:
        change = await config_change_service.get_change(db, change_id)
    except ChangeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChangeRequestResponse.model_validate(change)


@router.post("/api/v1/changes/{change_id}/validate", response_model=ChangeRequestResponse)
async def validate_change(change_id: str, _: CurrentUser = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    try:
        change = await config_change_service.validate_change(db, change_id)
    except (ChangeNotFoundError, InvalidStateTransitionError) as exc:
        status_code = 404 if isinstance(exc, ChangeNotFoundError) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return ChangeRequestResponse.model_validate(change)


@router.post("/api/v1/changes/{change_id}/approve", response_model=ChangeRequestResponse)
async def approve_change(change_id: str, payload: ApproveRequest, user: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    change_record = await config_change_service.get_change(db, change_id)
    if change_record.requested_by and change_record.requested_by == user.username:
        raise HTTPException(
            status_code=403,
            detail="Four-eyes policy: the approver cannot be the same user who requested the change",
        )
    try:
        change = await config_change_service.approve_change(db, change_id, user.username)
    except (ChangeNotFoundError, InvalidStateTransitionError) as exc:
        status_code = 404 if isinstance(exc, ChangeNotFoundError) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return ChangeRequestResponse.model_validate(change)


@router.post("/api/v1/changes/{change_id}/reject", response_model=ChangeRequestResponse)
async def reject_change(change_id: str, payload: RejectRequest, user: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        change = await config_change_service.reject_change(db, change_id, payload.reason, payload.rejected_by)
    except (ChangeNotFoundError, InvalidStateTransitionError) as exc:
        status_code = 404 if isinstance(exc, ChangeNotFoundError) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return ChangeRequestResponse.model_validate(change)


@router.post("/api/v1/changes/{change_id}/push", response_model=ChangeRequestResponse)
async def push_change(change_id: str, _: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        change = await config_change_service.push_change(db, change_id)
    except (ChangeNotFoundError, InvalidStateTransitionError) as exc:
        status_code = 404 if isinstance(exc, ChangeNotFoundError) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    await invalidate_twin_cache(change.device_id)
    return ChangeRequestResponse.model_validate(change)


@router.post("/api/v1/changes/{change_id}/commit", response_model=ChangeRequestResponse)
async def commit_change(change_id: str, _: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        change = await config_change_service.commit_change(db, change_id)
    except (ChangeNotFoundError, InvalidStateTransitionError) as exc:
        status_code = 404 if isinstance(exc, ChangeNotFoundError) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    await invalidate_twin_cache(change.device_id)
    return ChangeRequestResponse.model_validate(change)


@router.post("/api/v1/changes/{change_id}/rollback", response_model=ChangeRequestResponse)
async def rollback_change(change_id: str, payload: RollbackRequest, _: CurrentUser = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    try:
        change = await config_change_service.rollback_change(db, change_id, payload.to_version)
    except (ChangeNotFoundError, InvalidStateTransitionError) as exc:
        status_code = 404 if isinstance(exc, ChangeNotFoundError) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    await invalidate_twin_cache(change.device_id)
    return ChangeRequestResponse.model_validate(change)
