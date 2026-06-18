"""ContextManager: token 用量监控 + 压缩策略（软压缩/硬压缩）。"""
from __future__ import annotations

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from DataCode.config_manager import ConfigManager


class ContextManager:
    """监控对话 token 用量，在达到阈值时触发压缩。

    - ok: 正常，不做任何事
    - summary_compress: 软压缩，让 LLM 生成摘要替换早期对话
    - force_compress: 硬压缩，只保留最近 N 轮 + 摘要
    """

    def __init__(
        self,
        config: dict,
        count_tokens_fn: Callable[[list], int],
        max_tokens: int = 0,
    ):
        self._summary_threshold = config.get("summary_threshold", 0.7)
        self._force_threshold = config.get("force_threshold", 0.9)
        self._keep_recent_turns = config.get("keep_recent_turns", 5)
        self._count_tokens = count_tokens_fn
        self._max_tokens = max_tokens

    @classmethod
    def from_config(cls, config_manager: ConfigManager, count_tokens_fn: Callable[[list], int]) -> ContextManager:
        """从 ConfigManager 构建。"""
        return cls(
            config={
                "summary_threshold": config_manager.get("context.summary_threshold", 0.7),
                "force_threshold": config_manager.get("context.force_threshold", 0.9),
                "keep_recent_turns": config_manager.get("context.keep_recent_turns", 5),
            },
            count_tokens_fn=count_tokens_fn,
            max_tokens=config_manager.get("llm.context_length", 200000),
        )

    def set_context_length(self, length: int) -> None:
        self._max_tokens = length

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def check(self, messages: list) -> str:
        """检查当前 token 用量，返回压缩建议。"""
        if self._max_tokens == 0:
            return "ok"
        current = self._count_tokens(messages)
        ratio = current / self._max_tokens
        if ratio >= self._force_threshold:
            return "force_compress"
        if ratio >= self._summary_threshold:
            return "summary_compress"
        return "ok"

    def compress_force(self, messages: list) -> list:
        """硬压缩：保留系统提示 + 最近 N 轮对话。"""
        system_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
        non_system = [m for m in messages if not (isinstance(m, dict) and m.get("role") == "system")]
        keep_count = self._keep_recent_turns * 2
        return system_msgs + non_system[-keep_count:]

    def compress_summary(self, messages: list, summary: str) -> list:
        """软压缩：用摘要替换早期对话，保留最近 N 轮。"""
        summary_msg = {"role": "system", "content": f"对话摘要:\n{summary}"}
        system_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
        non_system = [m for m in messages if not (isinstance(m, dict) and m.get("role") == "system")]
        keep_count = self._keep_recent_turns * 2
        recent = non_system[-keep_count:]
        return system_msgs + [summary_msg] + recent
