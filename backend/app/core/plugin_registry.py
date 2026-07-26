from __future__ import annotations

from app.plugins.registry import PluginRegistry, build_default_registry

_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry
