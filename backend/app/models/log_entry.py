from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.entities import _now, _uuid


class LogEntryRecord(Base):
    """
    Phase 1 log storage: polled via the plugin's stream_logs() (job-based
    XML API query) and stored here. This is explicitly the "Phase 1"
    approach flagged in the plugin README — real-time ingestion via a
    syslog receiver is the Phase 2 upgrade for high log volume, and doesn't
    require changing this table's shape, just how rows get into it.
    """
    __tablename__ = "log_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.id"), index=True)
    log_type: Mapped[str] = mapped_column(String, index=True)  # traffic, threat, system, ...
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
