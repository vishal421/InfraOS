from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services import bpa_service, config_service, monitoring_service
from app.services.device_service import get_device

VALID_REPORT_TYPES = {"executive", "technical", "security"}


async def gather_report_data(db, device_id: str, report_type: str) -> dict:
    if report_type not in VALID_REPORT_TYPES:
        raise ValueError(f"report_type must be one of {sorted(VALID_REPORT_TYPES)}")

    device = await get_device(db, device_id)
    latest_config = await config_service.get_latest_config_version(db, device_id)
    health_events = await monitoring_service.list_health_events(db, device_id, active_only=True)

    bpa = None
    try:
        bpa = await bpa_service.analyze(db, device_id)
    except bpa_service.NoConfigurationError:
        pass

    data = {
        "report_type": report_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "device": {
            "hostname": device.hostname or device.mgmt_host,
            "mgmt_host": device.mgmt_host,
            "model": device.model,
            "serial": device.serial,
            "os_version": device.os_version,
            "ha_state": device.ha_state,
            "connection_status": device.connection_status,
        },
        "configuration_summary": {
            "version_num": latest_config.version_num if latest_config else None,
            "interfaces": latest_config.interface_count if latest_config else 0,
            "zones": latest_config.zone_count if latest_config else 0,
            "objects": latest_config.object_count if latest_config else 0,
            "policies": latest_config.policy_count if latest_config else 0,
        }
        if latest_config
        else None,
        "active_health_events": [
            {"severity": e.severity, "category": e.category, "message": e.message} for e in health_events
        ],
        "security_score": bpa["security_score"] if bpa else None,
        "findings": bpa["findings"] if (bpa and report_type != "executive") else None,
        "findings_by_category": bpa["findings_by_category"] if bpa else None,
    }
    return data


def render_pdf(data: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCustom", parent=styles["Title"], fontSize=20, spaceAfter=6)
    heading_style = ParagraphStyle("HeadingCustom", parent=styles["Heading2"], spaceBefore=16, spaceAfter=8)
    body_style = styles["BodyText"]

    story = []
    report_title = {
        "executive": "Executive Summary",
        "technical": "Technical Report",
        "security": "Security Report",
    }[data["report_type"]]

    story.append(Paragraph(f"InfraOS — {report_title}", title_style))
    story.append(Paragraph(f"Device: {data['device']['hostname']}", body_style))
    story.append(Paragraph(f"Generated: {data['generated_at']}", body_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Device Overview", heading_style))
    device_table_data = [
        ["Management IP", data["device"]["mgmt_host"]],
        ["Model", data["device"]["model"] or "—"],
        ["Serial", data["device"]["serial"] or "—"],
        ["PAN-OS Version", data["device"]["os_version"] or "—"],
        ["HA State", data["device"]["ha_state"] or "—"],
        ["Connection Status", data["device"]["connection_status"]],
    ]
    story.append(_styled_table(device_table_data))

    if data["security_score"] is not None:
        story.append(Paragraph("Security Posture", heading_style))
        score = data["security_score"]
        score_color = colors.HexColor("#3ecf8e") if score >= 80 else (
            colors.HexColor("#f5a623") if score >= 50 else colors.HexColor("#ff5d5d")
        )
        score_style = ParagraphStyle("Score", parent=body_style, textColor=score_color, fontSize=16)
        story.append(Paragraph(f"Security Score: {score}/100", score_style))
        if data.get("findings_by_category"):
            cat_rows = [["Finding Category", "Count"]] + [
                [cat.replace("_", " ").title(), str(count)] for cat, count in data["findings_by_category"].items()
            ]
            story.append(Spacer(1, 8))
            story.append(_styled_table(cat_rows, header=True))

    if data.get("configuration_summary"):
        story.append(Paragraph("Configuration Summary", heading_style))
        cfg = data["configuration_summary"]
        cfg_table = [
            ["Config Version", str(cfg["version_num"])],
            ["Interfaces", str(cfg["interfaces"])],
            ["Zones", str(cfg["zones"])],
            ["Objects", str(cfg["objects"])],
            ["Policies", str(cfg["policies"])],
        ]
        story.append(_styled_table(cfg_table))

    if data.get("active_health_events"):
        story.append(Paragraph("Active Health Events", heading_style))
        rows = [["Severity", "Category", "Message"]] + [
            [e["severity"], e["category"], e["message"]] for e in data["active_health_events"]
        ]
        story.append(_styled_table(rows, header=True))
    else:
        story.append(Paragraph("Active Health Events", heading_style))
        story.append(Paragraph("No active health events.", body_style))

    if data.get("findings"):
        story.append(Paragraph("Detailed Findings", heading_style))
        rows = [["Severity", "Category", "Target", "Message"]] + [
            [f["severity"], f["category"].replace("_", " "), f["target"], f["message"]] for f in data["findings"]
        ]
        story.append(_styled_table(rows, header=True, col_widths=[0.7 * inch, 1.3 * inch, 1.3 * inch, 2.8 * inch]))

    doc.build(story)
    return buffer.getvalue()


def _styled_table(rows: list[list[str]], header: bool = False, col_widths=None) -> Table:
    table = Table(rows, colWidths=col_widths)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12161d")))
        style.append(("TEXTCOLOR", (0, 0), (-1, 0), colors.white))
        style.append(("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"))
    table.setStyle(TableStyle(style))
    return table
