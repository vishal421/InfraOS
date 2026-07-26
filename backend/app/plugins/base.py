"""
Vendor Plugin Contract.

This module defines the ONLY interface the core platform is allowed to depend
on. No domain service, API router, or AI component may import anything from
plugins/installed/* directly — everything goes through PluginRegistry.get_plugin()
and these types.

Adding a new vendor means implementing VendorPlugin fully. CI enforces this via
tests/contract/test_plugin_contract.py, which runs against every registered
plugin and fails the build if any method is missing or violates the contract
(e.g. raising instead of returning a typed error).
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Shared enums
# --------------------------------------------------------------------------

class ConnectionStatus(str, enum.Enum):
    ONLINE = "online"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"
    TLS_ERROR = "tls_error"
    UNSUPPORTED_VERSION = "unsupported_version"


class HAState(str, enum.Enum):
    ACTIVE = "active"
    PASSIVE = "passive"
    STANDALONE = "standalone"
    UNKNOWN = "unknown"


class ConfigSnapshotType(str, enum.Enum):
    RUNNING = "running"
    CANDIDATE = "candidate"


class ObjectType(str, enum.Enum):
    ADDRESS = "address"
    ADDRESS_GROUP = "address_group"
    SERVICE = "service"
    SERVICE_GROUP = "service_group"
    APPLICATION_GROUP = "application_group"


class PolicyType(str, enum.Enum):
    SECURITY = "security"
    NAT = "nat"


class ChangeAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ChangeStatus(str, enum.Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    VALIDATION_FAILED = "validation_failed"
    PUSHED = "pushed"
    PUSH_FAILED = "push_failed"
    COMMITTED = "committed"
    COMMIT_FAILED = "commit_failed"
    ROLLED_BACK = "rolled_back"


# --------------------------------------------------------------------------
# Credentials / connection
# --------------------------------------------------------------------------

class DeviceCredentials(BaseModel):
    """
    Never carries a raw secret in memory longer than needed and is never
    logged or serialized as part of an audit event. `api_key` here is
    resolved by the caller from the secrets backend (Vault et al) immediately
    before use — the plugin layer has no knowledge of where it came from.
    """
    device_id: str
    mgmt_host: str
    mgmt_port: int = 443
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_tls: bool = True
    ca_bundle_path: Optional[str] = None
    timeout_seconds: float = 30.0

    def __repr__(self) -> str:  # never leak secrets into logs/tracebacks
        return f"DeviceCredentials(device_id={self.device_id!r}, mgmt_host={self.mgmt_host!r})"

    __str__ = __repr__


class ConnectivityResult(BaseModel):
    status: ConnectionStatus
    reachable: bool
    tls_valid: bool
    authenticated: bool
    latency_ms: Optional[float] = None
    error_detail: Optional[str] = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

class LicenseInfo(BaseModel):
    feature: str
    description: Optional[str] = None
    expires: Optional[str] = None
    expired: bool = False


class DeviceDiscoveryResult(BaseModel):
    hostname: str
    model: str
    serial: str
    os_version: str
    ha_state: HAState
    ha_peer_serial: Optional[str] = None
    panorama_managed: bool = False
    panorama_hostname: Optional[str] = None
    device_group: Optional[str] = None
    uptime_seconds: Optional[int] = None
    licenses: list[LicenseInfo] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

class NormalizedInterface(BaseModel):
    name: str
    zone: Optional[str] = None
    virtual_router: Optional[str] = None
    ip_addresses: list[str] = Field(default_factory=list)
    mode: Optional[str] = None  # layer3, layer2, tap, vwire
    enabled: bool = True


class NormalizedZone(BaseModel):
    name: str
    interfaces: list[str] = Field(default_factory=list)


class NormalizedObject(BaseModel):
    name: str
    object_type: ObjectType
    definition: dict[str, Any]
    in_use: Optional[bool] = None


class NormalizedPolicy(BaseModel):
    name: str
    policy_type: PolicyType
    rule_order: int
    source_zones: list[str] = Field(default_factory=list)
    destination_zones: list[str] = Field(default_factory=list)
    source: list[str] = Field(default_factory=list)
    destination: list[str] = Field(default_factory=list)
    application: list[str] = Field(default_factory=list)
    service: list[str] = Field(default_factory=list)
    action: Optional[str] = None
    definition: dict[str, Any]
    hit_count: Optional[int] = None
    last_hit_at: Optional[datetime] = None


class ConfigSnapshot(BaseModel):
    device_id: str
    snapshot_type: ConfigSnapshotType
    raw_xml: str
    config_hash: str
    interfaces: list[NormalizedInterface] = Field(default_factory=list)
    zones: list[NormalizedZone] = Field(default_factory=list)
    objects: list[NormalizedObject] = Field(default_factory=list)
    policies: list[NormalizedPolicy] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConfigChange(BaseModel):
    """
    Vendor-agnostic description of a desired change. The plugin translates
    this into vendor-native API calls. This object is what flows through the
    DRAFT -> VALIDATED -> ... state machine described in the architecture doc
    — the plugin never sees platform approval state, only the change itself
    once it has been approved and is ready to validate/push.
    """
    change_id: str
    action: ChangeAction
    target_type: str  # e.g. "security_policy", "address_object", "nat_policy"
    target_name: str
    xpath: Optional[str] = None
    element_xml: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PushResult(BaseModel):
    success: bool
    change_id: str
    vendor_job_id: Optional[str] = None
    error_detail: Optional[str] = None


class CommitResult(BaseModel):
    success: bool
    job_id: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    error_detail: Optional[str] = None


class RollbackResult(BaseModel):
    success: bool
    restored_version: str
    error_detail: Optional[str] = None


# --------------------------------------------------------------------------
# Monitoring / logs
# --------------------------------------------------------------------------

class Metric(BaseModel):
    device_id: str
    metric_name: str
    value: float
    unit: Optional[str] = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dimensions: dict[str, str] = Field(default_factory=dict)  # e.g. {"interface": "ethernet1/1"}


class LogEntry(BaseModel):
    device_id: str
    log_type: str  # traffic, threat, system, config, tunnel, hip, userid, auth
    raw: dict[str, Any]
    logged_at: datetime


class InterfaceStatus(BaseModel):
    """Live, per-interface snapshot used for interface monitoring: link
    state and configured IPs come straight from the device (not from a
    stored config snapshot, which may be stale), alongside cumulative
    traffic counters the caller can use to derive throughput between two
    polls."""

    name: str
    zone: Optional[str] = None
    admin_up: bool = True
    oper_up: bool = True
    ip_addresses: list[str] = Field(default_factory=list)
    speed_mbps: Optional[float] = None
    duplex: Optional[str] = None
    mtu: Optional[int] = None
    in_bytes: Optional[int] = None
    out_bytes: Optional[int] = None
    in_packets: Optional[int] = None
    out_packets: Optional[int] = None
    in_errors: Optional[int] = None
    out_errors: Optional[int] = None
    in_drops: Optional[int] = None
    out_drops: Optional[int] = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# AI context adapter
# --------------------------------------------------------------------------

class AIContextAdapter(ABC):
    """
    Translates vendor-native normalized objects into the flat fact/text
    representation the RAG retriever and Knowledge Graph loader consume.
    Keeping this as a separate small interface (rather than baking it into
    the main plugin methods) means the AI layer's expectations can evolve
    without touching config-collection code paths.
    """

    @abstractmethod
    def policy_to_graph_edges(self, policy: NormalizedPolicy) -> list[dict[str, Any]]: ...

    @abstractmethod
    def object_to_text_chunk(self, obj: NormalizedObject) -> str: ...

    @abstractmethod
    def snapshot_to_summary(self, snapshot: ConfigSnapshot) -> str: ...


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class PluginError(Exception):
    """Base class for all plugin-raised errors. Never let vendor-specific
    exceptions (e.g. httpx errors, XML parse errors) leak past the plugin
    boundary — wrap them in one of these so domain services can handle
    failures uniformly regardless of vendor."""


class ConnectivityError(PluginError):
    pass


class AuthenticationError(PluginError):
    pass


class UnsupportedVersionError(PluginError):
    pass


class ConfigCollectionError(PluginError):
    pass


class ConfigPushError(PluginError):
    pass


class CommitError(PluginError):
    pass


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------

class VendorPlugin(ABC):
    vendor_name: str
    supported_versions: list[str]

    @abstractmethod
    async def test_connectivity(self, creds: DeviceCredentials) -> ConnectivityResult: ...

    @abstractmethod
    async def discover(self, creds: DeviceCredentials) -> DeviceDiscoveryResult: ...

    @abstractmethod
    async def collect_configuration(
        self, creds: DeviceCredentials, snapshot_type: ConfigSnapshotType = ConfigSnapshotType.RUNNING
    ) -> ConfigSnapshot: ...

    @abstractmethod
    async def collect_metrics(self, creds: DeviceCredentials) -> list[Metric]: ...

    @abstractmethod
    async def get_interface_status(self, creds: DeviceCredentials) -> list[InterfaceStatus]:
        """Live per-interface snapshot: admin/oper state, configured IPs, and
        cumulative traffic counters, read directly from the device (not from
        a previously-collected config snapshot). Powers interface monitoring
        and live-traffic views."""
        ...

    @abstractmethod
    def stream_logs(
        self, creds: DeviceCredentials, log_type: str, since: datetime
    ) -> AsyncIterator[LogEntry]: ...

    @abstractmethod
    async def validate_change(self, creds: DeviceCredentials, change: ConfigChange) -> ValidationResult: ...

    @abstractmethod
    async def push_configuration(self, creds: DeviceCredentials, change: ConfigChange) -> PushResult: ...

    @abstractmethod
    async def commit(self, creds: DeviceCredentials) -> CommitResult: ...

    @abstractmethod
    async def rollback(self, creds: DeviceCredentials, to_version: str) -> RollbackResult: ...

    @abstractmethod
    def get_ai_context_adapter(self) -> AIContextAdapter: ...

    @abstractmethod
    async def close(self) -> None:
        """Release any pooled HTTP connections / resources."""
