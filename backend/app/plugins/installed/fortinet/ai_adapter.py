from __future__ import annotations

from typing import Any

from app.plugins.base import AIContextAdapter, ConfigSnapshot, NormalizedObject, NormalizedPolicy


class FortinetAIContextAdapter(AIContextAdapter):
    def policy_to_graph_edges(self, policy: NormalizedPolicy) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for zone in policy.source_zones:
            edges.append(
                {"src_node_type": "policy", "src_ref": policy.name, "dst_node_type": "zone", "dst_ref": zone, "relationship_type": "policy_from_zone"}
            )
        for zone in policy.destination_zones:
            edges.append(
                {"src_node_type": "policy", "src_ref": policy.name, "dst_node_type": "zone", "dst_ref": zone, "relationship_type": "policy_to_zone"}
            )
        for obj_name in (*policy.source, *policy.destination):
            edges.append(
                {"src_node_type": "policy", "src_ref": policy.name, "dst_node_type": "object", "dst_ref": obj_name, "relationship_type": "policy_references_object"}
            )
        return edges

    def object_to_text_chunk(self, obj: NormalizedObject) -> str:
        return f"{obj.object_type.value} object '{obj.name}': {', '.join(f'{k}={v}' for k, v in obj.definition.items() if v)}"

    def snapshot_to_summary(self, snapshot: ConfigSnapshot) -> str:
        return (
            f"Configuration snapshot ({snapshot.snapshot_type.value}) for device {snapshot.device_id}: "
            f"{len(snapshot.interfaces)} interfaces, {len(snapshot.objects)} objects, {len(snapshot.policies)} policies."
        )
