"""报告路由：读取、保存、下载报告。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from DataCode.report_generator import report_to_markdown, report_to_html, report_to_pdf_bytes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])


def _get_state(key: str) -> str:
    from DataCode.web_server import _app_state
    return _app_state[key]


def _report_path(patient_id: str) -> Path:
    if ".." in patient_id or "/" in patient_id or "\\" in patient_id:
        raise HTTPException(status_code=400, detail="Invalid patient_id")
    return Path(_get_state("reports_dir")) / patient_id / "report.json"


@router.get("/{patient_id}")
async def get_report(patient_id: str):
    """获取最新报告（5 tab JSON）。"""
    path = _report_path(patient_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@router.post("/{patient_id}")
async def save_report(patient_id: str, report: dict):
    """保存编辑后的报告。"""
    path = _report_path(patient_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


@router.get("/{patient_id}/download")
async def download_report(patient_id: str, format: str = "md"):
    """下载报告（md/html/pdf）。"""
    path = _report_path(patient_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    report = json.loads(path.read_text(encoding="utf-8"))

    if format == "md":
        content = report_to_markdown(report)
        filename = quote(f"report_{patient_id}.md")
        return PlainTextResponse(content, media_type="text/markdown",
                                 headers={"Content-Disposition": f"attachment; filename={filename}"})
    elif format == "html":
        content = report_to_html(report)
        filename = quote(f"report_{patient_id}.html")
        return PlainTextResponse(content, media_type="text/html",
                                 headers={"Content-Disposition": f"attachment; filename={filename}"})
    elif format == "pdf":
        content = report_to_pdf_bytes(report)
        filename = quote(f"report_{patient_id}.pdf")
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Use md, html, or pdf.")
