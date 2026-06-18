from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_SESSION_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_[A-Za-z0-9]{6}$")
MEMORY_ALLOWED_PREFIXES = ["Data/memory", "TempData/memory", "data/memory", "tempdata/memory", "memory"]


def _validate_memory_path(path: str) -> None:
    """验证内存路径前缀在允许列表中（滑动窗口子串匹配）。"""
    normalized = Path(path).as_posix()
    for prefix in MEMORY_ALLOWED_PREFIXES:
        # Check if normalized path starts with or contains the allowed prefix
        if normalized.startswith(prefix) or f"/{prefix}" in f"/{normalized}":
            return
        # Also handle Windows-style backslash paths
        if "\\" in path:
            win_normalized = path.replace("\\", "/")
            if win_normalized.startswith(prefix) or f"/{prefix}" in f"/{win_normalized}":
                return
    # On Windows, also check the raw path
    for prefix in MEMORY_ALLOWED_PREFIXES:
        if prefix in normalized or prefix.replace("/", "\\") in path:
            return
    raise ValueError(f"Memory path not allowed: {path}. Must be under {MEMORY_ALLOWED_PREFIXES}")


class MemoryStore:
    """会话内上下文卸载存储：短期记忆（内存）+ 长期记忆（文件 dump）。"""

    def __init__(self, long_term_path: str, session_id: str = "",
                 max_short_term: int = 50, offload_threshold: int = 100000):
        if session_id and not _SESSION_ID_RE.match(session_id):
            raise ValueError(f"Invalid session_id format: {session_id}")
        _validate_memory_path(long_term_path)
        self._long_term_path = Path(long_term_path) / session_id if session_id else Path(long_term_path)
        self._session_id = session_id
        self._max_short_term = max_short_term
        self._offload_threshold = offload_threshold
        self._short_term: list[dict] = []

    # ── 短期记忆 ──────────────────────────────────────────────

    def add_short_term(self, role: str, content: str) -> None:
        """添加一条短期记忆，超出上限时自动淘汰最早的消息。"""
        self._short_term.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        if len(self._short_term) > self._max_short_term:
            self._short_term = self._short_term[-self._max_short_term:]

    def get_short_term(self) -> list[dict]:
        """返回短期记忆的浅拷贝。"""
        return list(self._short_term)

    def clear_short_term(self, indices: list[int] | None = None) -> None:
        """清除短期记忆。indices 为 None 时清空全部，否则仅删除指定索引。"""
        if indices is None:
            self._short_term.clear()
        else:
            remove_set = set(indices)
            self._short_term = [
                m for i, m in enumerate(self._short_term) if i not in remove_set
            ]

    def should_offload(self, current_token_count: int) -> bool:
        """判断是否需要将短期记忆卸载到文件。"""
        return current_token_count > self._offload_threshold

    # ── 文件卸载 ──────────────────────────────────────────────

    def dump_to_file(self) -> Path:
        """将短期记忆序列化写入文件（原子写入）。"""
        self._long_term_path.mkdir(parents=True, exist_ok=True)
        dump_path = self._long_term_path / "memory_dump.json"
        data = {
            "session_id": self._session_id,
            "dumped_at": datetime.now().isoformat(),
            "entries": self._short_term,
        }
        tmp_path = dump_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp_path), str(dump_path))
        return dump_path

    def load_from_file(self) -> list[dict]:
        """从文件按需加载历史上下文。"""
        dump_path = self._long_term_path / "memory_dump.json"
        if not dump_path.exists():
            return []
        data = json.loads(dump_path.read_text(encoding="utf-8"))
        return data.get("entries", [])

    # ── 长期记忆（兼容旧接口）──────────────────────────────────

    def read_long_term(self) -> str:
        """读取长期记忆文件，不存在时返回空字符串。"""
        memory_file = self._long_term_path / "MEMORY.md"
        if memory_file.exists():
            return memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """覆写长期记忆文件。"""
        self._long_term_path.mkdir(parents=True, exist_ok=True)
        memory_file = self._long_term_path / "MEMORY.md"
        memory_file.write_text(content, encoding="utf-8")

    def append_long_term(self, content: str) -> None:
        """追加内容到长期记忆文件末尾。"""
        existing = self.read_long_term()
        if existing and not existing.endswith("\n"):
            existing += "\n"
        self.write_long_term(existing + content)

    # ── 工厂方法 ──────────────────────────────────────────────

    @classmethod
    def from_config(cls, config_manager, session_id: str = "") -> MemoryStore:
        """从 ConfigManager 实例构建 MemoryStore。"""
        return cls(
            long_term_path=config_manager.get(
                "memory.long_term_path", "Data/memory"
            ),
            session_id=session_id,
            max_short_term=config_manager.get("memory.max_short_term", 50),
            offload_threshold=config_manager.get("memory.offload_threshold", 100000),
        )
