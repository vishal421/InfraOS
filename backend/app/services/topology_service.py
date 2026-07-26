from __future__ import annotations

from app.core.plugin_registry import get_registry
from app.models.entities import ConfigVersion, Device
from app.plugins.base import NormalizedObject, NormalizedPolicy
from app.services import config_service
from app.services.device_service import get_device


class NoConfigurationError(Exception):
    pass


def _node(node_id: str, node_type: str, label: str) -> dict:
    return {"id": node_id, "type": node_type, "label": label}


def _edge(source: str, target: str, relationship_type: str) -> dict:
    return {"source": source, "target": target, "relationship_type": relationship_type}


async def build_topology(db, device_id: str) -> dict:
    """
    Builds a node/edge graph from the most recently collected running
    configuration. This is Phase-1-scoped on purpose: it reads the
    already-normalized objects/policies/interfaces/zones stored on the
    ConfigVersion row rather than standing up the Neo4j-backed Knowledge
    Graph described in the architecture doc — that upgrade is warranted once
    there's enough cross-vendor/tenant graph traffic to justify the extra
    datastore, not before. The relationship *types* below intentionally
    match the architecture doc's Knowledge Graph Design section so a future
    migration to a real graph store is a storage swap, not a redesign.
    """
    device: Device = await get_device(db, device_id)
    version: ConfigVersion | None = await config_service.get_latest_config_version(db, device_id)
    if version is None:
        raise NoConfigurationError("No configuration collected yet for this device — run Collect Config first")

    plugin = get_registry().get_plugin(device.vendor)
    ai_adapter = plugin.get_ai_context_adapter()

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    device_node_id = f"device:{device.id}"
    nodes[device_node_id] = _node(device_node_id, "device", device.hostname or device.mgmt_host)

    for iface in version.interfaces:
        iface_id = f"interface:{iface['name']}"
        nodes[iface_id] = _node(iface_id, "interface", iface["name"])
        edges.append(_edge(device_node_id, iface_id, "device_has_interface"))

    for zone in version.zones:
        zone_id = f"zone:{zone['name']}"
        nodes[zone_id] = _node(zone_id, "zone", zone["name"])
        for iface_name in zone["interfaces"]:
            iface_id = f"interface:{iface_name}"
            if iface_id not in nodes:
                nodes[iface_id] = _node(iface_id, "interface", iface_name)
            edges.append(_edge(zone_id, iface_id, "zone_contains_interface"))

    for obj in version.objects:
        obj_id = f"object:{obj['name']}"
        nodes[obj_id] = _node(obj_id, "object", obj["name"])

    for policy in version.policies:
        policy_id = f"policy:{policy['name']}"
        nodes[policy_id] = _node(policy_id, "policy", policy["name"])

        normalized_policy = NormalizedPolicy(**policy)
        for raw_edge in ai_adapter.policy_to_graph_edges(normalized_policy):
            dst_type = raw_edge["dst_node_type"]
            dst_ref = raw_edge["dst_ref"]
            dst_id = f"{dst_type}:{dst_ref}"
            if dst_id not in nodes:
                # Reference to something not in our node set yet (e.g. a
                # built-in application or object not present in this
                # snapshot's object list) — add a lightweight placeholder
                # node so the edge still renders rather than silently
                # dropping it.
                nodes[dst_id] = _node(dst_id, dst_type, dst_ref)
            edges.append(_edge(policy_id, dst_id, raw_edge["relationship_type"]))

    return {
        "device_id": device_id,
        "version_num": version.version_num,
        "nodes": list(nodes.values()),
        "edges": edges,
    }
