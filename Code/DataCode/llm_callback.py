"""LLM 调用追踪：LangChain BaseCallbackHandler + 内存环形缓冲。

每一次 ChatOpenAI 实际调用都会被记录：
  - 调用方 (agent_name / skill_name)
  - 模型 / base_url / api_key 后 4 位
  - 输入 prompt 长度（字符数）+ 摘要（前 N 字符）
  - 输出长度 + 摘要
  - 起止时间、延迟
  - 错误（脱敏）

外部通过 LLMCallTracker.recent() 拿到最近 N 条记录用于 /api/debug/llm。
日志同时写入 Result/logs/llm.log。
"""

from __future__ import annotations

import re
import time
import uuid
from collections import deque
from threading import Lock
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler

from DataCode.log_setup import get_llm_logger

_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{6,}")


def _sanitize(text: str) -> str:
    if not text:
        return text
    return _API_KEY_PATTERN.sub("sk-***", text)


def _short(text: str, limit: int = 200) -> str:
    text = _sanitize(text or "")
    text = text.replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[:limit] + f"…(+{len(text) - limit}字)"


def _key_tail(api_key: str) -> str:
    if not api_key:
        return ""
    return f"****{api_key[-4:]}" if len(api_key) >= 4 else "****"


class LLMCallTracker:
    """全局 LLM 调用记录器（进程内单例使用）。"""

    _instance: "LLMCallTracker | None" = None

    def __init__(self, max_records: int = 200):
        self._records: deque[dict] = deque(maxlen=max_records)
        self._inflight: dict[str, dict] = {}
        self._lock = Lock()
        self._logger = get_llm_logger()

    @classmethod
    def instance(cls) -> "LLMCallTracker":
        if cls._instance is None:
            cls._instance = LLMCallTracker()
        return cls._instance

    # ── 调用入口（手工调用，对应 ChatOpenAI 之外的环节也可以记录） ──

    def start(self, *, agent: str, model: str, base_url: str, api_key: str,
              prompt: str, kind: str = "chat") -> str:
        call_id = uuid.uuid4().hex[:12]
        record = {
            "id": call_id,
            "agent": agent,
            "kind": kind,
            "model": model,
            "base_url": base_url,
            "api_key_tail": _key_tail(api_key),
            "prompt_chars": len(prompt or ""),
            "prompt_preview": _short(prompt, 400),
            "started_at": time.time(),
            "status": "running",
        }
        with self._lock:
            self._inflight[call_id] = record
        self._logger.info(
            "LLM start id=%s agent=%s kind=%s model=%s base_url=%s key=%s prompt_chars=%d",
            call_id, agent, kind, model, base_url, record["api_key_tail"], record["prompt_chars"],
        )
        self._logger.debug("LLM start id=%s prompt=%s", call_id, record["prompt_preview"])
        return call_id

    def succeed(self, call_id: str, response_text: str) -> None:
        with self._lock:
            record = self._inflight.pop(call_id, None)
        if record is None:
            return
        record.update({
            "status": "success",
            "response_chars": len(response_text or ""),
            "response_preview": _short(response_text, 400),
            "ended_at": time.time(),
            "latency_s": round(time.time() - record["started_at"], 3),
        })
        with self._lock:
            self._records.append(record)
        self._logger.info(
            "LLM ok    id=%s agent=%s latency=%.3fs response_chars=%d",
            call_id, record["agent"], record["latency_s"], record["response_chars"],
        )
        self._logger.debug("LLM ok id=%s response=%s", call_id, record["response_preview"])

    def fail(self, call_id: str, error: BaseException) -> None:
        with self._lock:
            record = self._inflight.pop(call_id, None)
        if record is None:
            return
        record.update({
            "status": "error",
            "error_type": type(error).__name__,
            "error_message": _sanitize(str(error))[:500],
            "ended_at": time.time(),
            "latency_s": round(time.time() - record["started_at"], 3),
        })
        with self._lock:
            self._records.append(record)
        self._logger.warning(
            "LLM err   id=%s agent=%s latency=%.3fs error=%s msg=%s",
            call_id, record["agent"], record["latency_s"],
            record["error_type"], record["error_message"],
        )

    def recent(self, limit: int = 30) -> list[dict]:
        with self._lock:
            data = list(self._records)
        return data[-limit:][::-1]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._inflight.clear()


class LLMCallbackHandler(BaseCallbackHandler):
    """LangChain 回调，挂在 ChatOpenAI 上自动记录。"""

    def __init__(self, agent_name: str, model: str, base_url: str, api_key: str):
        super().__init__()
        self._agent = agent_name or "unknown"
        self._model = model or ""
        self._base_url = base_url or ""
        self._api_key = api_key or ""
        self._tracker = LLMCallTracker.instance()
        self._run_to_call: dict[str, str] = {}

    def _prompt_text(self, messages: list[Any] | None, prompts: list[str] | None) -> str:
        if prompts:
            return "\n---\n".join(prompts)
        if messages:
            parts: list[str] = []
            for batch in messages:
                if isinstance(batch, list):
                    for m in batch:
                        content = getattr(m, "content", None)
                        if content is None and isinstance(m, dict):
                            content = m.get("content", "")
                        parts.append(str(content or ""))
            return "\n---\n".join(parts)
        return ""

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        prompt = self._prompt_text(messages, None)
        call_id = self._tracker.start(
            agent=self._agent, model=self._model, base_url=self._base_url,
            api_key=self._api_key, prompt=prompt, kind="chat",
        )
        self._run_to_call[str(run_id)] = call_id

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        prompt = self._prompt_text(None, prompts)
        call_id = self._tracker.start(
            agent=self._agent, model=self._model, base_url=self._base_url,
            api_key=self._api_key, prompt=prompt, kind="completion",
        )
        self._run_to_call[str(run_id)] = call_id

    def on_llm_end(self, response, *, run_id, **kwargs):
        call_id = self._run_to_call.pop(str(run_id), None)
        if not call_id:
            return
        text_parts: list[str] = []
        try:
            for gens in getattr(response, "generations", []) or []:
                for gen in gens or []:
                    text = getattr(gen, "text", "") or ""
                    if not text:
                        msg = getattr(gen, "message", None)
                        if msg is not None:
                            text = str(getattr(msg, "content", "") or "")
                    text_parts.append(text)
        except Exception:
            pass
        self._tracker.succeed(call_id, "\n".join(text_parts))

    def on_llm_error(self, error, *, run_id, **kwargs):
        call_id = self._run_to_call.pop(str(run_id), None)
        if not call_id:
            return
        self._tracker.fail(call_id, error)
