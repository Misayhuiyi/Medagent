"""统一执行工具入口：权限检查 + 日志记录 + 工具调用。

使用享元模式（Flyweight），同步/异步路径共享同一条验证+执行+日志管线。
异步 handler 在同步路径下通过 asyncio.run() 执行（仅在非事件循环上下文）。
"""

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

    # ── 共享执行管线 ──────────────────────────────────────────

    async def _execute(self, tool_name: str, tool_params: dict) -> str:
        """验证 → 日志 → 执行 → 日志 → nag 注入（共享管线）。"""
        # 1. 权限检查
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

        # 2. 调用日志
        if self._logger:
            self._logger.log_tool_call(tool_name, tool_params)

        # 3. 执行
        try:
            start = time.time()
            result = tool_def.handler(**tool_params)
            if asyncio.iscoroutine(result):
                result = await result
            elapsed_ms = (time.time() - start) * 1000
            if self._logger:
                self._logger.log_tool_result(tool_name, result, elapsed_ms)
            # 4. Nag 注入（skip for todo: update() 已重置计数器）
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

    # ── 公共 API ─────────────────────────────────────────────

    async def run_async(self, tool_name: str, tool_params: dict) -> str:
        """异步执行工具。"""
        return await self._execute(tool_name, tool_params)

    def run(self, tool_name: str, tool_params: dict) -> str:
        """同步执行工具。

        兼容两种场景：
        - 已在事件循环中：通过 run_coroutine_threadsafe 投递到事件循环
        - 不在事件循环中：通过 asyncio.run() 创建临时事件循环
        """
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._execute(tool_name, tool_params), loop
                )
                return future.result(timeout=30)
        except RuntimeError:
            pass
        return asyncio.run(self._execute(tool_name, tool_params))

    # ── LangChain 工具适配 ────────────────────────────────────

    def as_tool(self) -> ToolDef:
        """返回 ToolDef，handler 为 async 函数（兼容 LangGraph 异步调用）。"""
        async def _handler(tool_name: str = "", tool_params: dict | None = None) -> str:
            return await self.run_async(tool_name, tool_params or {})

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
            handler=_handler,
        )
