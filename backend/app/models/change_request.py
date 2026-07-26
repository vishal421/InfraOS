from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.entities import _now, _uuid


class ConfigChangeRequest(Base):
    """
    The state machine described in the architecture doc:
    DRAFT -> VALIDATED -> PENDING_APPROVAL -> APPROVED -> PUSHED -> COMMITTED
                    \\-> VALIDATION_FAILED        \\-> REJECTED
    PUSHED -> (verification fails) -> ROLLED_BACK

    No path in this table skips APPROVED before PUSHED. That's enforced in
    the service layer, not just by convention — see config_change_service.py.
    """
    __tablename__ = "config_change_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(String, ForeignKey("devices.id"))

    action: Mapped[str] = mapped_column(String)  # create, update, delete
    target_type: Mapped[str] = mapped_column(String)  # security_policy, address_object, ...
    target_name: Mapped[str] = mapped_column(String)
    element_xml: Mapped[str] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String, default="draft")
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    validation_warnings: Mapped[list] = mapped_column(JSON, default=list)
    impact_summary: Mapped[dict] = mapped_column(JSON, default=dict)

    requested_by: Mapped[str] = mapped_column(String, nullable=True)
    approved_by: Mapped[str] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=True)
    commit_job_id: Mapped[str] = mapped_column(String, nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    device = relationship("Device")
