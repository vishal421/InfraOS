"""
Plugin registry. This is the ONLY place the core platform imports a vendor
plugin's concrete class. Every other module (domain services, API routers,
AI layer) calls PluginRegistry.get_plugin(vendor_name) and works only against
the VendorPlugin interface.

Adding a vendor: implement VendorPlugin in plugins/installed/<vendor>/, then
add one line to _load_builtin_plugins(). No other code changes required.
"""

from __future__ import annotations

import inspect
import logging

from app.plugins.base import VendorPlugin

logger = logging.getLogger("infraos.plugins.registry")


class PluginRegistrationError(Exception):
    pass


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, VendorPlugin] = {}

    def register(self, plugin: VendorPlugin) -> None:
        self._validate_contract(plugin)
        if plugin.vendor_name in self._plugins:
            raise PluginRegistrationError(f"Plugin '{plugin.vendor_name}' is already registered")
        self._plugins[plugin.vendor_name] = plugin
        logger.info("Registered plugin: %s (versions: %s)", plugin.vendor_name, plugin.supported_versions)

    def get_plugin(self, vendor_name: str) -> VendorPlugin:
        try:
            return self._plugins[vendor_name]
        except KeyError as exc:
            raise PluginRegistrationError(
                f"No plugin registered for vendor '{vendor_name}'. Registered: {list(self._plugins)}"
            ) from exc

    def list_vendors(self) -> list[str]:
        return list(self._plugins.keys())

    async def close_all(self) -> None:
        for plugin in self._plugins.values():
            await plugin.close()

    @staticmethod
    def _validate_contract(plugin: VendorPlugin) -> None:
        """Fails loudly at registration time if a plugin doesn't fully
        implement the interface, rather than failing at first call in
        production. This is deliberately stricter than Python's ABC
        enforcement alone (which only catches missing methods, not attribute
        presence)."""
        if not getattr(plugin, "vendor_name", None):
            raise PluginRegistrationError(f"{type(plugin).__name__} must set a non-empty vendor_name")
        if not getattr(plugin, "supported_versions", None):
            raise PluginRegistrationError(f"{type(plugin).__name__} must declare supported_versions")

        required_methods = [
            name
            for name, member in inspect.getmembers(VendorPlugin, predicate=inspect.isfunction)
            if getattr(member, "__isabstractmethod__", False)
        ]
        for method_name in required_methods:
            impl = getattr(type(plugin), method_name, None)
            base_impl = getattr(VendorPlugin, method_name)
            if impl is None or impl is base_impl:
                raise PluginRegistrationError(
                    f"{type(plugin).__name__} does not implement required method '{method_name}'"
                )


def build_default_registry() -> PluginRegistry:
    """Wires up all built-in plugins. Called once at app startup."""
    registry = PluginRegistry()

    from app.plugins.installed.paloalto.plugin import PaloAltoPlugin
    from app.plugins.installed.fortinet.plugin import FortinetPlugin

    registry.register(PaloAltoPlugin())
    registry.register(FortinetPlugin())

    return registry
