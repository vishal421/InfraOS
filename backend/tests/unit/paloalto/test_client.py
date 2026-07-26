from __future__ import annotations

import pytest
import respx
import httpx

from app.plugins.base import AuthenticationError, ConnectivityError
from app.plugins.installed.paloalto.client import PanOSAPIError, PanOSClient

BASE = "https://fw-test:443"


@pytest.mark.asyncio
@respx.mock
async def test_ensure_api_key_generates_key_when_not_provided():
    respx.get(f"{BASE}/api/").mock(
        return_value=httpx.Response(
            200,
            text='<response status="success"><result><key>abc123</key></result></response>',
        )
    )
    client = PanOSClient(host="fw-test", username="admin", password="secret")
    key = await client.ensure_api_key()
    assert key == "abc123"
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_ensure_api_key_raises_authentication_error_on_bad_creds():
    respx.get(f"{BASE}/api/").mock(
        return_value=httpx.Response(
            200,
            text='<response status="error" code="403"><msg>Invalid credential</msg></response>',
        )
    )
    client = PanOSClient(host="fw-test", username="admin", password="wrong")
    with pytest.raises(AuthenticationError):
        await client.ensure_api_key()
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_op_command_raises_connectivity_error_on_connect_failure():
    respx.get(f"{BASE}/api/").mock(side_effect=httpx.ConnectError("refused"))
    client = PanOSClient(host="fw-test", api_key="preset-key")
    with pytest.raises(ConnectivityError):
        await client.op_command("<show><system><info/></system></show>")
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_xml_request_raises_panos_api_error_on_generic_error():
    respx.get(f"{BASE}/api/").mock(
        return_value=httpx.Response(
            200,
            text='<response status="error" code="20"><msg>Command not found</msg></response>',
        )
    )
    client = PanOSClient(host="fw-test", api_key="preset-key")
    with pytest.raises(PanOSAPIError):
        await client.op_command("<bogus/>")
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_commit_builds_correct_request():
    route = respx.get(f"{BASE}/api/").mock(
        return_value=httpx.Response(
            200,
            text='<response status="success"><result><msg><line>Commit job enqueued with jobid 42</line></msg><job>42</job></result></response>',
        )
    )
    client = PanOSClient(host="fw-test", api_key="preset-key")
    root = await client.commit(description="test commit")
    assert route.called
    request = route.calls.last.request
    assert "type=commit" in str(request.url)
    job_el = root.find(".//result/job")
    assert job_el.text == "42"
    await client.close()
