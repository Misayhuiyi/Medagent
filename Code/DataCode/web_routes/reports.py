"""报告路由：读取、保存、下载报告。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
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


def _report_path(patient_id: str, visit_date: str = "") -> Path:
    if ".." in patient_id or "/" in patient_id or "\\" in patient_id:
        raise HTTPException(status_code=400, detail="Invalid patient_id")
    base = Path(_get_state("reports_dir")) / patient_id
    if visit_date:
        if ".." in visit_date or "/" in visit_date or "\\" in visit_date:
            raise HTTPException(status_code=400, detail="Invalid visit_date")
        return base / visit_date / "report.json"
    latest = base / "report.json"
    if latest.exists():
        return latest
    dated_reports = sorted(
        (p for p in base.glob("*/report.json") if p.parent.name),
        key=lambda p: p.parent.name,
        reverse=True,
    ) if base.exists() else []
    return dated_reports[0] if dated_reports else latest


def _first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" ：:，,;；")
            if value:
                return value
    return ""


def _clean_ocr_header_text(text: str) -> str:
    text = re.sub(r"</?(?:sub|sup|span|font|b|strong|i|u)\b[^>]*>", "", text or "", flags=re.I)
    text = text.replace("&nbsp;", " ")
    return text


def _extract_patient_info_from_report(report: dict) -> dict:
    for tab_key in ("patient-history", "patient-overview"):
        tab = report.get(tab_key)
        if not isinstance(tab, dict):
            continue
        info = tab.get("patient_info") or tab.get("basic_info") or tab.get("患者信息")
        if not isinstance(info, dict):
            continue
        return {
            "name": info.get("name") or info.get("姓名") or "",
            "sex": info.get("sex") or info.get("gender") or info.get("性别") or "",
            "age": info.get("age") or info.get("年龄") or "",
            "patient_id": (
                info.get("visit_number")
                or info.get("outpatient_no")
                or info.get("outpatient_number")
                or info.get("medical_record_no")
                or info.get("门诊号")
                or info.get("病历号")
                or info.get("住院号")
                or ""
            ),
            "phone": info.get("phone") or info.get("联系电话") or "",
        }
    return {}


def _extract_patient_info_from_ocr(patient_dir: Path, visit_date: str = "") -> dict:
    if not patient_dir.exists():
        return {}

    candidates: list[tuple[int, Path]] = []
    for md_file in patient_dir.rglob("*/ocr/*.md"):
        if md_file.parent.parent.name != md_file.stem:
            continue
        rel = md_file.relative_to(patient_dir).as_posix()
        score = 0
        if visit_date and visit_date in rel:
            score -= 100
        if any(keyword in rel for keyword in ("门诊记录", "入院记录", "出院记录", "入出院记录", "病历")):
            score -= 20
        if any(keyword in rel for keyword in ("检验报告", "影像报告")):
            score += 10
        candidates.append((score, md_file))

    merged = ""
    for _, md_file in sorted(candidates, key=lambda item: (item[0], item[1].as_posix()))[:12]:
        try:
            merged += "\n" + _clean_ocr_header_text(md_file.read_text(encoding="utf-8", errors="replace")[:2500])
        except OSError:
            continue

    info: dict[str, str] = {}
    info["name"] = _first_match(merged, [
        r"(?:患者姓名|姓名)\s*[:：]?\s*([\u4e00-\u9fa5]{2,6})",
    ])
    info["sex"] = _first_match(merged, [
        r"(?:性别)\s*[:：]?\s*([男女])",
        r"([男女])\s*性别",
    ])
    info["age"] = _first_match(merged, [
        r"(?:年龄)\s*[:：]?\s*(\d{1,3})(?=\s*岁)",
    ])
    info["patient_id"] = _first_match(merged, [
        r"(?:门诊号|门诊号码)\s*[:：]?\s*([A-Za-z0-9-]{4,30})",
        r"(?:病历号|住院号|住院号码)\s*[:：]?\s*([A-Za-z0-9-]{4,30})",
    ])
    # Only accept explicit patient contact labels. Lab-report service phones are
    # intentionally ignored because they describe hospital report contacts.
    info["phone"] = _first_match(merged, [
        r"(?:患者电话|本人电话|联系电话|手机号码|电话)\s*[:：]?\s*((?:1\d{10})|(?:\d{6,12}))",
    ])
    return {key: value for key, value in info.items() if value}


def _merge_patient_info(base: dict, *sources: dict) -> dict:
    for source in sources:
        for key, value in source.items():
            if value and not base.get(key):
                base[key] = str(value).strip()
    if base.get("patient_id") and not base.get("id"):
        base["id"] = base["patient_id"]
    if base.get("id") and not base.get("patient_id"):
        base["patient_id"] = base["id"]
    return base


def _get_patient_info(patient_id: str, visit_date: str = "", report: dict | None = None) -> dict:
    """从 TempData/patients/ 目录获取患者基本信息。"""
    patients_dir = Path(_get_state("patients_dir"))
    patient_dir = patients_dir / patient_id
    info: dict = {"id": patient_id, "patient_id": "", "name": patient_id}
    if not patient_dir.exists():
        return info

    # 从目录名推断中文名
    parts = patient_id.rsplit("-", 1)
    info["name"] = parts[0] if len(parts) == 2 else patient_id

    date = visit_date
    if not date:
        try:
            from DataCode.report_context import detect_patient_encounters

            encounters = detect_patient_encounters(patient_dir)
            selected = next((item for item in reversed(encounters) if item.get("type") != "discharge"), encounters[-1] if encounters else {})
            date = str(selected.get("admission", ""))
        except Exception:
            logger.exception("Failed to infer patient date for %s", patient_id)
    info["date"] = date or datetime.now().strftime("%Y-%m-%d")
    info["visit_date"] = info["date"]

    report_info = _extract_patient_info_from_report(report or {})
    ocr_info = _extract_patient_info_from_ocr(patient_dir, str(info["date"] or ""))
    _merge_patient_info(info, report_info, ocr_info)
    if not info.get("patient_id"):
        info["patient_id"] = patient_id
    if not info.get("id"):
        info["id"] = info["patient_id"]

    return info


def _download_filename(patient_info: dict, format: str, visit_date: str = "") -> str:
    """生成下载文件名：肺瘤慢病化管理AI门诊报告V4_{姓名}_{患者编号}.{format}"""
    name = patient_info.get("name", patient_info.get("id", ""))
    pid = patient_info.get("id", "")
    safe_name = name.replace(" ", "_")
    safe_pid = pid.replace(" ", "_")

    ext = {"md": "md", "html": "html", "pdf": "pdf"}[format]
    date_part = f"_{visit_date}" if visit_date else ""
    return f"肺瘤慢病化管理AI门诊报告V4_{safe_name}_{safe_pid}{date_part}.{ext}"


def _sanitize_report_for_display(report: dict) -> dict:
    """Clean legacy report markdown before returning it to the frontend."""
    try:
        from DataCode.skill_executor import SkillExecutor
    except Exception:
        return report

    cleaned: dict = {}
    for tab, value in report.items():
        if not isinstance(value, dict):
            cleaned[tab] = value
            continue
        item = dict(value)
        for key in ("_content", "content", "result"):
            raw = item.get(key)
            if isinstance(raw, str):
                item[key] = SkillExecutor._clean_agent_content(raw)
        cleaned[tab] = item
    return cleaned


@router.get("/{patient_id}")
async def get_report(patient_id: str, visit_date: str = ""):
    """获取最新报告（5 tab JSON）。"""
    path = _report_path(patient_id, visit_date)
    if not path.exists():
        return {}
    try:
        return _sanitize_report_for_display(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {}


@router.post("/{patient_id}")
async def save_report(patient_id: str, report: dict, visit_date: str = ""):
    """保存编辑后的报告。"""
    path = _report_path(patient_id, visit_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


@router.get("/{patient_id}/download")
async def download_report(patient_id: str, format: str = "pdf", visit_date: str = ""):
    """下载报告（md/html/pdf 格式），默认 PDF。

    文件名格式：肺瘤慢病化管理AI门诊报告V4_{姓名}_{患者编号}.{format}
    """
    path = _report_path(patient_id, visit_date)
    if not path.exists():
        raise HTTPException(status_code=404, detail="报告未生成，请先生成报告后再下载")

    report = _sanitize_report_for_display(json.loads(path.read_text(encoding="utf-8")))
    patient_info = _get_patient_info(patient_id, visit_date, report)
    filename = _download_filename(patient_info, format, visit_date)

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
            content = await asyncio.to_thread(report_to_pdf_bytes, report, REPORT_TITLE, patient_info)
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
