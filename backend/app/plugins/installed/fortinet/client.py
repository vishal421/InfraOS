"""
Low-level FortiOS REST API client (api/v2/cmdb and api/v2/monitor).

Mirrors the separation used in the Palo Alto plugin: this file is the only
place that knows FortiOS's actual wire format (JSON REST, not XML). Auth is
via API token (Authorization: Bearer <token>), which is FortiOS's standard
programmatic auth method — no keygen step like PAN-OS.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.plugins.base import AuthenticationError, ConnectivityError


class FortiOSAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"FortiOS API error [{status_code}]: {message}")


class FortiOSClient:
    def __init__(
        self,
        host: str,
        port: int = 443,
        api_token: Optional[str] = None,
        verify_tls: bool | str = True,
        timeout_seconds: float = 30.0,
    ):
        if not api_token:
            raise ValueError("FortiOS plugin requires an API token (username/password login is not implemented)")

        self._host = host
        self._port = port
        self._token = api_token
        self._client = httpx.AsyncClient(
            base_url=f"https://{host}:{port}",
            verify=verify_tls,
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_token}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json_body=json_body)

    async def put(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", path, json_body=json_body)

    async def delete(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", path)

    async def _request(
        self, method: str, path: str, params: dict[str, str] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            resp = await self._client.request(method, path, params=params, json=json_body)
        except httpx.ConnectError as exc:
            raise ConnectivityError(f"Could not connect to {self._host}:{self._port}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ConnectivityError(f"Timed out on request to {self._host}:{self._port}: {exc}") from exc

        if resp.status_code == 401:
            raise AuthenticationError("FortiOS rejected the API token (HTTP 401)")
        if resp.status_code >= 500:
            raise ConnectivityError(f"FortiOS returned server error HTTP {resp.status_code}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise FortiOSAPIError(resp.status_code, f"Non-JSON response: {exc}") from exc

        if resp.status_code >= 400:
            raise FortiOSAPIError(resp.status_code, body.get("cli_error") or body.get("http_status", "unknown error"))

        return body
