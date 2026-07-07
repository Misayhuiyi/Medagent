"""聊天路由：发送消息（SSE 流式响应）+ 获取历史。

请求模式：
  - mode = "chat"   主 LLM 直接回答（默认）
  - mode = "report" 子 LLM 串行执行 5 个 Skill，更新右侧报告
  - mode = "auto"   根据消息关键词自动判断

encounter 参数（可选）：
  - null / 不传：使用全部患者文件（当前行为）
  - {admission, discharge, type, source_admission}：按该时间点读取累计资料并注入上一期报告
"""

from __future__ import annotations

import json
import logging
import re as _re
from pathlib import Path
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])

_REPORT_KEYWORDS = (
    "生成报告", "完整报告", "门诊报告", "更新右侧", "更新报告",
    "五个页签", "5个页签", "右侧报告", "结构化报告",
)
_HISTORY_REPORT_NOISE_KEYWORDS = (
    *_REPORT_KEYWORDS,
    "报告已生成",
    "已完成生成报告",
    "已完成患者病史总结",
    "已完成患者概况",
    "已完成治疗方案",
    "已完成疗效预测",
    "已完成其他建议",
)

_DATE_RANGE_RE = _re.compile(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})')


class EncounterFilter(BaseModel):
    admission: str = ""
    discharge: str = ""
    type: str = ""
    label: str = ""
    source_admission: str = ""


class MessageRequest(BaseModel):
    message: str
    mode: Literal["chat", "report", "auto"] = Field(default="auto")
    encounter: EncounterFilter | None = Field(default=None, description="按就诊时间过滤文件，null=全部")


def _get_state(key: str) -> str:
    from DataCode.web_server import _app_state
    return _app_state[key]


def _sanitize_path_segment(segment: str) -> str:
    """消毒路径参数，拒绝 .. 和绝对路径。"""
    if ".." in segment or "/" in segment or "\\" in segment:
        raise HTTPException(status_code=400, detail="Invalid path segment")
    return segment


def _patient_dir(patient_id: str) -> Path:
    return Path(_get_state("patients_dir")) / patient_id


def _memory_dir(patient_id: str) -> Path:
    return Path(_get_state("memory_dir")) / patient_id


def _load_patient_files(patient_id: str) -> list[dict]:
    """递归读取患者目录下所有 OCR Markdown 文件内容。

    Caller must sanitize patient_id (no '..' or path separators) before calling.
    """
    pdir = _patient_dir(patient_id)
    if not pdir.exists():
        return []
    files = []
    for md_file in sorted(pdir.rglob("*/ocr/*.md")):
        # 跳过文件名与父目录不匹配的 OCR 文件（如 notes.md 在 A1/ocr/ 下）
        if md_file.parent.parent.name != md_file.stem:
            continue
        content = md_file.read_text(encoding="utf-8", errors="replace")
        # 路径：分类/stem.pdf（与前端文件树展示一致）
        rel = md_file.relative_to(pdir)
        # rel = "病历/A19/ocr/A19.md" → category="病历", stem="A19"
        parts = rel.parts
        category = parts[0]
        stem = md_file.stem
        files.append({"name": f"{category}/{stem}.pdf", "content": content})
    return files


def _extract_dates(content: str) -> list[str]:
    """提取文件内容中 2020-2030 范围内的所有日期字符串。"""
    dates: list[str] = []
    for m in _DATE_RANGE_RE.finditer(content[:2000]):
        y, mo, dy = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        if 2020 <= int(y) <= 2030:
            dates.append(f"{y}-{mo}-{dy}")
    return dates


def _extract_file_date(file_name: str, content: str) -> str | None:
    """从文件名或内容中提取文件的就诊日期。

    优先级：
    1. 文件名中的日期（如 病历/2023-12-05_入院记录.pdf → 2023-12-05）
    2. 文件内容中的最早日期（备用）

    文件名日期才是文档的**真实就诊时间**，内容中可能包含多年前的历史日期。
    """
    # 1. 尝试文件名
    stem = file_name.replace("\\", "/").split("/")[-1]  # "2023-12-05_入院记录.pdf"
    for m in _DATE_RANGE_RE.finditer(stem):
        y, mo, dy = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        if 2020 <= int(y) <= 2030:
            return f"{y}-{mo}-{dy}"
    # 2. 回退：内容最早日期
    dates = _extract_dates(content)
    return min(dates) if dates else None


def _filter_files_by_encounter(
    files: list[dict],
    encounter: EncounterFilter | None,
) -> list[dict]:
    """按就诊时间范围过滤文件。encounter=None 时返回全部文件。"""
    if encounter is None:
        return files
    adm = encounter.admission
    dis = encounter.discharge or adm
    if not adm:
        return files
    filtered: list[dict] = []
    for f in files:
        file_dt = _extract_file_date(f["name"], f["content"])
        if not file_dt:
            continue
        if adm <= file_dt <= dis:
            filtered.append(f)
    return filtered


def _load_files_for_request(patient_id: str, encounter: EncounterFilter | None, mode: str) -> tuple[list[dict], str, str]:
    """Load raw evidence for chat/report while keeping longitudinal report stages continuous."""
    from DataCode.report_context import detect_patient_encounters, load_cumulative_patient_files

    pdir = _patient_dir(patient_id)
    has_selected_encounter = bool(encounter and encounter.admission)
    visit_date = _resolve_visit_date(pdir, encounter)
    encounter_type = _resolve_encounter_type(pdir, encounter, visit_date)
    if mode == "report" and not has_selected_encounter:
        files = load_cumulative_patient_files(pdir, visit_date="")
        return files, visit_date, "all"
    if mode == "report" and visit_date:
        return load_cumulative_patient_files(pdir, visit_date=visit_date), visit_date, encounter_type
    if encounter and visit_date:
        return load_cumulative_patient_files(pdir, visit_date=visit_date), visit_date, encounter_type

    files = _load_patient_files(patient_id)
    if not visit_date:
        encounters = detect_patient_encounters(pdir)
        visit_date = str(encounters[-1].get("admission", "")) if encounters else _extract_visit_date(files)
        encounter_type = str(encounters[-1].get("type", "")) if encounters else "all"
    return files, visit_date, encounter_type or "all"


def _resolve_visit_date(pdir: Path, encounter: EncounterFilter | None) -> str:
    from DataCode.report_context import detect_patient_encounters

    if encounter and _is_valid_date(encounter.admission):
        if encounter.type == "discharge" and _is_valid_date(encounter.source_admission):
            return encounter.source_admission
        return encounter.admission
    encounters = detect_patient_encounters(pdir)
    if encounters:
        selected = next((item for item in reversed(encounters) if item.get("type") != "discharge"), encounters[-1])
        return str(selected.get("admission", ""))
    return ""


def _resolve_encounter_type(pdir: Path, encounter: EncounterFilter | None, visit_date: str) -> str:
    if encounter and encounter.type:
        return encounter.type
    try:
        from DataCode.report_context import detect_patient_encounters

        matched = next((item for item in detect_patient_encounters(pdir) if item.get("admission") == visit_date), None)
        return str((matched or {}).get("type") or "selected")
    except Exception:
        return "selected"


def _is_valid_date(value: str) -> bool:
    try:
        return bool(value and len(value) == 10 and datetime.strptime(value, "%Y-%m-%d"))
    except ValueError:
        return False


def _format_sse(event: dict) -> str:
    """将事件 dict 格式化为 SSE 文本块。"""
    lines = [f"id: {event['id']}", f"event: {event['event']}"]
    lines.append(f"data: {json.dumps(event['data'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _save_chat_message(patient_id: str, role: str, content: str):
    """追加一条消息到聊天历史文件。"""
    mem_dir = _memory_dir(patient_id)
    mem_dir.mkdir(parents=True, exist_ok=True)
    history_path = mem_dir / "chat_history.json"
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
    else:
        history = []
    history.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })
    history = _clean_chat_history(history)
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_report_task_message(patient_id: str, role: str, content: str):
    """Keep report-generation chatter out of the clinical chat history."""
    mem_dir = _memory_dir(patient_id)
    mem_dir.mkdir(parents=True, exist_ok=True)
    path = mem_dir / "report_history.json"
    try:
        history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (json.JSONDecodeError, OSError):
        history = []
    history.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })
    if len(history) > 80:
        history = history[-80:]
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_mode(message: str, requested: str) -> str:
    if requested in ("chat", "report"):
        return requested
    text = (message or "").strip()
    if any(keyword in text for keyword in _REPORT_KEYWORDS):
        return "report"
    return "chat"


def _load_history(patient_id: str) -> list[dict]:
    history_path = _memory_dir(patient_id) / "chat_history.json"
    if not history_path.exists():
        return []
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    cleaned = _clean_chat_history(history)
    if cleaned != history:
        try:
            backup_path = history_path.with_suffix(".json.bak")
            if not backup_path.exists():
                backup_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            history_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Failed to persist cleaned chat history for %s", patient_id)
    return cleaned


def _clean_chat_history(history: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for entry in history if isinstance(history, list) else []:
        role = entry.get("role")
        content = str(entry.get("content", "")).strip()
        if role not in ("user", "assistant") or not content:
            continue
        if _is_report_history_noise(content):
            continue
        cleaned.append({
            "role": role,
            "content": content,
            "timestamp": entry.get("timestamp") or datetime.now().isoformat(timespec="seconds"),
        })
    return cleaned[-80:]


def _is_report_history_noise(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return True
    if "针对问题「" in text and "建议结合原始数据进一步分析" in text:
        return True
    if "资料统计：" in text and "### 文件 " in text and "（其余 " in text:
        return True
    return any(keyword in text for keyword in _HISTORY_REPORT_NOISE_KEYWORDS)


@router.post("/{patient_id}/messages")
async def send_message(patient_id: str, body: MessageRequest):
    """发送消息，返回 SSE 流式响应。"""
    _sanitize_path_segment(patient_id)
    pdir = _patient_dir(patient_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="Patient not found")

    mode = _resolve_mode(body.message, body.mode)
    history_before = _load_history(patient_id)
    if mode == "chat":
        _save_chat_message(patient_id, "user", body.message)
    else:
        _save_report_task_message(patient_id, "user", body.message)
    logger.info(
        "Chat request patient=%s mode=%s requested=%s message_chars=%d",
        patient_id, mode, body.mode, len(body.message or ""),
    )

    async def event_stream():
        from DataCode.web_server import _app_state
        executor = _app_state.get("skill_executor")
        try:
            if executor is None:
                yield _format_sse({"id": 1, "event": "status", "data": {"state": "mock_mode"}})
                yield _format_sse({"id": 2, "event": "done", "data": {}})
                return

            files, visit_date, encounter_type = _load_files_for_request(patient_id, body.encounter, mode)
            logger.info(
                "Chat patient=%s files=%d mode=%s visit_date=%s encounter_type=%s encounter=%s",
                patient_id, len(files), mode, visit_date, encounter_type,
                body.encounter.model_dump_json() if body.encounter else "all",
            )

            assistant_buffer: list[str] = []

            if mode == "chat":
                yield _format_sse({"id": 0, "event": "mode", "data": {"mode": "chat"}})
                async for event in executor.execute_chat(
                    patient_id=patient_id,
                    files=files,
                    message=body.message,
                    history=history_before,
                ):
                    if event["event"] == "token":
                        assistant_buffer.append(str(event["data"].get("content", "")))
                    yield _format_sse(event)
            else:
                _clear_report_cache(patient_id, visit_date)
                prior_reports = ""
                try:
                    from DataCode.report_context import collect_prior_context_entries, format_prior_context

                    prior_entries = collect_prior_context_entries(pdir, visit_date)
                    prior_reports = format_prior_context(prior_entries)
                    logger.info(
                        "Report prior context patient=%s visit_date=%s entries=%d chars=%d",
                        patient_id, visit_date, len(prior_entries), len(prior_reports),
                    )
                except Exception:
                    logger.exception(
                        "Failed to load prior report context patient=%s visit_date=%s",
                        patient_id, visit_date,
                    )
                yield _format_sse({"id": 0, "event": "mode", "data": {"mode": "report"}})
                async for event in executor.execute_report_skills(
                    patient_id=patient_id,
                    files=files,
                    message=body.message,
                    visit_date=visit_date,
                    prior_reports=prior_reports,
                    patient_dir=str(pdir),
                ):
                    if event["event"] == "tab_ready":
                        _save_report_tab(patient_id, event["data"]["tab"], event["data"]["data"], visit_date)
                    if event["event"] == "token":
                        assistant_buffer.append(str(event["data"].get("content", "")))
                    yield _format_sse(event)

            if assistant_buffer:
                if mode == "chat":
                    _save_chat_message(patient_id, "assistant", "".join(assistant_buffer))
                else:
                    _save_report_task_message(patient_id, "assistant", "".join(assistant_buffer))

        except Exception as e:
            logger.exception("SSE stream error patient=%s mode=%s", patient_id, mode)
            yield _format_sse({"id": 999, "event": "error", "data": {"message": str(e)}})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # 关闭各级缓存/缓冲，保证 token/tab_ready 事件能逐条实时到达前端。
            # 否则反向代理（含 Vite dev proxy、nginx）可能整体缓冲，破坏流式体验。
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _extract_visit_date(files: list[dict]) -> str:
    for f in files:
        name = f["name"]
        for match in _DATE_RANGE_RE.finditer(name):
            y, mo, dy = match.group(1), match.group(2).zfill(2), match.group(3).zfill(2)
            if 2020 <= int(y) <= 2030:
                return f"{y}-{mo}-{dy}"
        for part in name.replace("_", " ").split():
            if part.isdigit() and len(part) == 8:
                return f"{part[:4]}-{part[4:6]}-{part[6:8]}"
    for f in files:
        dates = _extract_dates(str(f.get("content", "")))
        if dates:
            return dates[0]
    return datetime.now().strftime("%Y-%m-%d")


@router.get("/{patient_id}/history")
async def get_chat_history(patient_id: str):
    """获取聊天历史。"""
    _sanitize_path_segment(patient_id)
    history_path = _memory_dir(patient_id) / "chat_history.json"
    if not history_path.exists():
        return []
    try:
        return _clean_chat_history(json.loads(history_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, Exception):
        return []


def _clear_report_cache(patient_id: str, visit_date: str = ""):
    """Clear stale preview/report cache for a new generation task."""
    _sanitize_path_segment(patient_id)
    reports_dir = Path(_get_state("reports_dir")) / patient_id
    targets = [reports_dir / "report.json"]
    if _is_valid_date(visit_date):
        targets.append(reports_dir / visit_date / "report.json")
    for path in targets:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.exception("Failed to clear stale report cache %s", path)
    try:
        from DataCode.web_server import _app_state

        cache = _app_state.get("trace_cache", {})
        for key in list(cache.keys()):
            if str(key) == patient_id or str(key).startswith(f"{patient_id}:"):
                cache.pop(key, None)
    except Exception:
        logger.exception("Failed to clear trace cache for %s", patient_id)


def _save_report_tab(patient_id: str, tab: str, data: dict, visit_date: str = ""):
    """将 tab 数据保存到报告文件。"""
    _sanitize_path_segment(patient_id)
    reports_dir = Path(_get_state("reports_dir")) / patient_id
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_dir = reports_dir / visit_date if _is_valid_date(visit_date) else reports_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {}
    report[tab] = data
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Keep the legacy latest-report path for the current frontend preview/download flow.
    latest_path = reports_dir / "report.json"
    if latest_path != report_path:
        latest_report = {}
        if latest_path.exists():
            try:
                latest_report = json.loads(latest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                latest_report = {}
        latest_report[tab] = data
        latest_path.write_text(json.dumps(latest_report, ensure_ascii=False, indent=2), encoding="utf-8")
