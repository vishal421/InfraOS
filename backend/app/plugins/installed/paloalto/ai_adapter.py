from __future__ import annotations

from typing import Any

from app.plugins.base import AIContextAdapter, ConfigSnapshot, NormalizedObject, NormalizedPolicy


class PaloAltoAIContextAdapter(AIContextAdapter):
    """
    Converts Palo Alto normalized objects into:
      1) graph edges for the Knowledge Graph (topology.edges rows)
      2) flat text chunks for RAG embedding (ai.knowledge_chunks rows)

    Kept deliberately dumb/mechanical — no LLM calls happen here. This is
    pure data transformation so the AI layer's retrieval quality depends on
    deterministic facts, not on a model summarizing correctly.
    """

    def policy_to_graph_edges(self, policy: NormalizedPolicy) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for zone in policy.source_zones:
            edges.append(
                {
                    "src_node_type": "policy",
                    "src_ref": policy.name,
                    "dst_node_type": "zone",
                    "dst_ref": zone,
                    "relationship_type": "policy_from_zone",
                }
            )
        for zone in policy.destination_zones:
            edges.append(
                {
                    "src_node_type": "policy",
                    "src_ref": policy.name,
                    "dst_node_type": "zone",
                    "dst_ref": zone,
                    "relationship_type": "policy_to_zone",
                }
            )
        for obj_name in (*policy.source, *policy.destination):
            edges.append(
                {
                    "src_node_type": "policy",
                    "src_ref": policy.name,
                    "dst_node_type": "object",
                    "dst_ref": obj_name,
                    "relationship_type": "policy_references_object",
                }
            )
        for app in policy.application:
            edges.append(
                {
                    "src_node_type": "policy",
                    "src_ref": policy.name,
                    "dst_node_type": "application",
                    "dst_ref": app,
                    "relationship_type": "policy_allows_application",
                }
            )
        return edges

    def object_to_text_chunk(self, obj: NormalizedObject) -> str:
        return (
            f"{obj.object_type.value} object '{obj.name}': "
            f"{', '.join(f'{k}={v}' for k, v in obj.definition.items() if v)}"
        )

    def snapshot_to_summary(self, snapshot: ConfigSnapshot) -> str:
        return (
            f"Configuration snapshot ({snapshot.snapshot_type.value}) for device {snapshot.device_id}: "
            f"{len(snapshot.interfaces)} interfaces, {len(snapshot.zones)} zones, "
            f"{len(snapshot.objects)} objects, {len(snapshot.policies)} policies. "
            f"Collected at {snapshot.collected_at.isoformat()}."
        )
