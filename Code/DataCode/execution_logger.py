"""ExecutionLogger：三格式日志写入器（JSON 全量、MD 全量、TXT 脱敏）。

按 session_id 隔离存储，内存累积事件，finalize 时一次性写入。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class LogEvent:
    event_type: str  # "thinking", "tool_call", "tool_result", "message", "error", "info"
    agent: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


_SESSION_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_[A-Za-z0-9]{6}$")


class ExecutionLogger:
    """三格式执行日志记录器。

    累积 LogEvent 列表，finalize 时写入三种格式文件：
    - .json: 完整结构化日志
    - .md: 可读 Markdown 日志
    - .txt: 脱敏日志（仅工具名+耗时+状态，不含思考/参数/返回值）
    """

    SANITIZE_EVENT_TYPES = {"thinking"}  # 这些类型的内容不在 .txt 中出现
    SANITIZE_DATA_KEYS = {"body", "system_prompt", "args", "result", "content"}

    def __init__(self, result_dir: str | Path, log_dir: str | Path, session_id: str):
        if not _SESSION_ID_RE.match(session_id):
            raise ValueError(f"Invalid session_id format: {session_id}")
        self._result_dir = Path(result_dir) / session_id
        self._log_dir = Path(log_dir) / session_id
        self._session_id = session_id
        self._events: list[LogEvent] = []
        self._start_time = time.time()

    @property
    def session_id(self) -> str:
        return self._session_id

    def log(self, event_type: str, agent: str = "", **data: Any) -> None:
        self._events.append(LogEvent(event_type=event_type, agent=agent, data=data))

    def log_thinking(self, content: str, agent: str = "") -> None:
        self.log("thinking", agent, content=content)

    def log_tool_call(self, tool_name: str, args: dict | None = None, agent: str = "") -> None:
        self.log("tool_call", agent, tool_name=tool_name, args=args or {})

    def log_tool_result(self, tool_name: str, result: str, elapsed_ms: float, agent: str = "") -> None:
        self.log("tool_result", agent, tool_name=tool_name, result=result, elapsed_ms=elapsed_ms)

    def log_message(self, role: str, content: str, agent: str = "") -> None:
        self.log("message", agent, role=role, content=content)

    def log_error(self, message: str, agent: str = "") -> None:
        self.log("error", agent, message=message)

    def _sanitize_event(self, event: LogEvent) -> dict[str, Any] | None:
        """脱敏处理：过滤敏感事件类型和数据字段，用于 Result/ 下的 .txt 日志。"""
        if event.event_type in self.SANITIZE_EVENT_TYPES:
            return None

        sanitized = {
            "timestamp": datetime.fromtimestamp(event.timestamp).strftime("%H:%M:%S"),
            "event_type": event.event_type,
            "agent": event.agent,
        }

        if event.event_type == "tool_call":
            sanitized["tool_name"] = event.data.get("tool_name", "")
        elif event.event_type == "tool_result":
            sanitized["tool_name"] = event.data.get("tool_name", "")
            sanitized["elapsed_ms"] = event.data.get("elapsed_ms", 0)
            result = event.data.get("result", "")
            sanitized["status"] = "error" if result.startswith("Error:") else "ok"
        elif event.event_type == "message":
            sanitized["role"] = event.data.get("role", "")
        elif event.event_type == "error":
            sanitized["status"] = "error"
        elif event.event_type == "info":
            sanitized["status"] = "info"

        return sanitized

    def finalize(self) -> dict[str, Any]:
        """写入三种格式日志文件，返回汇总统计。"""
        elapsed = time.time() - self._start_time

        self._result_dir.mkdir(parents=True, exist_ok=True)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # 统计
        stats = {
            "session_id": self._session_id,
            "elapsed_seconds": round(elapsed, 2),
            "total_events": len(self._events),
            "tool_calls": sum(1 for e in self._events if e.event_type == "tool_call"),
            "errors": sum(1 for e in self._events if e.event_type == "error"),
        }

        # .json — 完整日志
        json_data = {
            "session_id": self._session_id,
            "elapsed_seconds": stats["elapsed_seconds"],
            "events": [
                {
                    "timestamp": datetime.fromtimestamp(e.timestamp).isoformat(),
                    "event_type": e.event_type,
                    "agent": e.agent,
                    "data": e.data,
                }
                for e in self._events
            ],
        }
        (self._log_dir / "execution.json").write_text(
            json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # .md — Markdown 可读日志
        md_lines = [
            f"# 执行日志 — {self._session_id}",
            f"",
            f"- 耗时: {stats['elapsed_seconds']}s",
            f"- 事件数: {stats['total_events']}",
            f"- 工具调用: {stats['tool_calls']}",
            f"- 错误: {stats['errors']}",
            f"",
            f"---",
            f"",
        ]
        for e in self._events:
            ts = datetime.fromtimestamp(e.timestamp).strftime("%H:%M:%S")
            if e.event_type == "thinking":
                md_lines.append(f"### [{ts}] 💭 思考 ({e.agent})")
                md_lines.append(f"")
                md_lines.append(e.data.get("content", ""))
            elif e.event_type == "tool_call":
                md_lines.append(f"### [{ts}] 🔧 工具调用: {e.data.get('tool_name', '')} ({e.agent})")
                md_lines.append(f"")
                md_lines.append(f"```json")
                md_lines.append(json.dumps(e.data.get("args", {}), ensure_ascii=False, indent=2))
                md_lines.append(f"```")
            elif e.event_type == "tool_result":
                md_lines.append(f"### [{ts}] 📋 工具结果: {e.data.get('tool_name', '')} ({e.data.get('elapsed_ms', 0):.0f}ms)")
                md_lines.append(f"")
                md_lines.append(f"```")
                md_lines.append(e.data.get("result", ""))
                md_lines.append(f"```")
            elif e.event_type == "message":
                md_lines.append(f"### [{ts}] 💬 {e.data.get('role', '')} ({e.agent})")
                md_lines.append(f"")
                md_lines.append(e.data.get("content", ""))
            elif e.event_type == "error":
                md_lines.append(f"### [{ts}] ❌ 错误 ({e.agent})")
                md_lines.append(f"")
                md_lines.append(e.data.get("message", ""))
            elif e.event_type == "info":
                md_lines.append(f"### [{ts}] ℹ️ 信息 ({e.agent})")
                md_lines.append(f"")
                md_lines.append(e.data.get("message", ""))
            md_lines.append(f"")

        (self._log_dir / "execution.md").write_text(
            "\n".join(md_lines), encoding="utf-8"
        )

        # .txt — 脱敏日志（用户可见）
        txt_lines = [
            f"执行日志 — {self._session_id}",
            f"耗时: {stats['elapsed_seconds']}s | 工具调用: {stats['tool_calls']} | 错误: {stats['errors']}",
            f"",
        ]
        for e in self._events:
            sanitized = self._sanitize_event(e)
            if sanitized is None:
                continue
            ts = sanitized["timestamp"]
            etype = sanitized["event_type"]
            if etype == "tool_call":
                txt_lines.append(f"[{ts}] 🔧 {sanitized['tool_name']} ({sanitized['agent']})")
            elif etype == "tool_result":
                txt_lines.append(f"[{ts}] 📋 {sanitized['tool_name']} — {sanitized['status']} ({sanitized['elapsed_ms']:.0f}ms)")
            elif etype == "message":
                txt_lines.append(f"[{ts}] 💬 {sanitized['role']} ({sanitized['agent']})")
            elif etype == "error":
                txt_lines.append(f"[{ts}] ❌ 错误 ({sanitized['agent']})")
            elif etype == "info":
                txt_lines.append(f"[{ts}] ℹ️ 信息 ({sanitized['agent']})")

        (self._result_dir / "execution.txt").write_text(
            "\n".join(txt_lines), encoding="utf-8"
        )

        return stats
