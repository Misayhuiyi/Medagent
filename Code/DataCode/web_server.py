"""FastAPI Web 服务入口：组装路由和依赖。"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from DataCode._shared import load_env, build_llm_candidates
from DataCode.log_setup import setup_logging

logger = logging.getLogger(__name__)

# 全局 app state，供路由模块访问
_app_state: dict = {}


def _load_env_file(project_root: str) -> None:
    """加载 .env 环境变量（委派到共享模块）。"""
    load_env(project_root)


def _build_llm_candidates(config) -> list[dict]:
    """构建 LLM 候选列表（委派到共享模块）。"""
    return build_llm_candidates(config)


def _init_skill_executor(project_root: str) -> None:
    """初始化 SkillExecutor 并注册到 _app_state。"""
    from DataCode.config_manager import ConfigManager
    from DataCode.tool_registry import ToolRegistry
    from DataCode.builtin_tools import (
        create_read_file_tool, create_write_file_tool,
        create_save_memory_tool, create_read_memory_tool,
        create_todo_tool, create_batch_pdf_conversion_tool,
    )
    from DataCode.todo_manager import TodoManager
    from DataCode.memory_store import MemoryStore
    from DataCode.agent_manager import AgentManager
    from DataCode.knowledge_base import RagKnowledgeBase
    from DataCode.skill_executor import SkillExecutor

    root = Path(project_root)
    config = ConfigManager(str(root / "Data" / "platform.yaml"), str(root / "Data" / "agents"))
    config.load()

    # 支持多种 API Key 环境变量名，并按常见供应商自动补齐 base_url/model
    llm = config._platform.setdefault("llm", {})
    llm_candidates = _build_llm_candidates(config)
    if llm_candidates:
        first_llm = llm_candidates[0]
        llm["api_key"] = first_llm["api_key"]
        llm["base_url"] = first_llm["base_url"]
        llm["default_model"] = first_llm["model"]

    errors = config.validate()
    if errors:
        logger.warning("Config validation warnings: %s", errors)

    registry = ToolRegistry()
    registry.register(create_read_file_tool(project_root))
    registry.register(create_write_file_tool(project_root))

    from datetime import datetime
    import secrets
    session_id = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{secrets.token_hex(3)}"
    memory = MemoryStore(
        long_term_path=str(root / "Data" / "memory"),
        session_id=session_id,
    )
    registry.register(create_save_memory_tool(memory))
    registry.register(create_read_memory_tool(memory))

    todo_mgr = TodoManager()
    registry.register(create_todo_tool(todo_mgr))
    registry.register(create_batch_pdf_conversion_tool(project_root))

    manager = AgentManager(config=config, registry=registry, memory=memory)

    # 上下文管理：监控 token 用量，防止 ReAct Agent 递归中消息膨胀
    from DataCode.context_manager import ContextManager

    def _count_tokens(messages: list) -> int:
        """混合中英文 token 估算：中文 ~0.5 token/字，英文 ~0.25 token/字。"""
        total = 0
        for m in messages:
            text = ""
            if hasattr(m, "content"):
                text = str(m.content)
            elif isinstance(m, dict):
                text = str(m.get("content", ""))
            # 粗略估算：英文/数字/符号 ≈ 0.25 token/char，中文 ≈ 0.5 token/char
            cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
            en = len(text) - cn
            total += int(cn * 0.5 + en * 0.25)
        return total

    context_mgr = ContextManager.from_config(config, _count_tokens)
    manager._context_manager = context_mgr

    kb = RagKnowledgeBase(str(root / "Data" / "knowledge_base"))

    # 注册 RAG 查询工具（Agent 可通过此工具检索知识库）
    from DataCode.builtin_tools import create_rag_query_tool
    registry.register(create_rag_query_tool(kb))

    executor = SkillExecutor(agent_manager=manager, knowledge_base=kb, llm_candidates=llm_candidates)
    loaded = executor.load_skills(str(root / "Data" / "skills"))
    logger.info("Loaded skills: %s", loaded)

    # 加载流水线配置（从 data/skills/pipeline.yaml）
    executor.load_pipeline(str(root / "Data" / "skills" / "pipeline.yaml"))
    logger.info("Pipeline steps: %s", [s.name for s in executor.pipeline_steps])

    _app_state["skill_executor"] = executor
    _app_state["config"] = config
    _app_state["knowledge_base"] = kb

    # 后台预热知识库和文本清洗器（避免首次调用 2-5s 延迟）
    try:
        import asyncio
        asyncio.create_task(kb.warmup())
        from DataCode.text_cleaner import TextCleaner
        TextCleaner.warmup()
    except Exception:
        pass


def create_app(
    patients_dir: str = "TempData/patients",
    skills_dir: str = "Data/skills",
    knowledge_dir: str = "Data/knowledge_base",
    reports_dir: str = "Result",
    memory_dir: str = "memory",
    project_root: str | None = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    app = FastAPI(title="MedAgent Demo", version="0.1.0")

    # CORS：开发阶段允许所有来源。生产环境应通过 ALLOWED_ORIGINS 环境变量限制。
    # 注意：通配符来源 "*" 不能与 allow_credentials=True 同时使用——浏览器会拒绝
    # "Access-Control-Allow-Origin: *" 与凭证共存的响应。本服务前端与后端同源
    # （生产为静态挂载、开发走 Vite 代理），不依赖跨域 Cookie，因此关闭 credentials
    # 让通配符来源真正生效。
    allowed_origins_str = os.environ.get("ALLOWED_ORIGINS", "*")
    allowed_origins = [o.strip() for o in allowed_origins_str.split(",") if o.strip()] if allowed_origins_str != "*" else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allowed_origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 解析项目根目录
    if project_root is None:
        import sys
        # PYTHONPATH=Code 时，从工作目录推算
        project_root = str(Path.cwd())

    setup_logging(project_root)

    @app.middleware("http")
    async def _log_request(request: Request, call_next):
        started = time.time()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.time() - started) * 1000
            logger.exception(
                "HTTP %s %s -> EXC in %.1fms",
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise
        elapsed_ms = (time.time() - started) * 1000
        logger.info(
            "HTTP %s %s -> %d in %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    # 初始化 app state
    _load_env_file(project_root)
    _app_state["patients_dir"] = str(Path(patients_dir).resolve())
    _app_state["skills_dir"] = str(Path(skills_dir).resolve())
    _app_state["knowledge_dir"] = str(Path(knowledge_dir).resolve())
    _app_state["reports_dir"] = str(Path(reports_dir).resolve())
    _app_state["memory_dir"] = str(Path(memory_dir).resolve())
    _app_state["project_root"] = project_root

    # 注册路由
    from DataCode.web_routes.patients import router as patients_router
    app.include_router(patients_router)

    try:
        from DataCode.web_routes.chat import router as chat_router
        app.include_router(chat_router)
    except ImportError:
        pass
    try:
        from DataCode.web_routes.reports import router as reports_router
        app.include_router(reports_router)
    except ImportError:
        pass
    try:
        from DataCode.web_routes.debug import router as debug_router
        app.include_router(debug_router)
    except ImportError:
        pass
    try:
        from DataCode.web_routes.kb import router as kb_router
        app.include_router(kb_router)
    except ImportError:
        pass

    # 同步初始化 SkillExecutor（不依赖 startup 事件，避免 --reload 进程隔离问题）
    # 但如果外部（如 main.py）已初始化过，则跳过
    if "skill_executor" not in _app_state:
        _init_skill_executor(project_root)

    frontend_dist = Path(project_root) / "frontend_static"
    if not frontend_dist.exists():
        # 兼容旧 React 构建产物作为后备
        frontend_dist = Path(project_root) / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


# uvicorn 入口：仅在直接运行本文件时创建 app
# 正常使用请通过 Code/main.py web 模式启动
if __name__ == "__main__":
    app = create_app()
