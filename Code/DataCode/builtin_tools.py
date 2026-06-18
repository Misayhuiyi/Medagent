from pathlib import Path

from DataCode.tool_registry import ToolDef


READ_ALLOWED = ["tempdata/", "Result/", "data/skills/", "data/agents/", "memory/", "data/"]
WRITE_ALLOWED = ["Result/"]

MAX_READ_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_WRITE_SIZE = 10 * 1024 * 1024  # 10 MB


def _resolve_and_check(path: str, allowed_prefixes: list[str], project_root: str) -> Path:
    """解析路径并检查白名单。返回规范化的绝对路径或 raise ValueError。"""
    root = Path(project_root).resolve()
    # 先规范化，处理 .. 和符号链接
    target = (root / path).resolve()
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise ValueError(f"路径 '{path}' 超出项目范围")

    rel_str = relative.as_posix() + "/"
    if not any(rel_str.startswith(prefix) for prefix in allowed_prefixes):
        raise ValueError(f"路径 '{path}' 不在允许的目录范围内")

    return target


def create_read_file_tool(project_root: str) -> ToolDef:
    """创建读取文件工具，路径白名单：Data/、TempData/、Result/。"""
    root = Path(project_root).resolve()

    def handler(path: str) -> str:
        try:
            target = _resolve_and_check(path, READ_ALLOWED, str(root))
        except ValueError as e:
            return f"Error: {e}"
        if not target.exists():
            return f"Error: 文件 '{path}' 不存在"
        if not target.is_file():
            return f"Error: '{path}' 不是文件"
        file_size = target.stat().st_size
        if file_size > MAX_READ_SIZE:
            return f"Error: 文件 '{path}' 太大 ({file_size} 字节)，超过限制 ({MAX_READ_SIZE} 字节)"
        return target.read_text(encoding="utf-8")

    return ToolDef(
        name="read_file",
        description="读取项目文件（允许 Data/、TempData/、Result/）",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根目录的文件路径"},
            },
            "required": ["path"],
        },
        source="builtin",
        handler=handler,
    )


def create_write_file_tool(project_root: str) -> ToolDef:
    """创建写入文件工具，路径白名单：仅 Result/。"""
    root = Path(project_root).resolve()

    def handler(path: str, content: str) -> str:
        try:
            target = _resolve_and_check(path, WRITE_ALLOWED, str(root))
        except ValueError as e:
            return f"Error: {e}"
        content_size = len(content.encode("utf-8"))
        if content_size > MAX_WRITE_SIZE:
            return f"Error: 写入内容太大 ({content_size} 字节)，超过限制 ({MAX_WRITE_SIZE} 字节)"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"成功写入 {path} ({len(content)} 字符)"

    return ToolDef(
        name="write_file",
        description="写入文件到 Result/ 目录",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对项目根目录的文件路径（仅 Result/ 下）"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        },
        source="builtin",
        handler=handler,
    )


def create_save_memory_tool(memory_store) -> ToolDef:
    """创建保存记忆工具：LLM 可主动将重要信息写入长期记忆。"""

    def handler(content: str, mode: str = "append") -> str:
        if mode == "overwrite":
            memory_store.write_long_term(content)
        else:
            memory_store.append_long_term(content)
        return f"已保存到长期记忆（{len(content)} 字符）"

    return ToolDef(
        name="save_memory",
        description="保存重要信息到长期记忆文件，供后续对话使用",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要保存的记忆内容"},
                "mode": {
                    "type": "string",
                    "enum": ["append", "overwrite"],
                    "description": "append=追加到末尾, overwrite=覆盖全部",
                },
            },
            "required": ["content"],
        },
        source="builtin",
        handler=handler,
    )


def create_read_memory_tool(memory_store) -> ToolDef:
    """创建读取记忆工具：LLM 可读取长期记忆文件内容。"""

    def handler() -> str:
        content = memory_store.read_long_term()
        return content if content else "（无长期记忆）"

    return ToolDef(
        name="read_memory",
        description="读取长期记忆文件，获取之前保存的重要信息",
        parameters={
            "type": "object",
            "properties": {},
        },
        source="builtin",
        handler=handler,
    )


def create_todo_tool(todo_manager, logger=None) -> ToolDef:
    """创建待办列表工具：模型通过此工具管理多步任务进度。"""

    def handler(items: list[dict]) -> str:
        try:
            result = todo_manager.update(items)
        except ValueError as e:
            return f"Error: {e}"
        summary = todo_manager.summary()
        print(f"Todo: {summary}")
        if logger:
            logger.log("info", "", message=f"Todo updated: {summary}")
        return result

    return ToolDef(
        name="todo",
        description=(
            "管理你的待办事项列表。在开始多步任务前先列出所有步骤，"
            "完成每步后更新状态。同一时间只能有一个 in_progress。"
            "items: [{id: str, text: str, status: str}]"
        ),
        parameters={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "步骤唯一标识"},
                            "text": {"type": "string", "description": "步骤描述"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "步骤状态",
                            },
                        },
                        "required": ["id", "text", "status"],
                    },
                },
            },
            "required": ["items"],
        },
        source="builtin",
        handler=handler,
    )
