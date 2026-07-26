from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password, verify_password
from app.models.user import VALID_ROLES, User


class UserExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


async def user_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return result.scalar_one()


async def create_user(db: AsyncSession, username: str, password: str, role: str) -> User:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalars().first() is not None:
        raise UserExistsError(f"Username '{username}' already exists")

    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, username: str, password: str) -> User:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid username or password")
    return user


async def get_user(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, user_id)


async def ensure_bootstrap_admin(db: AsyncSession, username: str, password: str) -> None:
    """Creates a default admin user only if the users table is completely
    empty — safe to call on every startup. Logged loudly so it's never a
    silent surprise which credentials are active."""
    import logging

    logger = logging.getLogger("infraos.auth")
    if await user_count(db) > 0:
        return
    await create_user(db, username, password, role="admin")
    logger.warning(
        "No users existed — bootstrapped default admin user '%s'. "
        "Change this password immediately in a real deployment.",
        username,
    )
