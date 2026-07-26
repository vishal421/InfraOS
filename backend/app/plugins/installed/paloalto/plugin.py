from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from xml.etree import ElementTree as ET

from app.plugins.base import (
    AIContextAdapter,
    AuthenticationError,
    CommitError,
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
    UnsupportedVersionError,
    ValidationResult,
    VendorPlugin,
)
from app.plugins.installed.paloalto import mappers
from app.plugins.installed.paloalto.ai_adapter import PaloAltoAIContextAdapter
from app.plugins.installed.paloalto.client import PanOSAPIError, PanOSClient

logger = logging.getLogger("infraos.plugins.paloalto")

MIN_SUPPORTED_MAJOR_VERSION = 9

# xpath roots. Assumes vsys1 for single-vsys firewalls in Phase 1; multi-vsys
# support is a documented Phase 1.1 follow-up (xpath becomes vsys-parametrized,
# no contract change needed).
CONFIG_XPATH_ROOT = "/config/devices/entry/vsys/entry[@name='vsys1']"
FULL_CONFIG_XPATH = "/config"


class PaloAltoPlugin(VendorPlugin):
    vendor_name = "paloalto"
    supported_versions = ["9.x", "10.x", "11.x"]

    def __init__(self) -> None:
        self._clients: dict[str, PanOSClient] = {}

    # ------------------------------------------------------------
    # Client lifecycle — one pooled client per device_id, created lazily
    # ------------------------------------------------------------

    def _get_client(self, creds: DeviceCredentials) -> PanOSClient:
        client = self._clients.get(creds.device_id)
        if client is None:
            client = PanOSClient(
                host=creds.mgmt_host,
                port=creds.mgmt_port,
                api_key=creds.api_key,
                username=creds.username,
                password=creds.password,
                verify_tls=creds.ca_bundle_path or creds.verify_tls,
                timeout_seconds=creds.timeout_seconds,
            )
            self._clients[creds.device_id] = client
        return client

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    # ------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------

    async def test_connectivity(self, creds: DeviceCredentials) -> ConnectivityResult:
        client = self._get_client(creds)
        start = time.monotonic()
        try:
            await client.ensure_api_key()
            root = await client.op_command("<show><system><info/></system></show>")
            latency_ms = (time.monotonic() - start) * 1000
            sw_version = mappers.map_system_info(root).get("sw_version", "")
            if not self._is_supported_version(sw_version):
                return ConnectivityResult(
                    status=ConnectionStatus.UNSUPPORTED_VERSION,
                    reachable=True,
                    tls_valid=True,
                    authenticated=True,
                    latency_ms=latency_ms,
                    error_detail=f"PAN-OS {sw_version} is below minimum supported major version {MIN_SUPPORTED_MAJOR_VERSION}",
                )
            return ConnectivityResult(
                status=ConnectionStatus.ONLINE,
                reachable=True,
                tls_valid=True,
                authenticated=True,
                latency_ms=latency_ms,
            )
        except AuthenticationError as exc:
            return ConnectivityResult(
                status=ConnectionStatus.AUTH_FAILED,
                reachable=True,
                tls_valid=True,
                authenticated=False,
                error_detail=str(exc),
            )
        except ConnectivityError as exc:
            return ConnectivityResult(
                status=ConnectionStatus.UNREACHABLE,
                reachable=False,
                tls_valid=False,
                authenticated=False,
                error_detail=str(exc),
            )

    @staticmethod
    def _is_supported_version(sw_version: str) -> bool:
        try:
            major = int(sw_version.split(".")[0])
            return major >= MIN_SUPPORTED_MAJOR_VERSION
        except (ValueError, IndexError):
            return False

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    async def discover(self, creds: DeviceCredentials) -> DeviceDiscoveryResult:
        client = self._get_client(creds)
        try:
            system_root = await client.op_command("<show><system><info/></system></show>")
            system_info = mappers.map_system_info(system_root)

            if not self._is_supported_version(system_info.get("sw_version", "")):
                raise UnsupportedVersionError(
                    f"PAN-OS {system_info.get('sw_version')} is not supported "
                    f"(minimum major version {MIN_SUPPORTED_MAJOR_VERSION})"
                )

            ha_root = await client.op_command("<show><high-availability><state/></high-availability></show>")
            ha_state, ha_peer = mappers.map_ha_state(ha_root)

            license_root = await client.xml_request({"type": "op", "cmd": "<request><license><info/></license></request>"})
            licenses = mappers.map_licenses(license_root)

            return mappers.build_discovery_result(
                system_info=system_info,
                ha_state=ha_state,
                ha_peer=ha_peer,
                licenses=licenses,
            )
        except PanOSAPIError as exc:
            raise ConfigCollectionError(f"Discovery failed for {creds.device_id}: {exc}") from exc

    # ------------------------------------------------------------
    # Configuration collection
    # ------------------------------------------------------------

    async def collect_configuration(
        self, creds: DeviceCredentials, snapshot_type: ConfigSnapshotType = ConfigSnapshotType.RUNNING
    ) -> ConfigSnapshot:
        client = self._get_client(creds)
        action = "show" if snapshot_type == ConfigSnapshotType.CANDIDATE else "get"

        try:
            root = await client.config_get(xpath=FULL_CONFIG_XPATH, action=action)
        except PanOSAPIError as exc:
            raise ConfigCollectionError(
                f"Failed to collect {snapshot_type.value} configuration for {creds.device_id}: {exc}"
            ) from exc

        result_el = root.find(".//result")
        if result_el is None:
            raise ConfigCollectionError(f"Empty config result for {creds.device_id}")

        raw_xml = ET.tostring(result_el, encoding="unicode")

        interfaces = mappers.map_interfaces(result_el)
        zones = mappers.map_zones(result_el)
        objects = mappers.map_address_objects(result_el) + mappers.map_service_objects(result_el)
        policies = mappers.map_security_policies(result_el) + mappers.map_nat_policies(result_el)

        return ConfigSnapshot(
            device_id=creds.device_id,
            snapshot_type=snapshot_type,
            raw_xml=raw_xml,
            config_hash=mappers.config_hash(raw_xml),
            interfaces=interfaces,
            zones=zones,
            objects=objects,
            policies=policies,
        )

    # ------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------

    async def collect_metrics(self, creds: DeviceCredentials) -> list[Metric]:
        client = self._get_client(creds)
        metrics: list[Metric] = []
        now = datetime.now(timezone.utc)

        try:
            # Control plane (management plane): `show system resources` is
            # literally the mgmt-plane OS's own `top` output wrapped in XML.
            resource_root = await client.op_command("<show><system><resources/></system></show>")
            cpu, mem = self._parse_resources(resource_root)
            if cpu is not None:
                metrics.append(
                    Metric(
                        device_id=creds.device_id,
                        metric_name="cpu_utilization_pct",
                        value=cpu,
                        unit="pct",
                        recorded_at=now,
                        dimensions={"plane": "control"},
                    )
                )
            if mem is not None:
                metrics.append(
                    Metric(
                        device_id=creds.device_id,
                        metric_name="mem_utilization_pct",
                        value=mem,
                        unit="pct",
                        recorded_at=now,
                        dimensions={"plane": "control"},
                    )
                )

            session_root = await client.op_command("<show><session><info/></session></show>")
            active_sessions = self._findfloat(session_root, ".//result/num-active")
            if active_sessions is not None:
                metrics.append(
                    Metric(device_id=creds.device_id, metric_name="active_sessions", value=active_sessions, unit="count", recorded_at=now)
                )

            for iface_stat in self._parse_interface_counters(
                await client.op_command("<show><counter><interface>all</interface></counter></show>")
            ):
                metrics.append(
                    Metric(
                        device_id=creds.device_id,
                        metric_name="interface_drop_packets",
                        value=iface_stat["drops"],
                        unit="count",
                        recorded_at=now,
                        dimensions={"interface": iface_stat["name"]},
                    )
                )

            # Data plane: the dataplane runs its own separate OS/scheduler
            # from the management plane, so mgmt-plane `top` output above
            # says nothing about it. `show running resource-monitor` is the
            # dedicated dataplane counterpart — per-core CPU load averages
            # plus packet buffer occupancy (the dataplane's closest analogue
            # to a "memory used %", since it doesn't run a general-purpose
            # OS with a heap/page-cache the way the control plane does).
            dp_root = await client.op_command(
                "<show><running><resource-monitor><second><last>1</last></second></resource-monitor></running></show>"
            )
            dp_cpu, dp_buffer = self._parse_dataplane_resources(dp_root)
            if dp_cpu is not None:
                metrics.append(
                    Metric(
                        device_id=creds.device_id,
                        metric_name="cpu_utilization_pct",
                        value=dp_cpu,
                        unit="pct",
                        recorded_at=now,
                        dimensions={"plane": "data"},
                    )
                )
            if dp_buffer is not None:
                metrics.append(
                    Metric(
                        device_id=creds.device_id,
                        metric_name="mem_utilization_pct",
                        value=dp_buffer,
                        unit="pct",
                        recorded_at=now,
                        dimensions={"plane": "data"},
                    )
                )

        except PanOSAPIError as exc:
            logger.warning("Partial metrics collection failure for %s: %s", creds.device_id, exc)

        return metrics

    @staticmethod
    def _parse_resources(root: ET.Element) -> tuple[Optional[float], Optional[float]]:
        """PAN-OS returns a `top`-style text blob for system resources; parsed
        defensively since exact formatting varies by platform *and* by the
        procps/top version baked into that PAN-OS release. Notably, older
        top prints `KiB Mem :` while newer versions (procps-ng 3.3.10+)
        print `MiB Mem :` (and some print `GiB Mem :`) — previously only
        "kib mem" was matched, so memory silently came back empty on any
        device whose top uses MiB/GiB, even though the CPU line matched
        fine. Matching any `<unit>b mem` prefix fixes that."""
        result_el = root.find(".//result")
        text = "".join(result_el.itertext()) if result_el is not None else ""
        cpu = mem = None
        mem_prefix_re = re.compile(r"^[kmg]ib mem\s*:?")
        for raw_line in text.splitlines():
            line = raw_line.strip().lower()
            if "cpu(s)" in line and "id" in line:
                try:
                    idle_str = line.split("id")[0].strip().split(",")[-1].strip().split("%")[0].strip()
                    cpu = 100.0 - float(idle_str)
                except (ValueError, IndexError):
                    pass
            if line.startswith("mem:") or mem_prefix_re.match(line):
                try:
                    parts = mem_prefix_re.sub("", line).replace(":", "").split(",")
                    total = free = used = None
                    for part in parts:
                        part = part.strip()
                        if "total" in part:
                            total = float(part.split()[0])
                        elif "free" in part:
                            free = float(part.split()[0])
                        elif "used" in part:
                            used = float(part.split()[0])
                    if total and total > 0:
                        if free is not None:
                            mem = 100.0 * (total - free) / total
                        elif used is not None:
                            # Some top builds omit "free" from the summary
                            # line entirely and only report used/buff-cache —
                            # derive from used directly rather than giving up.
                            mem = 100.0 * used / total
                except (ValueError, IndexError):
                    pass
        return cpu, mem

    @staticmethod
    def _parse_dataplane_resources(root: ET.Element) -> tuple[Optional[float], Optional[float]]:
        """Parses `show running resource-monitor` (last 1 second sample).
        Real shape (per data-processor, e.g. dp0):
            result/resource-monitor/data-processors/dp0/second/
                cpu-load-average/entry/value   (comma-separated recent samples, most-recent-last)
                resource-utilization/entry[@name='public-pool-current' | 'public-pool-max']

        CPU is averaged across all cores' most recent sample; packet-buffer
        utilization is current/max from the public packet-buffer pool, which
        is the standard "is the dataplane running low on packet memory"
        indicator PAN-OS itself surfaces in `show running resource-monitor`.
        """
        core_values: list[float] = []
        for dp in root.findall(".//result/resource-monitor/data-processors/*"):
            for entry in dp.findall("second/cpu-load-average/entry"):
                value_el = entry.find("value")
                if value_el is None or not value_el.text:
                    continue
                samples = [s.strip() for s in value_el.text.split(",") if s.strip()]
                if samples:
                    try:
                        core_values.append(float(samples[-1]))
                    except ValueError:
                        pass

        dp_cpu = sum(core_values) / len(core_values) if core_values else None

        dp_buffer = None
        for dp in root.findall(".//result/resource-monitor/data-processors/*"):
            current = maximum = None
            for entry in dp.findall("second/resource-utilization/entry"):
                name_el = entry.find("name")
                value_el = entry.find("value")
                if name_el is None or value_el is None or not value_el.text:
                    continue
                name = (name_el.text or "").strip()
                try:
                    value = float(value_el.text.strip())
                except ValueError:
                    continue
                if name == "public-pool-current":
                    current = value
                elif name == "public-pool-max":
                    maximum = value
            if current is not None and maximum and maximum > 0:
                dp_buffer = 100.0 * current / maximum
                break  # single-dp platforms are the common case; first hit wins

        return dp_cpu, dp_buffer

    @staticmethod
    def _findfloat(root: ET.Element, path: str) -> Optional[float]:
        el = root.find(path)
        if el is None or not el.text:
            return None
        try:
            return float(el.text.strip())
        except ValueError:
            return None

    @staticmethod
    def _parse_interface_counters(root: ET.Element) -> list[dict]:
        stats = []
        for entry in root.findall(".//result/ifnet/entry"):
            name_el = entry.find("name")
            drop_el = entry.find("idrops")
            if name_el is not None and name_el.text:
                drops = 0.0
                if drop_el is not None and drop_el.text:
                    try:
                        drops = float(drop_el.text.strip())
                    except ValueError:
                        drops = 0.0
                stats.append({"name": name_el.text.strip(), "drops": drops})
        return stats

    # ------------------------------------------------------------
    # Live interface status (monitor + traffic)
    # ------------------------------------------------------------

    async def get_interface_status(self, creds: DeviceCredentials) -> list[InterfaceStatus]:
        client = self._get_client(creds)
        try:
            interface_root = await client.op_command("<show><interface>all</interface></show>")
            counter_root = await client.op_command("<show><counter><interface>all</interface></counter></show>")
        except PanOSAPIError as exc:
            raise ConfigCollectionError(f"Interface status collection failed for {creds.device_id}: {exc}") from exc

        return mappers.map_interface_status(interface_root, counter_root)

    # ------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------

    async def stream_logs(
        self, creds: DeviceCredentials, log_type: str, since: datetime
    ) -> AsyncIterator[LogEntry]:
        """
        Phase 1 implementation: job-based polling via the XML log API.
        `since` is applied as a query filter; PAN-OS log queries are async
        (submit query -> poll job -> fetch results), handled here so callers
        just get an async iterator of normalized LogEntry objects.

        Phase 2 note (tracked, not implemented here): real-time ingestion via
        syslog receiver replaces polling for high-volume tenants. This method
        signature does not need to change for that migration — a caller using
        stream_logs() today keeps working unmodified.
        """
        client = self._get_client(creds)
        since_str = since.strftime("%Y/%m/%d %H:%M:%S")
        query_filter = f"(receive_time geq '{since_str}')"

        try:
            submit_root = await client.log_query(log_type=log_type, query_filter=query_filter)
        except PanOSAPIError as exc:
            raise ConfigCollectionError(f"Log query submission failed for {creds.device_id}: {exc}") from exc

        job_id_el = submit_root.find(".//result/job")
        if job_id_el is None or not job_id_el.text:
            return
        job_id = job_id_el.text.strip()

        result_root = await self._poll_log_job(client, job_id)
        for entry in result_root.findall(".//result/log/logs/entry"):
            raw = {child.tag: (child.text or "").strip() for child in entry}
            logged_at_str = raw.get("receive_time") or raw.get("time_generated")
            try:
                logged_at = datetime.strptime(logged_at_str, "%Y/%m/%d %H:%M:%S") if logged_at_str else datetime.now(timezone.utc)
            except ValueError:
                logged_at = datetime.now(timezone.utc)
            yield LogEntry(device_id=creds.device_id, log_type=log_type, raw=raw, logged_at=logged_at)

    @staticmethod
    async def _poll_log_job(client: PanOSClient, job_id: str, max_attempts: int = 10, delay_seconds: float = 1.0) -> ET.Element:
        import asyncio

        for _ in range(max_attempts):
            root = await client.log_job_result(job_id)
            status = root.find(".//result/job/status")
            if status is not None and status.text and status.text.strip().upper() == "FIN":
                return root
            await asyncio.sleep(delay_seconds)
        # Return whatever the last poll had rather than raising — a partial
        # result is more useful to the caller than nothing, and the caller can
        # see fewer entries than expected and decide to re-poll.
        return root

    # ------------------------------------------------------------
    # Configuration change lifecycle
    # ------------------------------------------------------------

    async def validate_change(self, creds: DeviceCredentials, change: ConfigChange) -> ValidationResult:
        """
        Stages the change onto the CANDIDATE config (via set/edit) so PAN-OS's
        own <validate><full/></validate> can check it, WITHOUT committing.
        This means validate_change has a side effect on candidate config —
        callers must treat a failed validation as needing an explicit
        candidate-config discard (config_delete of the staged element) if they
        don't intend to proceed to push/commit. This is documented behavior,
        not an oversight: PAN-OS has no true no-side-effect dry run for
        arbitrary config elements.
        """
        client = self._get_client(creds)
        xpath = change.xpath or self._default_xpath_for(change)

        try:
            if change.action.value == "delete":
                await client.config_delete(xpath)
            else:
                if not change.element_xml:
                    return ValidationResult(valid=False, errors=["element_xml is required for create/update"])
                await client.config_set(xpath, change.element_xml)

            validate_root = await client.validate_candidate()
        except PanOSAPIError as exc:
            return ValidationResult(valid=False, errors=[str(exc)])

        errors = [
            "".join(e.itertext()).strip()
            for e in validate_root.findall(".//result/errors/entry")
        ]
        warnings = [
            "".join(w.itertext()).strip()
            for w in validate_root.findall(".//result/warnings/entry")
        ]
        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    async def push_configuration(self, creds: DeviceCredentials, change: ConfigChange) -> PushResult:
        """
        By this point the change should already be staged on candidate config
        by validate_change(). This method exists as a distinct contract step
        (per the platform's DRAFT -> VALIDATED -> PUSHED -> COMMITTED state
        machine) even though for PAN-OS the "push" and "validate" wire calls
        overlap — keeping them distinct here means the platform-level approval
        gate between validate and push is enforceable regardless of vendor,
        even for vendors where push is a genuinely separate wire operation.
        """
        client = self._get_client(creds)
        xpath = change.xpath or self._default_xpath_for(change)

        try:
            if change.action.value == "delete":
                await client.config_delete(xpath)
            else:
                if not change.element_xml:
                    return PushResult(success=False, change_id=change.change_id, error_detail="element_xml is required")
                await client.config_edit(xpath, change.element_xml)
            return PushResult(success=True, change_id=change.change_id)
        except PanOSAPIError as exc:
            raise ConfigPushError(f"Push failed for change {change.change_id} on {creds.device_id}: {exc}") from exc

    async def commit(self, creds: DeviceCredentials) -> CommitResult:
        client = self._get_client(creds)
        try:
            commit_root = await client.commit(description="InfraOS platform commit")
        except PanOSAPIError as exc:
            raise CommitError(f"Commit failed for {creds.device_id}: {exc}") from exc

        job_id_el = commit_root.find(".//result/job")
        if job_id_el is None or not job_id_el.text:
            msg_el = commit_root.find(".//result/msg")
            if msg_el is not None and "no changes" in "".join(msg_el.itertext()).lower():
                return CommitResult(success=True, job_id=None, warnings=["no changes to commit"])
            return CommitResult(success=False, error_detail="Commit did not return a job id")

        job_id = job_id_el.text.strip()
        final_status = await self._poll_commit_job(client, job_id)
        return final_status

    @staticmethod
    async def _poll_commit_job(client: PanOSClient, job_id: str, max_attempts: int = 60, delay_seconds: float = 2.0) -> CommitResult:
        import asyncio

        for _ in range(max_attempts):
            root = await client.job_status(job_id)
            status_el = root.find(".//result/job/status")
            result_el = root.find(".//result/job/result")
            if status_el is not None and status_el.text and status_el.text.strip().upper() == "FIN":
                success = result_el is not None and result_el.text and result_el.text.strip().upper() == "OK"
                warnings = [
                    "".join(w.itertext()).strip()
                    for w in root.findall(".//result/job/details/line")
                ]
                return CommitResult(success=bool(success), job_id=job_id, warnings=warnings)
            await asyncio.sleep(delay_seconds)

        return CommitResult(success=False, job_id=job_id, error_detail="Commit job did not finish within polling window")

    async def rollback(self, creds: DeviceCredentials, to_version: str) -> RollbackResult:
        """
        PAN-OS rollback = load a saved config version into candidate, then
        commit. The platform layer decides *when* to call this (e.g. after a
        failed post-commit verification per the architecture's automatic
        rollback rule) — this method just executes it.
        """
        client = self._get_client(creds)
        try:
            await client.load_config_version(to_version)
            commit_result = await self.commit(creds)
        except (PanOSAPIError, CommitError) as exc:
            return RollbackResult(success=False, restored_version=to_version, error_detail=str(exc))

        if not commit_result.success:
            return RollbackResult(
                success=False, restored_version=to_version, error_detail=commit_result.error_detail or "rollback commit failed"
            )
        return RollbackResult(success=True, restored_version=to_version)

    @staticmethod
    def _default_xpath_for(change: ConfigChange) -> str:
        type_to_container = {
            "address_object": "address",
            "address_group": "address-group",
            "service_object": "service",
            "service_group": "service-group",
            "security_policy": "rulebase/security/rules",
            "nat_policy": "rulebase/nat/rules",
        }
        container = type_to_container.get(change.target_type, change.target_type)
        return f"{CONFIG_XPATH_ROOT}/{container}/entry[@name='{change.target_name}']"

    # ------------------------------------------------------------
    # AI context adapter
    # ------------------------------------------------------------

    def get_ai_context_adapter(self) -> AIContextAdapter:
        return PaloAltoAIContextAdapter()
