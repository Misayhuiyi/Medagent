"""聊天路由：发送消息（SSE 流式响应）+ 获取历史。

请求模式：
  - mode = "chat"   主 LLM 直接回答（默认）
  - mode = "report" 子 LLM 串行执行 5 个 Skill，更新右侧报告
  - mode = "auto"   根据消息关键词自动判断
"""

from __future__ import annotations

import json
import logging
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


class MessageRequest(BaseModel):
    message: str
    mode: Literal["chat", "report", "auto"] = Field(default="auto")


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
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


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
        return json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


@router.post("/{patient_id}/messages")
async def send_message(patient_id: str, body: MessageRequest):
    """发送消息，返回 SSE 流式响应。"""
    _sanitize_path_segment(patient_id)
    pdir = _patient_dir(patient_id)
    if not pdir.exists():
        raise HTTPException(status_code=404, detail="Patient not found")

    mode = _resolve_mode(body.message, body.mode)
    history_before = _load_history(patient_id)
    _save_chat_message(patient_id, "user", body.message)
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

            files = _load_patient_files(patient_id)
            logger.info("Chat patient=%s loaded_files=%d mode=%s", patient_id, len(files), mode)

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
                visit_date = _extract_visit_date(files)
                yield _format_sse({"id": 0, "event": "mode", "data": {"mode": "report"}})
                async for event in executor.execute_report_skills(
                    patient_id=patient_id,
                    files=files,
                    message=body.message,
                    visit_date=visit_date,
                ):
                    if event["event"] == "tab_ready":
                        _save_report_tab(patient_id, event["data"]["tab"], event["data"]["data"])
                    if event["event"] == "token":
                        assistant_buffer.append(str(event["data"].get("content", "")))
                    yield _format_sse(event)

            if assistant_buffer:
                _save_chat_message(patient_id, "assistant", "".join(assistant_buffer))

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
        for part in name.replace("_", " ").split():
            if part.isdigit() and len(part) == 8:
                return f"{part[:4]}-{part[4:6]}-{part[6:8]}"
    return datetime.now().strftime("%Y-%m")


@router.get("/{patient_id}/history")
async def get_chat_history(patient_id: str):
    """获取聊天历史。"""
    _sanitize_path_segment(patient_id)
    history_path = _memory_dir(patient_id) / "chat_history.json"
    if not history_path.exists():
        return []
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return []


def _save_report_tab(patient_id: str, tab: str, data: dict):
    """将 tab 数据保存到报告文件。"""
    _sanitize_path_segment(patient_id)
    reports_dir = Path(_get_state("reports_dir")) / patient_id
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {}
    report[tab] = data
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
