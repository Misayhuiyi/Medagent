from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from DataCode.tool_registry import ToolDef, ToolRegistry

if TYPE_CHECKING:
    from DataCode.execution_logger import ExecutionLogger


class ExecuteTool:
    """统一执行工具入口：权限检查 + 日志记录 + 工具调用。"""

    def __init__(
        self,
        registry: ToolRegistry,
        allowed_tools: list[str] | None = None,
        logger: ExecutionLogger | None = None,
        todo_manager=None,
    ):
        self._registry = registry
        self._allowed_tools = set(allowed_tools) if allowed_tools else None
        self._logger = logger
        self._todo_manager = todo_manager

    async def run_async(self, tool_name: str, tool_params: dict) -> str:
        """异步执行工具。"""
        if self._allowed_tools and tool_name not in self._allowed_tools:
            msg = f"Error: 工具 '{tool_name}' 不在允许列表中。"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

        tool_def = self._registry.get(tool_name)
        if tool_def is None:
            msg = f"Error: 工具 '{tool_name}' 未找到。"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

        if tool_def.handler is None:
            msg = f"Error: 工具 '{tool_name}' 没有可执行的处理函数。"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

        if self._logger:
            self._logger.log_tool_call(tool_name, tool_params)

        try:
            start = time.time()
            result = tool_def.handler(**tool_params)
            if asyncio.iscoroutine(result):
                result = await result
            elapsed_ms = (time.time() - start) * 1000
            if self._logger:
                self._logger.log_tool_result(tool_name, result, elapsed_ms)
            # Nag injection: skip for todo (update() already resets counter)
            if tool_name != "todo" and self._todo_manager:
                nag = self._todo_manager.tick_round()
                if nag:
                    result = f"{result}\n\n{nag}"
            return result
        except Exception as e:
            msg = f"Error: 执行工具 '{tool_name}' 失败 - {e}"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

    def run(self, tool_name: str, tool_params: dict) -> str:
        """同步执行工具。"""
        if self._allowed_tools and tool_name not in self._allowed_tools:
            msg = f"Error: 工具 '{tool_name}' 不在允许列表中。"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

        tool_def = self._registry.get(tool_name)
        if tool_def is None:
            msg = f"Error: 工具 '{tool_name}' 未找到。"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

        if tool_def.handler is None:
            msg = f"Error: 工具 '{tool_name}' 没有可执行的处理函数。"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

        if self._logger:
            self._logger.log_tool_call(tool_name, tool_params)

        try:
            start = time.time()
            result = tool_def.handler(**tool_params)
            elapsed_ms = (time.time() - start) * 1000
            if self._logger:
                self._logger.log_tool_result(tool_name, result, elapsed_ms)
            # Nag injection: skip for todo (update() already resets counter)
            if tool_name != "todo" and self._todo_manager:
                nag = self._todo_manager.tick_round()
                if nag:
                    result = f"{result}\n\n{nag}"
            return result
        except Exception as e:
            msg = f"Error: 执行工具 '{tool_name}' 失败 - {e}"
            if self._logger:
                self._logger.log_tool_result(tool_name, msg, 0)
            return msg

    def as_tool(self) -> ToolDef:
        return ToolDef(
            name="ExecuteTool",
            description="统一执行工具入口。先搜索工具，再通过此工具执行。",
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "要执行的工具名称",
                    },
                    "tool_params": {
                        "type": "object",
                        "description": "工具参数",
                    },
                },
                "required": ["tool_name"],
            },
            source="builtin",
            handler=lambda tool_name="", tool_params=None: self.run(
                tool_name, tool_params or {}
            ),
        )
