from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    vendor: Mapped[str] = mapped_column(String, default="paloalto")
    hostname: Mapped[str] = mapped_column(String, nullable=True)
    mgmt_host: Mapped[str] = mapped_column(String)
    mgmt_port: Mapped[int] = mapped_column(Integer, default=443)

    # credentials — encrypted at rest via CredentialCipher, never returned by the API
    username: Mapped[str] = mapped_column(String, nullable=True)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=True)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=True)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)

    # discovery-derived fields, refreshed on each discover() call
    model: Mapped[str] = mapped_column(String, nullable=True)
    serial: Mapped[str] = mapped_column(String, nullable=True)
    os_version: Mapped[str] = mapped_column(String, nullable=True)
    ha_state: Mapped[str] = mapped_column(String, nullable=True)
    ha_peer_serial: Mapped[str] = mapped_column(String, nullable=True)
    uptime_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    licenses: Mapped[list] = mapped_column(JSON, default=list)

    connection_status: Mapped[str] = mapped_column(String, default="unknown")
    last_connectivity_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_config_collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    config_versions: Mapped[list["ConfigVersion"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    metrics: Mapped[list["MetricRecord"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    health_events: Mapped[list["HealthEvent"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class ConfigVersion(Base):
    """One row per collected configuration snapshot. `version_num` increments
    per device; `diff_summary` is computed relative to the previous version
    at collection time so the version-history UI doesn't need to recompute
    diffs on every read."""
    __tablename__ = "config_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.id"))
    version_num: Mapped[int] = mapped_column(Integer)
    snapshot_type: Mapped[str] = mapped_column(String, default="running")
    config_hash: Mapped[str] = mapped_column(String)

    interface_count: Mapped[int] = mapped_column(Integer, default=0)
    zone_count: Mapped[int] = mapped_column(Integer, default=0)
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    policy_count: Mapped[int] = mapped_column(Integer, default=0)

    interfaces: Mapped[list] = mapped_column(JSON, default=list)
    zones: Mapped[list] = mapped_column(JSON, default=list)
    objects: Mapped[list] = mapped_column(JSON, default=list)
    policies: Mapped[list] = mapped_column(JSON, default=list)

    diff_summary: Mapped[dict] = mapped_column(JSON, default=dict)  # {added: [...], removed: [...], changed: [...]}
    is_drift: Mapped[bool] = mapped_column(Boolean, default=False)  # differs from previous even though no platform-initiated change was recorded

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    device: Mapped["Device"] = relationship(back_populates="config_versions")


class MetricRecord(Base):
    __tablename__ = "metrics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.id"))
    metric_name: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String, nullable=True)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    device: Mapped["Device"] = relationship(back_populates="metrics")


class HealthEvent(Base):
    __tablename__ = "health_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.id"))
    severity: Mapped[str] = mapped_column(String)  # info, warning, critical
    category: Mapped[str] = mapped_column(String)  # connectivity, license, config_drift, resource, ha
    message: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="health_events")
