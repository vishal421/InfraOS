from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DeviceCreateRequest(BaseModel):
    mgmt_host: str
    mgmt_port: int = 443
    username: str
    password: str
    verify_tls: bool = True


class DeviceUpdateRequest(BaseModel):
    mgmt_host: Optional[str] = None
    mgmt_port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None  # if provided, replaces stored credential
    verify_tls: Optional[bool] = None


class DeviceResponse(BaseModel):
    id: str
    vendor: str
    hostname: Optional[str]
    mgmt_host: str
    mgmt_port: int
    username: Optional[str]
    verify_tls: bool
    model: Optional[str]
    serial: Optional[str]
    os_version: Optional[str]
    ha_state: Optional[str]
    ha_peer_serial: Optional[str]
    uptime_seconds: Optional[int]
    licenses: list[dict]
    connection_status: str
    last_connectivity_check_at: Optional[datetime]
    last_discovered_at: Optional[datetime]
    last_config_collected_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConnectivityTestResponse(BaseModel):
    status: str
    reachable: bool
    tls_valid: bool
    authenticated: bool
    latency_ms: Optional[float]
    error_detail: Optional[str]


class ConfigVersionSummary(BaseModel):
    id: str
    version_num: int
    snapshot_type: str
    config_hash: str
    interface_count: int
    zone_count: int
    object_count: int
    policy_count: int
    diff_summary: dict
    is_drift: bool
    collected_at: datetime

    class Config:
        from_attributes = True


class ConfigVersionDetail(ConfigVersionSummary):
    interfaces: list[dict]
    zones: list[dict]
    objects: list[dict]
    policies: list[dict]


class MetricPoint(BaseModel):
    metric_name: str
    value: float
    unit: Optional[str]
    dimensions: dict
    recorded_at: datetime

    class Config:
        from_attributes = True


class HealthEventResponse(BaseModel):
    id: str
    severity: str
    category: str
    message: str
    occurred_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class InterfaceStatusResponse(BaseModel):
    name: str
    zone: Optional[str] = None
    admin_up: bool
    oper_up: bool
    ip_addresses: list[str]
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
    in_bps: Optional[float] = None
    out_bps: Optional[float] = None
    collected_at: datetime


class DigitalTwinResponse(BaseModel):
    device: DeviceResponse
    latest_config: Optional[ConfigVersionSummary]
    latest_metrics: dict[str, MetricPoint]
    active_health_events: list[HealthEventResponse]
    generated_at: datetime
    cache_hit: bool = False


class ChangeRequestCreate(BaseModel):
    action: str = Field(description="create, update, or delete")
    target_type: str
    target_name: str
    element_xml: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: Optional[str] = None


class ChangeRequestResponse(BaseModel):
    id: str
    device_id: str
    action: str
    target_type: str
    target_name: str
    element_xml: Optional[str]
    payload: dict[str, Any]
    status: str
    validation_errors: list[str]
    validation_warnings: list[str]
    impact_summary: dict[str, Any]
    requested_by: Optional[str]
    approved_by: Optional[str]
    rejection_reason: Optional[str]
    commit_job_id: Optional[str]
    error_detail: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RejectRequest(BaseModel):
    reason: str
    rejected_by: Optional[str] = None


class ApproveRequest(BaseModel):
    approved_by: Optional[str] = None


class RollbackRequest(BaseModel):
    to_version: str


class LogEntryResponse(BaseModel):
    id: str
    log_type: str
    raw: dict[str, Any]
    logged_at: datetime
    collected_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
