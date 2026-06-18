"""MCPConnector：通过 streamable_http 连接外部 MCP 服务器，懒加载工具。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from DataCode.config_manager import ConfigManager
from DataCode.tool_registry import ToolDef, ToolRegistry

logger = logging.getLogger(__name__)


class MCPConnector:
    """MCP 服务器连接器。

    - index_all(): 连接所有 enabled 服务器，收集工具名+描述到索引字典
    - load_tool(): 按需加载完整工具定义，创建 handler 闭包，注册到 ToolRegistry
    - call_tool(): 调用 MCP 工具
    """

    def __init__(self, config: ConfigManager):
        self._config = config
        self._servers: dict[str, dict[str, Any]] = {}  # server_name -> config dict
        self._tool_index: dict[tuple[str, str], dict] = {}  # (server, tool_name) -> schema
        self._sessions: dict[str, Any] = {}  # server_name -> client session
        self._connected: dict[str, bool] = {}

        servers = config.get("mcp.servers", {})
        if isinstance(servers, dict):
            for name, srv_conf in servers.items():
                if srv_conf.get("enabled", True):
                    self._servers[name] = srv_conf

    @property
    def servers(self) -> dict[str, dict[str, Any]]:
        return self._servers

    def get_server_status(self, name: str) -> str:
        if name not in self._servers:
            return "unknown"
        if self._connected.get(name):
            return "connected"
        return "disconnected"

    def list_indexed_tools(self, server_name: str) -> list[dict]:
        """返回指定服务器的索引工具列表。"""
        return [
            {"name": tn, "description": schema.get("description", "")}
            for (sn, tn), schema in self._tool_index.items()
            if sn == server_name
        ]

    async def connect_server(self, name: str) -> list[dict]:
        """连接单个 MCP 服务器并索引工具。"""
        if name not in self._servers:
            raise ValueError(f"Unknown MCP server: {name}")

        srv = self._servers[name]
        url = srv.get("url", "")
        headers = srv.get("headers")

        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        cm = streamablehttp_client(url, headers=headers)
        read_stream, write_stream, _ = await cm.__aenter__()
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()

        self._sessions[name] = {"session": session, "cm": cm}
        self._connected[name] = True

        # 索引工具
        result = await session.list_tools()
        indexed = []
        for tool in result.tools:
            schema = {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema or {"type": "object", "properties": {}},
            }
            self._tool_index[(name, tool.name)] = schema
            indexed.append(schema)

        return indexed

    async def index_all(self) -> dict[str, list[dict]]:
        """连接所有 enabled 服务器并索引工具。"""
        results = {}
        for name in list(self._servers.keys()):
            try:
                tools = await self.connect_server(name)
                results[name] = tools
            except Exception:
                results[name] = []
        return results

    async def load_tool(self, server_name: str, tool_name: str, registry: ToolRegistry) -> ToolDef:
        """按需加载工具定义并注册到 ToolRegistry。"""
        key = (server_name, tool_name)
        if key not in self._tool_index:
            raise ValueError(f"Tool {tool_name} not indexed on server {server_name}")

        schema = self._tool_index[key]

        async def _handler(**kwargs):
            return await self.call_tool(server_name, tool_name, kwargs)

        def _sync_handler(**kwargs):
            return asyncio.get_event_loop().run_until_complete(
                self.call_tool(server_name, tool_name, kwargs)
            )

        tool_def = ToolDef(
            name=tool_name,
            description=schema.get("description", ""),
            parameters=schema.get("inputSchema", {"type": "object", "properties": {}}),
            source="mcp",
            handler=_sync_handler,
        )
        registry.register(tool_def)
        return tool_def

    async def call_tool(self, server_name: str, tool_name: str, args: dict) -> str:
        """调用 MCP 工具。"""
        entry = self._sessions.get(server_name)
        if entry is None:
            return f"Error: Server '{server_name}' not connected"
        session = entry["session"] if isinstance(entry, dict) else entry

        try:
            start = time.time()
            result = await session.call_tool(tool_name, args)
            elapsed_ms = (time.time() - start) * 1000

            if result.content:
                parts = []
                for c in result.content:
                    if hasattr(c, "text"):
                        parts.append(c.text)
                    else:
                        parts.append(str(c))
                return "\n".join(parts)
            return ""
        except Exception as e:
            logger.exception("MCP tool call failed: %s/%s", server_name, tool_name)
            return f"Error: 调用 MCP 工具 {tool_name} 失败"

    async def disconnect_server(self, name: str) -> None:
        """断开指定服务器。"""
        entry = self._sessions.pop(name, None)
        if entry:
            session = entry["session"] if isinstance(entry, dict) else entry
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass
            cm = entry.get("cm") if isinstance(entry, dict) else None
            if cm:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
        self._connected.pop(name, None)
        # 清理索引
        keys_to_remove = [(sn, tn) for sn, tn in self._tool_index if sn == name]
        for key in keys_to_remove:
            del self._tool_index[key]

    async def disconnect_all(self) -> None:
        """断开所有服务器。"""
        for name in list(self._sessions.keys()):
            await self.disconnect_server(name)
