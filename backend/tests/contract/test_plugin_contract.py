"""
Runs against every plugin in the default registry. This is what makes
"future vendors can be added without changing core platform code" an
enforced fact rather than an aspiration — a plugin that doesn't fully
implement the contract fails CI here, before it ever reaches a domain
service.
"""
from __future__ import annotations

import inspect

import pytest

from app.plugins.base import VendorPlugin
from app.plugins.registry import build_default_registry


@pytest.fixture(scope="module")
def registry():
    reg = build_default_registry()
    yield reg


def test_registry_loads_without_error(registry):
    assert len(registry.list_vendors()) > 0


@pytest.mark.parametrize("vendor_name", ["paloalto", "fortinet"])
def test_plugin_implements_full_contract(registry, vendor_name):
    plugin = registry.get_plugin(vendor_name)

    required_methods = [
        name
        for name, member in inspect.getmembers(VendorPlugin, predicate=inspect.isfunction)
        if getattr(member, "__isabstractmethod__", False)
    ]

    for method_name in required_methods:
        assert hasattr(plugin, method_name), f"{vendor_name} plugin missing {method_name}"
        bound = getattr(plugin, method_name)
        assert callable(bound), f"{vendor_name}.{method_name} is not callable"


@pytest.mark.parametrize("vendor_name", ["paloalto", "fortinet"])
def test_plugin_declares_metadata(registry, vendor_name):
    plugin = registry.get_plugin(vendor_name)
    assert isinstance(plugin.vendor_name, str) and plugin.vendor_name
    assert isinstance(plugin.supported_versions, list) and len(plugin.supported_versions) > 0


@pytest.mark.parametrize("vendor_name", ["paloalto", "fortinet"])
def test_ai_context_adapter_is_provided(registry, vendor_name):
    plugin = registry.get_plugin(vendor_name)
    adapter = plugin.get_ai_context_adapter()
    assert adapter is not None
    assert hasattr(adapter, "policy_to_graph_edges")
    assert hasattr(adapter, "object_to_text_chunk")
    assert hasattr(adapter, "snapshot_to_summary")
