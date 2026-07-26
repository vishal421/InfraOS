from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plugin_registry import get_registry
from app.models.entities import ConfigVersion, Device, HealthEvent
from app.plugins.base import ConfigSnapshot, ConfigSnapshotType
from app.services.device_service import build_credentials, get_device


def _diff_named_items(previous: list[dict], current: list[dict]) -> dict[str, list[str]]:
    """Diffs two lists of dict-like items (each having a 'name' key) by name,
    and flags name-matches whose serialized content differs as 'changed'.
    Kept deliberately simple (whole-object equality, not field-level diff) —
    good enough to drive "what changed" summaries and drift flags; a
    field-level diff view is a natural follow-up for the version-history UI."""
    prev_by_name = {item["name"]: item for item in previous}
    curr_by_name = {item["name"]: item for item in current}

    added = sorted(set(curr_by_name) - set(prev_by_name))
    removed = sorted(set(prev_by_name) - set(curr_by_name))
    changed = sorted(
        name
        for name in set(curr_by_name) & set(prev_by_name)
        if curr_by_name[name] != prev_by_name[name]
    )
    return {"added": added, "removed": removed, "changed": changed}


def _build_diff_summary(previous: ConfigVersion | None, snapshot: ConfigSnapshot) -> dict[str, Any]:
    current_objects = [o.model_dump(mode="json") for o in snapshot.objects]
    current_policies = [p.model_dump(mode="json") for p in snapshot.policies]
    current_interfaces = [i.model_dump(mode="json") for i in snapshot.interfaces]
    current_zones = [z.model_dump(mode="json") for z in snapshot.zones]

    if previous is None:
        return {
            "objects": {"added": [o["name"] for o in current_objects], "removed": [], "changed": []},
            "policies": {"added": [p["name"] for p in current_policies], "removed": [], "changed": []},
            "interfaces": {"added": [i["name"] for i in current_interfaces], "removed": [], "changed": []},
            "zones": {"added": [z["name"] for z in current_zones], "removed": [], "changed": []},
        }

    return {
        "objects": _diff_named_items(previous.objects, current_objects),
        "policies": _diff_named_items(previous.policies, current_policies),
        "interfaces": _diff_named_items(previous.interfaces, current_interfaces),
        "zones": _diff_named_items(previous.zones, current_zones),
    }


def _summary_is_empty(summary: dict[str, Any]) -> bool:
    return all(not category["added"] and not category["removed"] and not category["changed"] for category in summary.values())


async def collect_configuration(
    db: AsyncSession, device_id: str, snapshot_type: ConfigSnapshotType = ConfigSnapshotType.RUNNING
) -> ConfigVersion:
    device = await get_device(db, device_id)
    creds = build_credentials(device)
    plugin = get_registry().get_plugin(device.vendor)

    snapshot = await plugin.collect_configuration(creds, snapshot_type)

    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.device_id == device_id, ConfigVersion.snapshot_type == snapshot_type.value)
        .order_by(ConfigVersion.version_num.desc())
        .limit(1)
    )
    previous = result.scalars().first()

    if previous is not None and previous.config_hash == snapshot.config_hash:
        # No change since last collection — don't create a redundant version row,
        # just record that we re-checked.
        device.last_config_collected_at = datetime.now(timezone.utc)
        await db.commit()
        return previous

    diff_summary = _build_diff_summary(previous, snapshot)
    # "Drift" here means a difference was detected between two collections
    # of the device's own config over time. The platform doesn't yet track
    # which changes were platform-initiated vs made directly on the device
    # (that requires the Configuration Engine / change-request flow, not
    # built in this pass) — so every new version after the first is flagged
    # as drift until that distinction exists. Treat this flag as "config
    # changed since we last looked", not yet as "unauthorized change".
    is_drift = previous is not None and not _summary_is_empty(diff_summary)

    version = ConfigVersion(
        device_id=device_id,
        version_num=(previous.version_num + 1) if previous else 1,
        snapshot_type=snapshot_type.value,
        config_hash=snapshot.config_hash,
        interface_count=len(snapshot.interfaces),
        zone_count=len(snapshot.zones),
        object_count=len(snapshot.objects),
        policy_count=len(snapshot.policies),
        interfaces=[i.model_dump(mode="json") for i in snapshot.interfaces],
        zones=[z.model_dump(mode="json") for z in snapshot.zones],
        objects=[o.model_dump(mode="json") for o in snapshot.objects],
        policies=[p.model_dump(mode="json") for p in snapshot.policies],
        diff_summary=diff_summary,
        is_drift=is_drift,
    )
    db.add(version)

    device.last_config_collected_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(version)

    if is_drift:
        db.add(
            HealthEvent(
                device_id=device_id,
                severity="warning",
                category="config_drift",
                message=(
                    f"Configuration changed since last collection: "
                    f"{sum(len(c['added']) + len(c['removed']) + len(c['changed']) for c in diff_summary.values())} "
                    f"item(s) affected across objects/policies/interfaces/zones."
                ),
            )
        )
        await db.commit()

    return version


async def list_config_versions(db: AsyncSession, device_id: str, snapshot_type: str = "running") -> list[ConfigVersion]:
    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.device_id == device_id, ConfigVersion.snapshot_type == snapshot_type)
        .order_by(ConfigVersion.version_num.desc())
    )
    return list(result.scalars().all())


async def get_config_version(db: AsyncSession, version_id: str) -> ConfigVersion | None:
    return await db.get(ConfigVersion, version_id)


async def get_latest_config_version(db: AsyncSession, device_id: str, snapshot_type: str = "running") -> ConfigVersion | None:
    result = await db.execute(
        select(ConfigVersion)
        .where(ConfigVersion.device_id == device_id, ConfigVersion.snapshot_type == snapshot_type)
        .order_by(ConfigVersion.version_num.desc())
        .limit(1)
    )
    return result.scalars().first()
