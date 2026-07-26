from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services import report_service
from app.services.device_service import DeviceNotFoundError

router = APIRouter(prefix="/api/v1/devices/{device_id}/reports", tags=["reports"])


@router.get("/{report_type}")
async def get_report(
    device_id: str,
    report_type: str,
    format: str = Query(default="pdf", pattern="^(pdf|json)$"),
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await report_service.gather_report_data(db, device_id, report_type)
    except DeviceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if format == "json":
        return data

    pdf_bytes = report_service.render_pdf(data)
    filename = f"infraos-{report_type}-report-{device_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
