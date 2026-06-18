from dataclasses import dataclass, field
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


def _json_type_to_python(prop: dict) -> type:
    json_type = prop.get("type", "string")
    return {"string": str, "integer": int, "number": float, "boolean": bool, "array": list, "object": dict}.get(json_type, str)


def _json_schema_to_pydantic(schema: dict, model_name: str = "Args") -> type:
    from pydantic import Field, create_model

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = {}
    for pname, pdef in properties.items():
        ptype = _json_type_to_python(pdef)
        desc = pdef.get("description", "")
        if pname in required:
            fields[pname] = (ptype, Field(description=desc))
        else:
            fields[pname] = (ptype, Field(default=None, description=desc))
    return create_model(model_name, **fields)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    source: str  # "builtin", "platform", "skill", "mcp"
    handler: Callable | None = None

    def to_langchain_tool(self):
        if self.handler is None:
            raise ValueError(f"Tool '{self.name}' has no handler, cannot convert to langchain tool")
        from langchain_core.tools import StructuredTool

        args_model = _json_schema_to_pydantic(self.parameters, f"{self.name}Args")
        return StructuredTool.from_function(
            name=self.name,
            description=self.description,
            func=self.handler,
            args_schema=args_model,
        )


class ToolRegistry:
    """工具注册中心：注册、查找、搜索工具定义。"""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        if tool.name in self._tools:
            logger.warning("Tool '%s' already registered, overwriting", tool.name)
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolDef]:
        return list(self._tools.values())

    def search(self, query: str) -> list[ToolDef]:
        query_lower = query.lower()
        return [
            t for t in self._tools.values()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]


def create_tool_search_tool(registry: ToolRegistry) -> ToolDef:
    """创建工具搜索工具：搜索已注册的工具。"""

    def handler(query: str = "") -> str:
        tools = registry.search(query) if query else registry.list_all()
        if not tools:
            return "没有找到匹配的工具。"
        lines = []
        for t in tools:
            lines.append(f"- {t.name}: {t.description}")
        return "可用工具:\n" + "\n".join(lines)

    return ToolDef(
        name="ToolSearch",
        description="搜索可用工具，返回名称和描述",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，空字符串返回全部"},
            },
        },
        source="builtin",
        handler=handler,
    )


def create_skill_search_tool(registry: ToolRegistry) -> ToolDef:
    """创建技能搜索工具：只搜索 source=skill 的工具。"""

    def handler(query: str = "") -> str:
        skills = [t for t in registry.list_all() if t.source == "skill"]
        if query:
            query_lower = query.lower()
            skills = [
                s for s in skills
                if query_lower in s.name.lower() or query_lower in s.description.lower()
            ]
        if not skills:
            return "没有找到匹配的技能。"
        lines = [f"- {s.name}: {s.description}" for s in skills]
        return "可用技能:\n" + "\n".join(lines)

    return ToolDef(
        name="SkillSearch",
        description="搜索可用技能",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，空字符串返回全部"},
            },
        },
        source="builtin",
        handler=handler,
    )
