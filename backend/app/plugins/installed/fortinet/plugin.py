"""
FortiGate plugin.

This is the architecture's second vendor, built specifically to stress-test
the VendorPlugin contract designed around Palo Alto's two-phase
candidate/commit config model. FortiOS does NOT work that way — CMDB API
calls (POST/PUT/DELETE) apply directly to the running configuration, with
no separate "commit" step. Rather than force a fake staging concept onto
FortiOS, this plugin is honest about the difference:

  - validate_change(): FortiOS has no generic dry-run for arbitrary CMDB
    objects, so this performs structural validation only (required fields
    present for the target type) and returns a warning that push will apply
    immediately — there is no staging to inspect before commit.
  - push_configuration(): actually performs the create/update/delete against
    the FortiOS CMDB API. This is the point at which the change takes effect
    on the device, unlike Palo Alto where push only stages candidate config.
  - commit(): a no-op that reports success, since there is nothing left to
    commit — push already applied the change. The platform's approval gate
    (validate -> approve -> push -> commit) still holds: a human still has to
    approve before push happens, which is what actually matters. Commit
    being trivial for this vendor doesn't weaken that gate.
  - rollback(): NOT implemented in this pass. FortiOS has its own config
    revision/backup mechanism that's a materially different shape than
    Palo Alto's load-named-version approach, and guessing at its exact API
    surface here risks shipping incorrect vendor-specific detail. This
    method returns a clear failure explaining the gap rather than pretending
    to support something unverified.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from app.plugins.base import (
    AIContextAdapter,
    AuthenticationError,
    ChangeAction,
    CommitResult,
    ConfigChange,
    ConfigCollectionError,
    ConfigPushError,
    ConfigSnapshot,
    ConfigSnapshotType,
    ConnectionStatus,
    ConnectivityError,
    ConnectivityResult,
    DeviceCredentials,
    DeviceDiscoveryResult,
    InterfaceStatus,
    LogEntry,
    Metric,
    PushResult,
    RollbackResult,
    ValidationResult,
    VendorPlugin,
)
from app.plugins.installed.fortinet import mappers
from app.plugins.installed.fortinet.ai_adapter import FortinetAIContextAdapter
from app.plugins.installed.fortinet.client import FortiOSAPIError, FortiOSClient

logger = logging.getLogger("infraos.plugins.fortinet")

TARGET_TYPE_ENDPOINTS = {
    "address_object": "/api/v2/cmdb/firewall/address",
    "service_object": "/api/v2/cmdb/firewall/service/custom",
    "security_policy": "/api/v2/cmdb/firewall/policy",
}

REQUIRED_FIELDS = {
    "address_object": {"subnet"},
    "service_object": {"protocol"},
    "security_policy": {"srcintf", "dstintf", "action"},
}


class FortinetPlugin(VendorPlugin):
    vendor_name = "fortinet"
    supported_versions = ["6.4", "7.0", "7.2", "7.4"]

    def __init__(self) -> None:
        self._clients: dict[str, FortiOSClient] = {}

    def _get_client(self, creds: DeviceCredentials) -> FortiOSClient:
        client = self._clients.get(creds.device_id)
        if client is None:
            # FortiOS auth is API-token based; this plugin reads the token
            # from the same api_key field the platform already threads
            # through DeviceCredentials for other vendors, rather than
            # inventing a Fortinet-specific credential shape.
            client = FortiOSClient(
                host=creds.mgmt_host,
                port=creds.mgmt_port,
                api_token=creds.api_key,
                verify_tls=creds.ca_bundle_path or creds.verify_tls,
                timeout_seconds=creds.timeout_seconds,
            )
            self._clients[creds.device_id] = client
        return client

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    async def test_connectivity(self, creds: DeviceCredentials) -> ConnectivityResult:
        client = self._get_client(creds)
        start = time.monotonic()
        try:
            await client.get("/api/v2/monitor/system/status")
            return ConnectivityResult(
                status=ConnectionStatus.ONLINE,
                reachable=True,
                tls_valid=True,
                authenticated=True,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except AuthenticationError as exc:
            return ConnectivityResult(status=ConnectionStatus.AUTH_FAILED, reachable=True, tls_valid=True, authenticated=False, error_detail=str(exc))
        except ConnectivityError as exc:
            return ConnectivityResult(status=ConnectionStatus.UNREACHABLE, reachable=False, tls_valid=False, authenticated=False, error_detail=str(exc))

    async def discover(self, creds: DeviceCredentials) -> DeviceDiscoveryResult:
        client = self._get_client(creds)
        try:
            status_body = await client.get("/api/v2/monitor/system/status")
            ha_body = await client.get("/api/v2/monitor/system/ha-status")
        except FortiOSAPIError as exc:
            raise ConfigCollectionError(f"Discovery failed for {creds.device_id}: {exc}") from exc
        return mappers.map_discovery(status_body, ha_body)

    async def get_interface_status(self, creds: DeviceCredentials) -> list[InterfaceStatus]:
        client = self._get_client(creds)
        try:
            monitor_body = await client.get("/api/v2/monitor/system/interface")
        except FortiOSAPIError as exc:
            raise ConfigCollectionError(f"Interface status collection failed for {creds.device_id}: {exc}") from exc
        return mappers.map_interface_status(monitor_body)

    async def collect_configuration(
        self, creds: DeviceCredentials, snapshot_type: ConfigSnapshotType = ConfigSnapshotType.RUNNING
    ) -> ConfigSnapshot:
        if snapshot_type == ConfigSnapshotType.CANDIDATE:
            # FortiOS has no candidate config concept — there is only
            # running config. Surface that plainly rather than silently
            # returning the running config under a misleading label.
            raise ConfigCollectionError(
                "FortiOS has no candidate configuration concept — only running config is available for this vendor"
            )

        client = self._get_client(creds)
        try:
            interfaces_body = await client.get("/api/v2/cmdb/system/interface")
            zones_body = await client.get("/api/v2/cmdb/system/zone")
            address_body = await client.get("/api/v2/cmdb/firewall/address")
            service_body = await client.get("/api/v2/cmdb/firewall/service/custom")
            policy_body = await client.get("/api/v2/cmdb/firewall/policy")
        except FortiOSAPIError as exc:
            raise ConfigCollectionError(f"Config collection failed for {creds.device_id}: {exc}") from exc

        raw = {
            "interfaces": interfaces_body,
            "zones": zones_body,
            "addresses": address_body,
            "services": service_body,
            "policies": policy_body,
        }

        return ConfigSnapshot(
            device_id=creds.device_id,
            snapshot_type=snapshot_type,
            raw_xml="",  # FortiOS is JSON-native; raw_xml intentionally left empty for this vendor
            config_hash=mappers.config_hash(raw),
            interfaces=mappers.map_interfaces(interfaces_body),
            zones=mappers.map_zones(zones_body),
            objects=mappers.map_address_objects(address_body) + mappers.map_service_objects(service_body),
            policies=mappers.map_policies(policy_body),
        )

    async def collect_metrics(self, creds: DeviceCredentials) -> list[Metric]:
        client = self._get_client(creds)
        metrics: list[Metric] = []
        now = datetime.utcnow()
        try:
            usage = await client.get("/api/v2/monitor/system/resource/usage", params={"scope": "vdom"})
            results = usage.get("results", {})
            cpu = results.get("cpu", [{}])[-1].get("current") if results.get("cpu") else None
            mem = results.get("mem", [{}])[-1].get("current") if results.get("mem") else None
            if cpu is not None:
                metrics.append(Metric(device_id=creds.device_id, metric_name="cpu_utilization_pct", value=float(cpu), unit="pct", recorded_at=now))
            if mem is not None:
                metrics.append(Metric(device_id=creds.device_id, metric_name="mem_utilization_pct", value=float(mem), unit="pct", recorded_at=now))

            session_body = await client.get("/api/v2/monitor/system/session")
            session_count = len(session_body.get("results", []))
            metrics.append(Metric(device_id=creds.device_id, metric_name="active_sessions", value=float(session_count), unit="count", recorded_at=now))
        except FortiOSAPIError as exc:
            logger.warning("Partial metrics collection failure for %s: %s", creds.device_id, exc)
        return metrics

    async def stream_logs(self, creds: DeviceCredentials, log_type: str, since: datetime) -> AsyncIterator[LogEntry]:
        client = self._get_client(creds)
        fortios_log_type = {"traffic": "traffic", "threat": "utm", "system": "event"}.get(log_type, log_type)
        try:
            body = await client.get(f"/api/v2/log/disk/{fortios_log_type}/forward")
        except FortiOSAPIError as exc:
            raise ConfigCollectionError(f"Log query failed for {creds.device_id}: {exc}") from exc

        for entry in body.get("results", []):
            logged_at_str = entry.get("date", "") + " " + entry.get("time", "")
            try:
                logged_at = datetime.strptime(logged_at_str.strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                logged_at = datetime.utcnow()
            yield LogEntry(device_id=creds.device_id, log_type=log_type, raw=entry, logged_at=logged_at)

    async def validate_change(self, creds: DeviceCredentials, change: ConfigChange) -> ValidationResult:
        required = REQUIRED_FIELDS.get(change.target_type, set())
        missing = required - set(change.payload.keys())
        warnings = [
            "FortiOS applies configuration changes immediately on push — there is no candidate-config "
            "staging step to review before commit, unlike the Palo Alto plugin."
        ]
        if missing:
            return ValidationResult(valid=False, errors=[f"Missing required field(s) for {change.target_type}: {sorted(missing)}"])
        return ValidationResult(valid=True, warnings=warnings)

    async def push_configuration(self, creds: DeviceCredentials, change: ConfigChange) -> PushResult:
        endpoint = TARGET_TYPE_ENDPOINTS.get(change.target_type)
        if endpoint is None:
            return PushResult(success=False, change_id=change.change_id, error_detail=f"Unsupported target_type '{change.target_type}' for Fortinet plugin")

        client = self._get_client(creds)
        try:
            if change.action == ChangeAction.CREATE:
                await client.post(endpoint, {"name": change.target_name, **change.payload})
            elif change.action == ChangeAction.UPDATE:
                await client.put(f"{endpoint}/{change.target_name}", change.payload)
            elif change.action == ChangeAction.DELETE:
                await client.delete(f"{endpoint}/{change.target_name}")
            return PushResult(success=True, change_id=change.change_id)
        except FortiOSAPIError as exc:
            raise ConfigPushError(f"Push failed for change {change.change_id} on {creds.device_id}: {exc}") from exc

    async def commit(self, creds: DeviceCredentials) -> CommitResult:
        # No-op by design — see module docstring. push_configuration() already
        # applied the change directly to FortiOS's running config.
        return CommitResult(success=True, job_id=None, warnings=["FortiOS has no separate commit step — the change was already applied by push."])

    async def rollback(self, creds: DeviceCredentials, to_version: str) -> RollbackResult:
        return RollbackResult(
            success=False,
            restored_version=to_version,
            error_detail=(
                "Rollback is not implemented for the Fortinet plugin in this pass. FortiOS's config "
                "revision/backup system is a different shape than Palo Alto's named-version load, and "
                "needs its own design rather than a guessed API mapping."
            ),
        )

    def get_ai_context_adapter(self) -> AIContextAdapter:
        return FortinetAIContextAdapter()
