from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets_backend import get_secrets_backend
from app.models.entities import Device
from app.plugins.base import DeviceCredentials
from app.schemas.schemas import DeviceCreateRequest, DeviceUpdateRequest


class DeviceNotFoundError(Exception):
    pass


async def create_device(db: AsyncSession, payload: DeviceCreateRequest) -> Device:
    backend = get_secrets_backend()
    device = Device(
        vendor="paloalto",
        mgmt_host=payload.mgmt_host,
        mgmt_port=payload.mgmt_port,
        username=payload.username,
        verify_tls=payload.verify_tls,
        connection_status="unknown",
    )
    db.add(device)
    await db.flush()  # assigns device.id before we need it for the secret path
    device.encrypted_password = backend.store(device.id, "password", payload.password)
    await db.commit()
    await db.refresh(device)
    return device


async def get_device(db: AsyncSession, device_id: str) -> Device:
    device = await db.get(Device, device_id)
    if device is None:
        raise DeviceNotFoundError(f"Device {device_id} not found")
    return device


async def list_devices(db: AsyncSession) -> list[Device]:
    result = await db.execute(select(Device).order_by(Device.created_at.desc()))
    return list(result.scalars().all())


async def update_device(db: AsyncSession, device_id: str, payload: DeviceUpdateRequest) -> Device:
    device = await get_device(db, device_id)
    backend = get_secrets_backend()

    if payload.mgmt_host is not None:
        device.mgmt_host = payload.mgmt_host
    if payload.mgmt_port is not None:
        device.mgmt_port = payload.mgmt_port
    if payload.username is not None:
        device.username = payload.username
    if payload.password is not None:
        device.encrypted_password = backend.store(device.id, "password", payload.password)
        device.encrypted_api_key = None  # force re-auth via username/password next call
    if payload.verify_tls is not None:
        device.verify_tls = payload.verify_tls

    device.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(device)
    return device


async def delete_device(db: AsyncSession, device_id: str) -> None:
    device = await get_device(db, device_id)
    backend = get_secrets_backend()
    if device.encrypted_password:
        backend.delete(device.encrypted_password)
    if device.encrypted_api_key:
        backend.delete(device.encrypted_api_key)
    await db.delete(device)
    await db.commit()


def build_credentials(device: Device) -> DeviceCredentials:
    """Bridges a persisted Device row to the plugin-layer DeviceCredentials,
    resolving the stored reference through whichever secrets backend is
    active — device_service and the plugins it feeds have no idea whether
    that's a Fernet-decrypted blob or a Vault lookup, by design."""
    backend = get_secrets_backend()
    password = backend.retrieve(device.encrypted_password) if device.encrypted_password else None
    api_key = backend.retrieve(device.encrypted_api_key) if device.encrypted_api_key else None

    return DeviceCredentials(
        device_id=device.id,
        mgmt_host=device.mgmt_host,
        mgmt_port=device.mgmt_port,
        username=device.username,
        password=password,
        api_key=api_key,
        verify_tls=device.verify_tls,
    )


async def persist_api_key_if_generated(db: AsyncSession, device: Device, api_key: Optional[str]) -> None:
    """The plugin's client generates and caches an API key in memory per
    connection; we don't currently persist it back (each request re-derives
    credentials from stored username/password, which is simpler and avoids
    a second secret needing rotation/expiry handling). Left as an explicit
    no-op with this docstring so the decision is visible rather than silent."""
    return None
