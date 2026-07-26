from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugin_registry import get_registry
from app.models.entities import Device, HealthEvent
from app.plugins.base import (
    AuthenticationError,
    ConnectionStatus,
    ConnectivityError,
    ConnectivityResult,
    DeviceDiscoveryResult,
    PluginError,
    UnsupportedVersionError,
)
from app.services.device_service import build_credentials, get_device


class DeviceDiscoveryError(Exception):
    """Raised when discover_device() cannot complete because of a plugin-layer
    failure (unreachable device, auth rejected, unsupported OS version, or any
    other vendor error). This is what the router catches to return a clean
    4xx/502 response instead of the request 500ing — previously the plugin's
    PluginError subclasses (AuthenticationError, ConnectivityError,
    UnsupportedVersionError, ConfigCollectionError) were left uncaught here,
    so any of those bubbled all the way up as an unhandled exception."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


async def test_connectivity(db: AsyncSession, device_id: str) -> ConnectivityResult:
    device = await get_device(db, device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    result = await plugin.test_connectivity(creds)

    device.connection_status = result.status.value
    device.last_connectivity_check_at = datetime.now(timezone.utc)
    await db.commit()

    if result.status != ConnectionStatus.ONLINE:
        db.add(
            HealthEvent(
                device_id=device.id,
                severity="critical" if result.status == ConnectionStatus.UNREACHABLE else "warning",
                category="connectivity",
                message=result.error_detail or f"Connectivity status: {result.status.value}",
            )
        )
        await db.commit()

    return result


async def _record_discovery_failure(db: AsyncSession, device: Device, status, detail: str) -> None:
    status_value = status.value if isinstance(status, ConnectionStatus) else status
    device.connection_status = status_value
    device.last_connectivity_check_at = datetime.now(timezone.utc)
    db.add(
        HealthEvent(
            device_id=device.id,
            severity="critical" if status_value == ConnectionStatus.UNREACHABLE.value else "warning",
            category="connectivity",
            message=f"Discovery failed: {detail}",
        )
    )
    await db.commit()


async def discover_device(db: AsyncSession, device_id: str) -> DeviceDiscoveryResult:
    device = await get_device(db, device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    try:
        result = await plugin.discover(creds)
    except AuthenticationError as exc:
        await _record_discovery_failure(db, device, ConnectionStatus.AUTH_FAILED, str(exc))
        raise DeviceDiscoveryError(f"Authentication failed while discovering device: {exc}", status_code=401) from exc
    except UnsupportedVersionError as exc:
        await _record_discovery_failure(db, device, ConnectionStatus.UNSUPPORTED_VERSION, str(exc))
        raise DeviceDiscoveryError(str(exc), status_code=422) from exc
    except ConnectivityError as exc:
        await _record_discovery_failure(db, device, ConnectionStatus.UNREACHABLE, str(exc))
        raise DeviceDiscoveryError(f"Could not reach device to discover it: {exc}", status_code=502) from exc
    except PluginError as exc:
        # Catch-all for any other vendor-raised error (e.g. ConfigCollectionError
        # wrapping a malformed API response) so it never reaches the router as
        # an unhandled exception.
        await _record_discovery_failure(db, device, device.connection_status or ConnectionStatus.UNREACHABLE.value, str(exc))
        raise DeviceDiscoveryError(f"Discovery failed: {exc}", status_code=502) from exc

    device.hostname = result.hostname
    device.model = result.model
    device.serial = result.serial
    device.os_version = result.os_version
    device.ha_state = result.ha_state.value
    device.ha_peer_serial = result.ha_peer_serial
    device.uptime_seconds = result.uptime_seconds
    device.licenses = [lic.model_dump(mode="json") for lic in result.licenses]
    device.last_discovered_at = datetime.now(timezone.utc)
    await db.commit()

    expired = [lic for lic in result.licenses if lic.expired]
    if expired:
        db.add(
            HealthEvent(
                device_id=device.id,
                severity="warning",
                category="license",
                message=f"{len(expired)} expired license(s): {', '.join(l.feature for l in expired)}",
            )
        )
        await db.commit()

    return result
