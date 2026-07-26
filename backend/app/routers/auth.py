from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token
from app.core.deps import CurrentUser, get_current_user, require_admin
from app.db.session import get_db
from app.schemas.schemas import LoginRequest, TokenResponse, UserCreateRequest, UserResponse
from app.services import auth_service
from app.services.auth_service import InvalidCredentialsError, UserExistsError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await auth_service.authenticate(db, payload.username, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token = create_access_token(user.id, user.username, user.role)
    return TokenResponse(access_token=token, role=user.role, username=user.username)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record = await auth_service.get_user(db, user.id)
    if record is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(record)


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreateRequest,
    _: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        user = await auth_service.create_user(db, payload.username, payload.password, payload.role)
    except UserExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserResponse.model_validate(user)
