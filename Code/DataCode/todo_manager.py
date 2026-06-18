"""TodoManager: 带状态的待办列表管理器，支持 nag reminder。"""
from __future__ import annotations

from dataclasses import dataclass

VALID_STATUSES = {"pending", "in_progress", "completed"}

STATUS_ICONS = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
}


@dataclass
class TodoItem:
    id: str
    text: str
    status: str = "pending"


class TodoManager:
    """管理带状态的待办列表。同一时间只允许一个 in_progress。

    支持 nag reminder：连续 N 轮未调用 update 时返回提醒文本。
    """

    def __init__(self, nag_threshold: int = 3):
        self.items: list[TodoItem] = []
        self._rounds_since_todo: int = 0
        self._nag_threshold = nag_threshold

    def update(self, items: list[dict]) -> str:
        """接收模型输出的 todo 列表，验证并更新内部状态。返回渲染文本。"""
        validated: list[TodoItem] = []
        in_progress_count = 0
        for item in items:
            status = item.get("status", "pending")
            if status not in VALID_STATUSES:
                raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_STATUSES}")
            if status == "in_progress":
                in_progress_count += 1
            validated.append(TodoItem(id=item["id"], text=item["text"], status=status))
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        self._rounds_since_todo = 0
        return self.render()

    def tick_round(self) -> str | None:
        """每轮非 todo 工具调用后调用。返回 nag 文本或 None。"""
        self._rounds_since_todo += 1
        if self._rounds_since_todo >= self._nag_threshold and self.items:
            return "<reminder>Update your todos.</reminder>"
        return None

    def render(self) -> str:
        """渲染当前 todo 状态为可读文本。"""
        if not self.items:
            return "(no todos)"
        lines = []
        for item in self.items:
            icon = STATUS_ICONS.get(item.status, "[ ]")
            lines.append(f"{icon} {item.text}")
        return "\n".join(lines)

    def summary(self) -> str:
        """简短摘要：N/M done | [>] current。"""
        total = len(self.items)
        done = sum(1 for i in self.items if i.status == "completed")
        current = next((i for i in self.items if i.status == "in_progress"), None)
        base = f"{done}/{total} done"
        if current:
            return f"{base} | [>] {current.text}"
        return base
