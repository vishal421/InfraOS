from __future__ import annotations

import pytest
import respx
import httpx

from app.plugins.base import ChangeAction, ConfigChange, ConfigSnapshotType, ConnectionStatus, DeviceCredentials
from app.plugins.installed.fortinet.plugin import FortinetPlugin

BASE = "https://fw-test:443"


@pytest.fixture
def creds() -> DeviceCredentials:
    return DeviceCredentials(device_id="forti-1", mgmt_host="fw-test", api_key="test-token")


@pytest.mark.asyncio
@respx.mock
async def test_test_connectivity_online(creds):
    respx.get(f"{BASE}/api/v2/monitor/system/status").mock(
        return_value=httpx.Response(200, json={"results": {"hostname": "forti-01", "version": "v7.2.5", "serial": "FG100E1"}})
    )
    plugin = FortinetPlugin()
    result = await plugin.test_connectivity(creds)
    assert result.status == ConnectionStatus.ONLINE
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_test_connectivity_auth_failed(creds):
    respx.get(f"{BASE}/api/v2/monitor/system/status").mock(return_value=httpx.Response(401, json={}))
    plugin = FortinetPlugin()
    result = await plugin.test_connectivity(creds)
    assert result.status == ConnectionStatus.AUTH_FAILED
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_discover(creds):
    respx.get(f"{BASE}/api/v2/monitor/system/status").mock(
        return_value=httpx.Response(200, json={"results": {"hostname": "forti-01", "version": "v7.2.5", "serial": "FG100E1", "model_name": "FortiGate-100E"}})
    )
    respx.get(f"{BASE}/api/v2/monitor/system/ha-status").mock(
        return_value=httpx.Response(200, json={"results": {"mode": "standalone"}})
    )
    plugin = FortinetPlugin()
    result = await plugin.discover(creds)
    assert result.hostname == "forti-01"
    assert result.model == "FortiGate-100E"
    assert result.ha_state.value == "standalone"
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_collect_configuration(creds):
    respx.get(f"{BASE}/api/v2/cmdb/system/interface").mock(
        return_value=httpx.Response(200, json={"results": [{"name": "port1", "ip": "10.0.1.1 255.255.255.0", "status": "up"}]})
    )
    respx.get(f"{BASE}/api/v2/cmdb/system/zone").mock(
        return_value=httpx.Response(200, json={"results": [{"name": "trust", "interface": [{"interface-name": "port1"}]}]})
    )
    respx.get(f"{BASE}/api/v2/cmdb/firewall/address").mock(
        return_value=httpx.Response(200, json={"results": [{"name": "finance-server-1", "subnet": "10.0.1.50 255.255.255.255"}]})
    )
    respx.get(f"{BASE}/api/v2/cmdb/firewall/service/custom").mock(
        return_value=httpx.Response(200, json={"results": [{"name": "https-custom", "protocol": "TCP", "tcp-portrange": "443"}]})
    )
    respx.get(f"{BASE}/api/v2/cmdb/firewall/policy").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "policyid": 1,
                        "name": "allow-finance",
                        "srcintf": [{"name": "trust"}],
                        "dstintf": [{"name": "untrust"}],
                        "srcaddr": [{"name": "finance-server-1"}],
                        "dstaddr": [{"name": "all"}],
                        "service": [{"name": "HTTPS"}],
                        "action": "accept",
                    }
                ]
            },
        )
    )
    plugin = FortinetPlugin()
    snapshot = await plugin.collect_configuration(creds, ConfigSnapshotType.RUNNING)
    assert len(snapshot.interfaces) == 1
    assert len(snapshot.zones) == 1
    assert any(o.name == "finance-server-1" for o in snapshot.objects)
    assert snapshot.policies[0].name == "allow-finance"
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_candidate_snapshot_type_unsupported(creds):
    plugin = FortinetPlugin()
    with pytest.raises(Exception):
        await plugin.collect_configuration(creds, ConfigSnapshotType.CANDIDATE)
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_validate_change_requires_fields(creds):
    plugin = FortinetPlugin()
    change = ConfigChange(change_id="c1", action=ChangeAction.CREATE, target_type="address_object", target_name="new-obj", payload={})
    result = await plugin.validate_change(creds, change)
    assert result.valid is False
    assert "subnet" in result.errors[0]
    await plugin.close()


@pytest.mark.asyncio
@respx.mock
async def test_push_configuration_creates_object(creds):
    route = respx.post(f"{BASE}/api/v2/cmdb/firewall/address").mock(
        return_value=httpx.Response(200, json={"status": "success"})
    )
    plugin = FortinetPlugin()
    change = ConfigChange(
        change_id="c1", action=ChangeAction.CREATE, target_type="address_object", target_name="new-obj",
        payload={"subnet": "10.0.5.5 255.255.255.255"},
    )
    result = await plugin.push_configuration(creds, change)
    assert result.success is True
    assert route.called
    await plugin.close()


@pytest.mark.asyncio
async def test_commit_is_noop_success(creds):
    plugin = FortinetPlugin()
    result = await plugin.commit(creds)
    assert result.success is True
    assert "no separate commit step" in result.warnings[0]
    await plugin.close()


@pytest.mark.asyncio
async def test_rollback_reports_unsupported(creds):
    plugin = FortinetPlugin()
    result = await plugin.rollback(creds, "some-version")
    assert result.success is False
    assert "not implemented" in result.error_detail
    await plugin.close()
