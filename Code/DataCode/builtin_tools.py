import logging
from pathlib import Path

from DataCode.tool_registry import ToolDef

logger = logging.getLogger(__name__)


READ_ALLOWED = ["TempData/", "Result/", "Data/skills/", "Data/agents/", "Data/memory/", "Data/"]
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


def create_batch_pdf_conversion_tool(project_root: str) -> ToolDef:
    """批量 PDF → MD 转换工具。一次调用完成目录下所有 PDF 的转换。
    
    替代逐文件 read/write 循环（每文件 2+ 轮），将 42+ 轮减少到 1 轮。
    """
    import json
    root = Path(project_root).resolve()

    def handler(dir_path: str) -> str:
        try:
            target = (root / dir_path).resolve()
            relative = target.relative_to(root)
        except ValueError:
            return json.dumps({"error": f"路径 '{dir_path}' 超出项目范围"}, ensure_ascii=False)
        
        if not target.is_dir():
            return json.dumps({"error": f"目录 '{dir_path}' 不存在"}, ensure_ascii=False)
        
        try:
            import fitz
        except ImportError:
            # 回退：pypdf2
            try:
                import PyPDF2
                return _convert_via_pypdf2(target)
            except ImportError:
                return json.dumps({"error": "pymupdf (fitz) 和 PyPDF2 均未安装"}, ensure_ascii=False)
        
        pdf_files = sorted(target.rglob("*.pdf"))
        if not pdf_files:
            return json.dumps({
                "totalFiles": 0, "successCount": 0, "failCount": 0,
                "mdFilePaths": [], "message": "No PDF files found"
            }, ensure_ascii=False)
        
        results = []
        success = 0
        failed = 0
        md_paths = []
        
        for pdf_path in pdf_files:
            try:
                doc = fitz.open(str(pdf_path))
                md_lines = []
                for page in doc:
                    text = page.get_text("text")
                    md_lines.append(text if text.strip() else f"[Page {page.number+1}: no extractable text]")
                md_content = "\n\n".join(md_lines)
                doc.close()
                
                md_path = pdf_path.with_suffix(".md")
                md_path.write_text(md_content, encoding="utf-8")
                
                rel_source = str(pdf_path.relative_to(target))
                rel_target = str(md_path.relative_to(target))
                
                results.append({
                    "sourceFile": rel_source,
                    "targetFile": rel_target,
                    "status": "success" if len(md_content) > 0 else "empty",
                    "method": "text",
                    "pageCount": len(md_lines),
                    "charCount": len(md_content),
                })
                success += 1
                md_paths.append(str(md_path))
            except Exception as e:
                results.append({
                    "sourceFile": str(pdf_path.relative_to(target)),
                    "status": "failed",
                    "error": str(e),
                })
                failed += 1
        
        report = {
            "totalFiles": len(pdf_files),
            "successCount": success,
            "failCount": failed,
            "mdFilePaths": md_paths,
            "conversionResults": results,
        }
        
        # 同时写 conversion_report.json 供后续步骤读取
        report_path = target / "conversion_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        
        return json.dumps(report, ensure_ascii=False)
    
    return ToolDef(
        name="batch_pdf_to_md",
        description=(
            "批量将目录下所有 PDF 文件转换为 Markdown 文件。"
            "一次调用处理全部 PDF，生成的 .md 文件保存在 PDF 同目录。"
            "输入 dir_path 为相对于项目根目录的路径（如 '本地患者库/张三_001/2026-01-15'）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "dir_path": {"type": "string", "description": "患者就诊时间目录（相对于项目根的路径）"},
            },
            "required": ["dir_path"],
        },
        source="builtin",
        handler=handler,
    )


def _convert_via_pypdf2(directory: Path) -> str:
    """PyPDF2 回退方案。"""
    import json
    pdf_files = sorted(directory.rglob("*.pdf"))
    success = 0
    failed = 0
    results = []
    
    for pdf_path in pdf_files:
        try:
            import PyPDF2
            with open(pdf_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                md_lines = []
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    md_lines.append(text if text.strip() else f"[Page {i+1}: no extractable text]")
            md_content = "\n\n".join(md_lines)
            md_path = pdf_path.with_suffix(".md")
            md_path.write_text(md_content, encoding="utf-8")
            results.append({"sourceFile": str(pdf_path.name), "status": "success"})
            success += 1
        except Exception as e:
            results.append({"sourceFile": str(pdf_path.name), "status": "failed", "error": str(e)})
            failed += 1
    
    return json.dumps({
        "totalFiles": len(pdf_files),
        "successCount": success,
        "failCount": failed,
        "conversionResults": results,
    }, ensure_ascii=False)


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


def create_rag_query_tool(knowledge_base) -> ToolDef:
    """创建 RAG 知识库查询工具 — 拦截 Skill 中 exec('rag_query.py') 调用，
    转为 KnowledgeBase.query() 语义检索。"""

    async def handler(query: str, top_k: int = 5, mode: str = "retrieve") -> str:
        import json
        try:
            results = await knowledge_base.query(question=query, top_k=top_k)
            return json.dumps(results, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    return ToolDef(
        name="rag_query",
        description="RAG 知识库语义检索，查询指南/文献/共识等权威医学资料",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索查询语句"},
                "top_k": {"type": "integer", "description": "返回结果数量，默认 5"},
                "mode": {"type": "string", "description": "检索模式，默认 retrieve"},
            },
            "required": ["query"],
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
