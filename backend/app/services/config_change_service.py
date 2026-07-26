from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugin_registry import get_registry
from app.models.change_request import ConfigChangeRequest
from app.models.entities import ConfigVersion
from app.plugins.base import ChangeAction, ConfigChange, PluginError
from app.services import config_service
from app.services.device_service import build_credentials, get_device


class ChangeNotFoundError(Exception):
    pass


class InvalidStateTransitionError(Exception):
    pass


VALID_TARGET_TYPES = {
    "address_object",
    "address_group",
    "service_object",
    "service_group",
    "security_policy",
    "nat_policy",
}


async def create_change_request(
    db: AsyncSession,
    device_id: str,
    action: str,
    target_type: str,
    target_name: str,
    element_xml: str | None,
    payload: dict,
    requested_by: str | None = None,
) -> ConfigChangeRequest:
    await get_device(db, device_id)  # 404s if missing
    if target_type not in VALID_TARGET_TYPES:
        raise ValueError(f"Unknown target_type '{target_type}'. Must be one of {sorted(VALID_TARGET_TYPES)}")

    change = ConfigChangeRequest(
        device_id=device_id,
        action=action,
        target_type=target_type,
        target_name=target_name,
        element_xml=element_xml,
        payload=payload,
        status="draft",
        requested_by=requested_by,
    )
    db.add(change)
    await db.commit()
    await db.refresh(change)
    return change


async def get_change(db: AsyncSession, change_id: str) -> ConfigChangeRequest:
    change = await db.get(ConfigChangeRequest, change_id)
    if change is None:
        raise ChangeNotFoundError(f"Change request {change_id} not found")
    return change


async def list_changes(db: AsyncSession, device_id: str) -> list[ConfigChangeRequest]:
    result = await db.execute(
        select(ConfigChangeRequest)
        .where(ConfigChangeRequest.device_id == device_id)
        .order_by(ConfigChangeRequest.created_at.desc())
    )
    return list(result.scalars().all())


def _require_status(change: ConfigChangeRequest, *allowed: str) -> None:
    if change.status not in allowed:
        raise InvalidStateTransitionError(
            f"Change {change.id} is in status '{change.status}', expected one of {allowed}"
        )


async def _compute_impact(db: AsyncSession, device_id: str, target_name: str) -> dict:
    """Deliberately simple impact analysis: how many policies in the latest
    collected config reference this object name anywhere (source, destination,
    service, application). Enough to drive an approval decision and an
    explanation; a full Knowledge-Graph traversal (per the architecture doc)
    is the natural upgrade path once the graph/topology layer exists."""
    latest = await config_service.get_latest_config_version(db, device_id)
    if latest is None:
        return {"affected_policies": [], "note": "no configuration collected yet — impact unknown"}

    affected = []
    for policy in latest.policies:
        refs = set(policy.get("source", [])) | set(policy.get("destination", [])) | set(
            policy.get("service", [])
        ) | set(policy.get("application", []))
        if target_name in refs:
            affected.append(policy["name"])

    return {"affected_policies": affected, "affected_count": len(affected)}


def _build_config_change(change: ConfigChangeRequest) -> ConfigChange:
    return ConfigChange(
        change_id=change.id,
        action=ChangeAction(change.action),
        target_type=change.target_type,
        target_name=change.target_name,
        element_xml=change.element_xml,
        payload=change.payload,
    )


async def validate_change(db: AsyncSession, change_id: str) -> ConfigChangeRequest:
    change = await get_change(db, change_id)
    _require_status(change, "draft", "validation_failed")

    device = await get_device(db, change.device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    try:
        result = await plugin.validate_change(creds, _build_config_change(change))
    except PluginError as exc:
        change.status = "validation_failed"
        change.error_detail = str(exc)
        await db.commit()
        await db.refresh(change)
        return change

    change.validation_errors = result.errors
    change.validation_warnings = result.warnings
    change.impact_summary = await _compute_impact(db, change.device_id, change.target_name)

    if result.valid:
        change.status = "pending_approval"
    else:
        change.status = "validation_failed"

    await db.commit()
    await db.refresh(change)
    return change


async def approve_change(db: AsyncSession, change_id: str, approved_by: str | None = None) -> ConfigChangeRequest:
    change = await get_change(db, change_id)
    _require_status(change, "pending_approval")
    change.status = "approved"
    change.approved_by = approved_by
    await db.commit()
    await db.refresh(change)
    return change


async def reject_change(db: AsyncSession, change_id: str, reason: str, rejected_by: str | None = None) -> ConfigChangeRequest:
    change = await get_change(db, change_id)
    _require_status(change, "pending_approval")
    change.status = "rejected"
    change.rejection_reason = reason
    change.approved_by = rejected_by
    await db.commit()
    await db.refresh(change)
    return change


async def push_change(db: AsyncSession, change_id: str) -> ConfigChangeRequest:
    """
    Requires APPROVED status — this is the enforced human-approval gate.
    There is no code path in this service that reaches push_configuration()
    from any status other than 'approved'.
    """
    change = await get_change(db, change_id)
    _require_status(change, "approved")

    device = await get_device(db, change.device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    try:
        result = await plugin.push_configuration(creds, _build_config_change(change))
    except PluginError as exc:
        change.status = "push_failed"
        change.error_detail = str(exc)
        await db.commit()
        await db.refresh(change)
        return change

    change.status = "pushed" if result.success else "push_failed"
    change.error_detail = result.error_detail
    await db.commit()
    await db.refresh(change)
    return change


async def commit_change(db: AsyncSession, change_id: str) -> ConfigChangeRequest:
    change = await get_change(db, change_id)
    _require_status(change, "pushed")

    device = await get_device(db, change.device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    try:
        result = await plugin.commit(creds)
    except PluginError as exc:
        change.status = "commit_failed"
        change.error_detail = str(exc)
        await db.commit()
        await db.refresh(change)
        return change

    change.status = "committed" if result.success else "commit_failed"
    change.commit_job_id = result.job_id
    change.error_detail = result.error_detail
    await db.commit()
    await db.refresh(change)

    # Refresh config version history so the new committed state shows up as
    # the latest version rather than waiting for the next poller cycle.
    if result.success:
        try:
            await config_service.collect_configuration(db, change.device_id)
        except PluginError:
            pass  # non-fatal — the scheduled poller will pick it up

    return change


async def rollback_change(db: AsyncSession, change_id: str, to_version: str) -> ConfigChangeRequest:
    change = await get_change(db, change_id)
    _require_status(change, "pushed", "commit_failed", "committed")

    device = await get_device(db, change.device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    result = await plugin.rollback(creds, to_version)
    change.status = "rolled_back" if result.success else change.status
    change.error_detail = result.error_detail
    await db.commit()
    await db.refresh(change)
    return change
