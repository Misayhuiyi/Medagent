"""FastAPI Web 服务入口：组装路由和依赖。"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from DataCode.log_setup import setup_logging

logger = logging.getLogger(__name__)

# 全局 app state，供路由模块访问
_app_state: dict = {}


def _load_env_file(project_root: str) -> None:
    env_path = Path(project_root) / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        lower_value = value.lower()
        if not key or not value or "xxx" in lower_value or "your-api-key" in lower_value:
            continue
        os.environ.setdefault(key, value)


def _build_llm_candidates(config) -> list[dict]:
    def valid_env(name: str) -> str:
        value = os.environ.get(name, "").strip()
        lower_value = value.lower()
        if not value or "xxx" in lower_value or "your-api-key" in lower_value:
            return ""
        return value

    llm = config._platform.setdefault("llm", {})
    platform_base_url = str(llm.get("base_url", "") or "").strip()
    platform_model = str(llm.get("default_model", "") or "").strip()
    candidates = []

    def add_candidate(name: str, api_key: str, base_url: str, model: str) -> None:
        if not api_key or not base_url or not model:
            return
        signature = (name, base_url, model)
        if any((item["name"], item["base_url"], item["model"]) == signature for item in candidates):
            return
        candidates.append({"name": name, "api_key": api_key, "base_url": base_url, "model": model})

    def add_provider(provider: str, api_key: str, public_host: str,
                     public_base_url: str, public_model: str) -> None:
        """为某供应商的 key 生成候选。

        关键约束：一个 key 只应指向它真正归属的 endpoint。
        - 若平台 base_url 已配置且不是该供应商的公网域名，则把该 key 作为
          “平台网关候选”(PLATFORM_*)，因为平台 base_url（如 opencode.ai 网关）
          可能就是这个 key 的真实归属地。
        - 仅当用户显式提供了该供应商的 *_BASE_URL（说明确实要直连公网 endpoint），
          或根本没有平台网关候选时，才追加公网 endpoint 候选。
          否则用同一个网关 key 去请求公网官方域名必然 401，纯属噪声。
        """
        explicit_base = valid_env(f"{provider}_BASE_URL")
        explicit_model = valid_env(f"{provider}_MODEL")
        platform_candidate_added = bool(platform_base_url and public_host not in platform_base_url)
        if platform_candidate_added:
            add_candidate(f"PLATFORM_{provider}_KEY", api_key, platform_base_url, platform_model)
        if explicit_base or not platform_candidate_added:
            add_candidate(provider, api_key,
                          explicit_base or public_base_url,
                          explicit_model or public_model)

    generic_key = valid_env("LLM_API_KEY")
    if generic_key:
        add_candidate("LLM_API_KEY", generic_key, valid_env("LLM_BASE_URL") or platform_base_url, valid_env("LLM_MODEL") or platform_model)
    openai_key = valid_env("OPENAI_API_KEY")
    if openai_key:
        add_provider("OPENAI", openai_key, "openai.com", "https://api.openai.com/v1", "gpt-4o-mini")
    dashscope_key = valid_env("DASHSCOPE_API_KEY")
    if dashscope_key:
        add_provider("DASHSCOPE", dashscope_key, "dashscope.aliyuncs.com", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus")
    deepseek_key = valid_env("DEEPSEEK_API_KEY")
    if deepseek_key:
        add_provider("DEEPSEEK", deepseek_key, "api.deepseek.com", "https://api.deepseek.com/v1", "deepseek-v4-flash")

    preferred = valid_env("LLM_PROVIDER").upper()
    if preferred:
        candidates.sort(key=lambda item: 0 if item["name"].upper() == preferred else 1)
    return candidates


def _init_skill_executor(project_root: str) -> None:
    """初始化 SkillExecutor 并注册到 _app_state。"""
    from DataCode.config_manager import ConfigManager
    from DataCode.tool_registry import ToolRegistry
    from DataCode.builtin_tools import (
        create_read_file_tool, create_write_file_tool,
        create_save_memory_tool, create_read_memory_tool,
        create_todo_tool,
    )
    from DataCode.todo_manager import TodoManager
    from DataCode.memory_store import MemoryStore
    from DataCode.agent_manager import AgentManager
    from DataCode.knowledge_base import RagKnowledgeBase
    from DataCode.skill_executor import SkillExecutor

    root = Path(project_root)
    config = ConfigManager(str(root / "data" / "platform.yaml"), str(root / "data" / "agents"))
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
        long_term_path=str(root / "memory"),
        session_id=session_id,
    )
    registry.register(create_save_memory_tool(memory))
    registry.register(create_read_memory_tool(memory))

    todo_mgr = TodoManager()
    registry.register(create_todo_tool(todo_mgr))

    manager = AgentManager(config=config, registry=registry, memory=memory)

    kb = RagKnowledgeBase(str(root / "data" / "knowledge_base"))
    executor = SkillExecutor(agent_manager=manager, knowledge_base=kb, llm_candidates=llm_candidates)
    loaded = executor.load_skills(str(root / "data" / "skills"))
    logger.info("Loaded skills: %s", loaded)

    # 加载流水线配置（从 data/skills/pipeline.yaml）
    executor.load_pipeline(str(root / "data" / "skills" / "pipeline.yaml"))
    logger.info("Pipeline steps: %s", [s.name for s in executor.pipeline_steps])

    _app_state["skill_executor"] = executor
    _app_state["config"] = config
    _app_state["knowledge_base"] = kb


def create_app(
    patients_dir: str = "tempdata/patients",
    skills_dir: str = "data/skills",
    knowledge_dir: str = "data/knowledge_base",
    reports_dir: str = "Result",
    memory_dir: str = "memory",
    project_root: str | None = None,
) -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    app = FastAPI(title="MedAgent Demo", version="0.1.0")

    # CORS：开发阶段允许所有来源。
    # 注意：通配符来源 "*" 不能与 allow_credentials=True 同时使用——浏览器会拒绝
    # "Access-Control-Allow-Origin: *" 与凭证共存的响应。本服务前端与后端同源
    # （生产为静态挂载、开发走 Vite 代理），不依赖跨域 Cookie，因此关闭 credentials
    # 让通配符来源真正生效。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
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
    _init_skill_executor(project_root)

    frontend_dist = Path(project_root) / "frontend_static"
    if not frontend_dist.exists():
        # 兼容旧 React 构建产物作为后备
        frontend_dist = Path(project_root) / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


# uvicorn 入口
app = create_app()
