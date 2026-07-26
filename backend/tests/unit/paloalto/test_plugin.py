from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from app.plugins.base import ConnectionStatus, ConfigSnapshotType, DeviceCredentials
from app.plugins.installed.paloalto.plugin import PaloAltoPlugin

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "paloalto"
BASE = "https://fw-test:443"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


def _route_by_cmd_or_type(request: httpx.Request) -> httpx.Response:
    """Central fake PAN-OS responder: inspects query params and returns the
    right fixture, the way a real device would respond differently per
    request type. This lets one respx mock stand in for a whole session
    (keygen -> system info -> ha state -> license info) in discover()."""
    params = parse_qs(urlparse(str(request.url)).query)
    req_type = params.get("type", [""])[0]
    cmd = params.get("cmd", [""])[0]

    if req_type == "keygen":
        return httpx.Response(200, text='<response status="success"><result><key>test-key</key></result></response>')
    if "system><info" in cmd:
        return httpx.Response(200, text=fixture_text("system_info.xml"))
    if "high-availability" in cmd:
        return httpx.Response(200, text=fixture_text("ha_state_standalone.xml"))
    if "license><info" in cmd:
        return httpx.Response(200, text=fixture_text("licenses.xml"))
    if req_type == "config":
        return httpx.Response(200, text=fixture_text("running_config.xml"))

    return httpx.Response(200, text='<response status="success"><result/></response>')


@pytest.fixture
def creds() -> DeviceCredentials:
    return DeviceCredentials(device_id="dev-1", mgmt_host="fw-test", username="admin", password="secret")


@pytest.mark.asyncio
@respx.mock
async def test_test_connectivity_online(creds):
    respx.get(f"{BASE}/api/").mock(side_effect=_route_by_cmd_or_type)
    plugin = PaloAltoPlugin()
    result = await plugin.test_connectivity(creds)
    assert result.status == ConnectionStatus.ONLINE
    assert result.reachable is True
    assert result.authenticated is True
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_discover_returns_full_result(creds):
    respx.get(f"{BASE}/api/").mock(side_effect=_route_by_cmd_or_type)
    plugin = PaloAltoPlugin()
    result = await plugin.discover(creds)
    assert result.hostname == "fw-branch-01"
    assert result.model == "PA-440"
    assert result.os_version == "10.2.4"
    assert result.ha_state.value == "standalone"
    assert len(result.licenses) == 2
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_collect_configuration_normalizes_full_snapshot(creds):
    respx.get(f"{BASE}/api/").mock(side_effect=_route_by_cmd_or_type)
    plugin = PaloAltoPlugin()
    snapshot = await plugin.collect_configuration(creds, ConfigSnapshotType.RUNNING)

    assert snapshot.device_id == "dev-1"
    assert len(snapshot.interfaces) == 2
    assert len(snapshot.zones) == 2
    assert any(o.name == "finance-server-1" for o in snapshot.objects)
    assert any(p.name == "allow-finance-to-sap" for p in snapshot.policies)
    assert snapshot.config_hash  # non-empty
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_ai_adapter_converts_policy_to_edges(creds):
    respx.get(f"{BASE}/api/").mock(side_effect=_route_by_cmd_or_type)
    plugin = PaloAltoPlugin()
    snapshot = await plugin.collect_configuration(creds, ConfigSnapshotType.RUNNING)
    adapter = plugin.get_ai_context_adapter()

    policy = next(p for p in snapshot.policies if p.name == "allow-finance-to-sap")
    edges = adapter.policy_to_graph_edges(policy)

    relationship_types = {e["relationship_type"] for e in edges}
    assert "policy_from_zone" in relationship_types
    assert "policy_to_zone" in relationship_types
    assert "policy_references_object" in relationship_types
    await plugin.close()


def test_parse_resources_extracts_cpu_and_mem():
    """Regression test: an earlier version of this parser had a stray
    `if line.startswith('%cpu'): continue` that skipped the exact line it
    needed to read, silently dropping cpu_utilization_pct from every
    metrics collection. Caught via end-to-end testing against a fake
    device, not by unit tests alone — this test exists so it can't
    reappear silently."""
    import xml.etree.ElementTree as ET

    xml = (
        '<response status="success"><result>load average: 0.10, 0.08, 0.05\n'
        "Tasks: 120 total, 1 running\n"
        "%Cpu(s):  12.3 us,  2.1 sy,  0.0 ni, 85.0 id,  0.0 wa\n"
        "KiB Mem:  4046656 total,  2100000 free,  1200000 used\n"
        "</result></response>"
    )
    root = ET.fromstring(xml)
    cpu, mem = PaloAltoPlugin._parse_resources(root)
    assert cpu == pytest.approx(15.0)
    assert mem is not None and 40 < mem < 60


@pytest.mark.asyncio
@respx.mock
async def test_commit_polls_until_job_finishes():
    call_count = {"n": 0}

    def commit_responder(request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlparse(str(request.url)).query)
        req_type = params.get("type", [""])[0]
        if req_type == "keygen":
            return httpx.Response(200, text='<response status="success"><result><key>test-key</key></result></response>')
        if req_type == "commit":
            return httpx.Response(
                200,
                text='<response status="success"><result><job>77</job></result></response>',
            )
        if req_type == "op" and "jobs" in params.get("cmd", [""])[0]:
            call_count["n"] += 1
            status = "FIN" if call_count["n"] >= 2 else "ACT"
            return httpx.Response(
                200,
                text=f'<response status="success"><result><job><status>{status}</status><result>OK</result></job></result></response>',
            )
        return httpx.Response(200, text='<response status="success"><result/></response>')

    respx.get(f"{BASE}/api/").mock(side_effect=commit_responder)
    plugin = PaloAltoPlugin()
    creds = DeviceCredentials(device_id="dev-1", mgmt_host="fw-test", username="admin", password="secret")

    result = await plugin.commit(creds)
    assert result.success is True
    assert result.job_id == "77"
    assert call_count["n"] == 2  # polled twice before FIN
    await plugin.close()
