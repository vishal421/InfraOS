"""
Low-level PAN-OS API client.

This is the only module in the plugin allowed to know about PAN-OS's actual
wire format (XML API + REST). Everything above it (plugin.py) works with
normalized models from plugins/base.py. Keeping this separation means if
PAN-OS changes its API shape between versions, the blast radius is this file
and mappers.py — not the plugin's public contract.
"""

from __future__ import annotations

from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx

from app.plugins.base import (
    AuthenticationError,
    ConnectivityError,
)

DEFAULT_API_VERSION = "v10.1"


class PanOSAPIError(Exception):
    """Raised for any non-success response from the PAN-OS XML/REST API,
    carrying the vendor's own error code/message for logging and debugging."""

    def __init__(self, code: Optional[str], message: str):
        self.code = code
        self.message = message
        super().__init__(f"PAN-OS API error [{code}]: {message}")


class PanOSClient:
    """
    Thin async wrapper around the PAN-OS XML API (`/api/`) and REST API
    (`/restapi/{version}/...`). One instance per device connection; callers
    (plugin.py) are responsible for instantiating per-request or holding a
    short-lived pool — this client does not cache credentials beyond its
    own lifetime and never persists them.
    """

    def __init__(
        self,
        host: str,
        port: int = 443,
        api_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_tls: bool | str = True,
        timeout_seconds: float = 30.0,
        api_version: str = DEFAULT_API_VERSION,
    ):
        if not api_key and not (username and password):
            raise ValueError("Either api_key or username+password must be provided")

        self._host = host
        self._port = port
        self._api_key = api_key
        self._username = username
        self._password = password
        self._api_version = api_version
        self._base_url = f"https://{host}:{port}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=verify_tls,
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PanOSClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ----------------------------------------------------------------
    # Auth
    # ----------------------------------------------------------------

    async def ensure_api_key(self) -> str:
        """Returns a usable API key, generating one from username/password
        via the keygen endpoint if one wasn't provided directly."""
        if self._api_key:
            return self._api_key

        try:
            resp = await self._client.get(
                "/api/",
                params={"type": "keygen", "user": self._username, "password": self._password},
            )
        except httpx.ConnectError as exc:
            raise ConnectivityError(f"Could not connect to {self._host}:{self._port}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ConnectivityError(f"Timed out connecting to {self._host}:{self._port}: {exc}") from exc

        root = self._parse_xml_response(resp)
        key_el = root.find(".//key")
        if key_el is None or not key_el.text:
            raise AuthenticationError(f"Keygen failed for user {self._username!r} on {self._host}")

        self._api_key = key_el.text
        return self._api_key

    # ----------------------------------------------------------------
    # XML API primitives
    # ----------------------------------------------------------------

    async def xml_request(self, params: dict[str, str]) -> ET.Element:
        """Issue a request against the legacy XML API (`/api/`), which is
        still required for config get/set/edit/commit operations that the
        REST API does not fully cover across all PAN-OS versions."""
        api_key = await self.ensure_api_key()
        request_params = {**params, "key": api_key}

        try:
            resp = await self._client.get("/api/", params=request_params)
        except httpx.ConnectError as exc:
            raise ConnectivityError(f"Could not connect to {self._host}:{self._port}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ConnectivityError(f"Timed out on request to {self._host}:{self._port}: {exc}") from exc

        return self._parse_xml_response(resp)

    async def op_command(self, cmd_xml: str) -> ET.Element:
        """Run an operational command, e.g. <show><system><info/></system></show>"""
        return await self.xml_request({"type": "op", "cmd": cmd_xml})

    async def config_get(self, xpath: str, action: str = "get") -> ET.Element:
        return await self.xml_request({"type": "config", "action": action, "xpath": xpath})

    async def config_set(self, xpath: str, element_xml: str) -> ET.Element:
        return await self.xml_request(
            {"type": "config", "action": "set", "xpath": xpath, "element": element_xml}
        )

    async def config_edit(self, xpath: str, element_xml: str) -> ET.Element:
        return await self.xml_request(
            {"type": "config", "action": "edit", "xpath": xpath, "element": element_xml}
        )

    async def config_delete(self, xpath: str) -> ET.Element:
        return await self.xml_request({"type": "config", "action": "delete", "xpath": xpath})

    async def validate_candidate(self) -> ET.Element:
        return await self.xml_request({"type": "op", "cmd": "<validate><full/></validate>"})

    async def commit(self, description: str = "") -> ET.Element:
        cmd = "<commit>"
        if description:
            cmd += f"<description>{_xml_escape(description)}</description>"
        cmd += "</commit>"
        return await self.xml_request({"type": "commit", "cmd": cmd})

    async def job_status(self, job_id: str) -> ET.Element:
        return await self.xml_request({"type": "op", "cmd": f"<show><jobs><id>{job_id}</id></jobs></show>"})

    async def load_config_version(self, version_name: str) -> ET.Element:
        cmd = f"<load><config><version>{_xml_escape(version_name)}</version></config></load>"
        return await self.xml_request({"type": "op", "cmd": cmd})

    async def log_query(self, log_type: str, query_filter: str, nlogs: int = 500) -> ET.Element:
        """Submits an async log retrieval job (PAN-OS logs are pulled via a
        job-based query, not returned synchronously)."""
        return await self.xml_request(
            {
                "type": "log",
                "log-type": log_type,
                "query": query_filter,
                "nlogs": str(nlogs),
            }
        )

    async def log_job_result(self, job_id: str) -> ET.Element:
        return await self.xml_request({"type": "log", "action": "get", "job-id": job_id})

    # ----------------------------------------------------------------
    # Response handling
    # ----------------------------------------------------------------

    @staticmethod
    def _parse_xml_response(resp: httpx.Response) -> ET.Element:
        if resp.status_code == 403:
            raise AuthenticationError("PAN-OS rejected credentials (HTTP 403)")
        if resp.status_code >= 500:
            raise ConnectivityError(f"PAN-OS returned server error HTTP {resp.status_code}")

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            raise PanOSAPIError(None, f"Could not parse XML response: {exc}") from exc

        status = root.attrib.get("status")
        if status == "error":
            code = root.attrib.get("code")
            msg_el = root.find(".//msg")
            message = "".join(msg_el.itertext()).strip() if msg_el is not None else "unknown error"
            if code == "403" or "Invalid credential" in message:
                raise AuthenticationError(message)
            raise PanOSAPIError(code, message)

        return root


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
