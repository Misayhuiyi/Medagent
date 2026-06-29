"""报告路由：读取、保存、下载报告。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from DataCode.report_generator import (
    report_to_markdown, report_to_html, report_to_pdf_bytes, REPORT_TITLE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])


def _get_state(key: str) -> str:
    from DataCode.web_server import _app_state
    return _app_state[key]


def _report_path(patient_id: str) -> Path:
    if ".." in patient_id or "/" in patient_id or "\\" in patient_id:
        raise HTTPException(status_code=400, detail="Invalid patient_id")
    return Path(_get_state("reports_dir")) / patient_id / "report.json"


def _get_patient_info(patient_id: str) -> dict:
    """从 TempData/patients/ 目录获取患者基本信息。"""
    patients_dir = Path(_get_state("patients_dir"))
    patient_dir = patients_dir / patient_id
    info: dict = {"id": patient_id, "name": patient_id}
    if not patient_dir.exists():
        return info

    # 从目录名推断中文名
    parts = patient_id.rsplit("-", 1)
    info["name"] = parts[0] if len(parts) == 2 else patient_id

    # 从 OCR 文件推断就诊日期
    date = ""
    for md_file in sorted(patient_dir.rglob("ocr/*.md")):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")[:2000]
            import re
            date_pattern = re.compile(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})')
            m = date_pattern.search(content)
            if m:
                y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
                if 2020 <= int(y) <= 2030:
                    date = f"{y}-{mo}-{d}"
                    break
        except Exception:
            continue
    info["date"] = date or datetime.now().strftime("%Y-%m-%d")

    return info


def _download_filename(patient_info: dict, format: str) -> str:
    """生成下载文件名：肺瘤慢病化管理AI门诊报告V4_{姓名}_{患者编号}.{format}"""
    name = patient_info.get("name", patient_info.get("id", ""))
    pid = patient_info.get("id", "")
    safe_name = name.replace(" ", "_")
    safe_pid = pid.replace(" ", "_")

    ext = {"md": "md", "html": "html", "pdf": "pdf"}[format]
    return f"肺瘤慢病化管理AI门诊报告V4_{safe_name}_{safe_pid}.{ext}"


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
async def download_report(patient_id: str, format: str = "pdf"):
    """下载报告（md/html/pdf 格式），默认 PDF。

    文件名格式：肺瘤慢病化管理AI门诊报告V4_{姓名}_{患者编号}.{format}
    """
    path = _report_path(patient_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告未生成，请先生成报告后再下载")

    report = json.loads(path.read_text(encoding="utf-8"))
    patient_info = _get_patient_info(patient_id)
    filename = _download_filename(patient_info, format)

    if format == "md":
        content = report_to_markdown(report, REPORT_TITLE, patient_info)
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
    elif format == "html":
        content = report_to_html(report, REPORT_TITLE, patient_info)
        return PlainTextResponse(content, media_type="text/html; charset=utf-8",
                                 headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
    elif format == "pdf":
        try:
            content = report_to_pdf_bytes(report, REPORT_TITLE, patient_info)
        except Exception as e:
            logger.exception("PDF generation failed for %s", patient_id)
            raise HTTPException(status_code=500, detail=f"PDF 生成失败：{e}")
        # fpdf2 pdf.output() 返回 bytearray → bytes（Starlette Response 需要）
        if isinstance(content, bytearray):
            content = bytes(content)
        elif isinstance(content, str):
            content = content.encode("utf-8")
        return Response(content, media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
    else:
        raise HTTPException(status_code=400, detail="Unsupported format. Use md, html, or pdf.")
