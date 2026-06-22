"""Code/main.py — MedAgent 唯一主入口。

用法:
  python Code/main.py web            # Web 服务模式（FastAPI + 前端）
  python Code/main.py cli            # CLI 流水线模式（读 params.txt 批量执行）
  python Code/main.py blank          # 空白验证模式（加载空流水线，验证框架可用）

模式说明:
  - web:   启动 FastAPI 服务（端口 8000），前端交互
  - cli:   命令行执行，读取 TempData/params.txt 参数，按 Data/skills/pipeline.yaml 串行执行
  - blank: 验证框架可启动、能加载 Skill、前后端通信正常（最小验证）

符合佰茵云规范：
  - Code/ 下仅此 1 个主函数文件
  - 参数通过 tempdata/params.txt（TXT 制表符分隔）传递
  - 所有自定义模块位于 Code/DataCode/
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 通用工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def _load_env() -> None:
    """加载 .env 环境变量。"""
    env_path = Path(PROJECT_ROOT) / ".env"
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


def _load_params() -> dict[str, str]:
    """从 TempData/params.txt（两行格式）加载参数。

    格式示例（第一行参数名，第二行参数值）:
        model
        deepseek-chat
        temperature
        0.7

    空行和 # 注释行被跳过。
    """
    params_path = Path(PROJECT_ROOT) / "tempdata" / "params.txt"
    if not params_path.exists():
        return {}
    params: dict[str, str] = {}
    lines: list[str] = []
    for raw_line in params_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    # 两行一组配对
    for i in range(0, len(lines) - 1, 2):
        key = lines[i]
        value = lines[i + 1]
        params[key] = value
    return params


def _build_llm_candidates(config) -> list[dict]:
    """构建 LLM 候选列表（从 .env + platform.yaml）。"""
    def valid_env(name: str) -> str:
        value = os.environ.get(name, "").strip()
        lower_value = value.lower()
        if not value or "xxx" in lower_value or "your-api-key" in lower_value:
            return ""
        return value

    llm = config._platform.setdefault("llm", {})
    platform_base_url = str(llm.get("base_url", "") or "").strip()
    platform_model = str(llm.get("default_model", "") or "").strip()
    candidates: list[dict] = []

    def add_candidate(name: str, api_key: str, base_url: str, model: str) -> None:
        if not api_key or not base_url or not model:
            return
        candidates.append({"name": name, "api_key": api_key, "base_url": base_url, "model": model})

    generic_key = valid_env("LLM_API_KEY")
    if generic_key:
        add_candidate("LLM_API_KEY", generic_key, valid_env("LLM_BASE_URL") or platform_base_url, valid_env("LLM_MODEL") or platform_model)

    openai_key = valid_env("OPENAI_API_KEY")
    if openai_key:
        add_candidate("OPENAI", openai_key, "https://api.openai.com/v1", "gpt-4o-mini")

    dashscope_key = valid_env("DASHSCOPE_API_KEY")
    if dashscope_key:
        add_candidate("DASHSCOPE", dashscope_key, "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus")

    deepseek_key = valid_env("DEEPSEEK_API_KEY")
    if deepseek_key:
        add_candidate("DEEPSEEK", deepseek_key, "https://api.deepseek.com/v1", "deepseek-v4-flash")

    preferred = valid_env("LLM_PROVIDER").upper()
    if preferred:
        candidates.sort(key=lambda item: 0 if item["name"].upper() == preferred else 1)
    return candidates


# ═══════════════════════════════════════════════════════════════════════════════
# 模式：web — FastAPI 服务
# ═══════════════════════════════════════════════════════════════════════════════

def _init_web_app():
    """初始化 Web 应用的 SkillExecutor 等服务组件（复用 web_server 模块）。"""
    from DataCode.web_server import create_app, _app_state

    root = Path(PROJECT_ROOT)
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

    config = ConfigManager(str(root / "Data" / "platform.yaml"), str(root / "Data" / "agents"))
    config.load()

    llm = config._platform.setdefault("llm", {})
    llm_candidates = _build_llm_candidates(config)
    if llm_candidates:
        first = llm_candidates[0]
        llm["api_key"] = first["api_key"]
        llm["base_url"] = first["base_url"]
        llm["default_model"] = first["model"]

    errors = config.validate()
    if errors:
        logger.warning("Config validation warnings: %s", errors)

    registry = ToolRegistry()
    registry.register(create_read_file_tool(str(root)))
    registry.register(create_write_file_tool(str(root)))

    session_id = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{secrets.token_hex(3)}"
    memory = MemoryStore(long_term_path=str(root / "Data" / "memory"), session_id=session_id)
    registry.register(create_save_memory_tool(memory))
    registry.register(create_read_memory_tool(memory))

    todo_mgr = TodoManager()
    registry.register(create_todo_tool(todo_mgr))

    manager = AgentManager(config=config, registry=registry, memory=memory)

    kb = RagKnowledgeBase(str(root / "Data" / "knowledge_base"))
    executor = SkillExecutor(agent_manager=manager, knowledge_base=kb, llm_candidates=llm_candidates)
    loaded = executor.load_skills(str(root / "Data" / "skills"))
    logger.info("Loaded skills: %s", loaded)

    executor.load_pipeline(str(root / "Data" / "skills" / "pipeline.yaml"))
    logger.info("Pipeline steps: %s", [s.name for s in executor.pipeline_steps])

    _app_state["skill_executor"] = executor
    _app_state["config"] = config
    _app_state["knowledge_base"] = kb

    return create_app(
        patients_dir=str(root / "TempData" / "patients"),
        skills_dir=str(root / "Data" / "skills"),
        knowledge_dir=str(root / "Data" / "knowledge_base"),
        reports_dir=str(root / "Result"),
        memory_dir=str(root / "Data" / "memory"),
        project_root=str(root),
    )


def _run_web() -> None:
    """启动 FastAPI Web 服务。"""
    import uvicorn
    app = _init_web_app()
    port = int(os.environ.get("PORT", "8000"))
    print(f"MedAgent Web 服务启动: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


# ═══════════════════════════════════════════════════════════════════════════════
# 模式：cli — CLI 流水线
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_cli() -> None:
    """CLI 模式：读取 params.txt → 加载 platform.yaml → 执行流水线。"""
    from DataCode.config_manager import ConfigManager
    from DataCode.tool_registry import ToolRegistry
    from DataCode.builtin_tools import (
        create_read_file_tool, create_write_file_tool,
        create_save_memory_tool, create_read_memory_tool,
        create_todo_tool,
    )
    from DataCode.todo_manager import TodoManager
    from DataCode.memory_store import MemoryStore
    from DataCode.execution_logger import ExecutionLogger
    from DataCode.skill_parser import SkillParser
    from DataCode.agent_manager import AgentManager
    from DataCode.knowledge_base import RagKnowledgeBase
    from DataCode.skill_executor import SkillExecutor

    root = Path(PROJECT_ROOT)

    # 检查配置
    config_path = root / "Data" / "platform.yaml"
    agents_path = root / "Data" / "agents"
    if not config_path.exists():
        print(f"Error: 缺少 {config_path}", file=sys.stderr)
        sys.exit(1)

    # 加载参数
    params = _load_params()
    print(f"加载参数: {len(params)} 项")

    # 初始化
    config = ConfigManager(str(config_path), str(agents_path))
    config.load()

    llm_candidates = _build_llm_candidates(config)
    if llm_candidates:
        llm = config._platform.setdefault("llm", {})
        llm["api_key"] = llm_candidates[0]["api_key"]
        llm["base_url"] = llm_candidates[0]["base_url"]
        llm["default_model"] = llm_candidates[0]["model"]

    session_id = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{secrets.token_hex(3)}"
    print(f"Session: {session_id}")

    registry = ToolRegistry()
    registry.register(create_read_file_tool(str(root)))
    registry.register(create_write_file_tool(str(root)))

    result_dir = root / "Result"
    log_dir = result_dir / "logs"
    logger_obj = ExecutionLogger(str(result_dir), str(log_dir), session_id)

    memory = MemoryStore(long_term_path=str(root / "Data" / "memory"), session_id=session_id)
    registry.register(create_save_memory_tool(memory))
    registry.register(create_read_memory_tool(memory))

    todo_mgr = TodoManager()
    registry.register(create_todo_tool(todo_mgr, logger=logger_obj))

    manager = AgentManager(config=config, registry=registry, memory=memory)

    kb = RagKnowledgeBase(str(root / "Data" / "knowledge_base"))
    executor = SkillExecutor(agent_manager=manager, knowledge_base=kb, llm_candidates=llm_candidates)

    skills_dir = root / "Data" / "skills"
    loaded = executor.load_skills(str(skills_dir))
    print(f"Skills loaded: {loaded}")

    executor.load_pipeline(str(skills_dir / "pipeline.yaml"))
    steps = executor.pipeline_steps
    if not steps:
        print("流水线未配置，请先在 data/skills/pipeline.yaml 中注册步骤")
        sys.exit(1)

    print(f"Pipeline steps ({len(steps)}): {[s.name for s in steps]}")

    # 执行（串行）
    for step in steps:
        skill = executor._skills.get(step.name)
        if not skill:
            print(f"  [跳过] {step.name}: Skill 未找到")
            continue
        print(f"  [执行] {step.display_name} ({step.name})...")
        try:
            result_text = await executor._run_skill_with_llm_candidates(
                skill,
                args={
                    "files": "",
                    "patient_id": params.get("patient_id", "demo"),
                    "message": params.get("message", "请开始执行分析。"),
                    "knowledge": "",
                    "visit_date": params.get("visit_date", datetime.now().strftime("%Y-%m-%d")),
                    "previous_results": "{}",
                },
            )
            import json as _json
            result_json = _json.loads(result_text)
            print(f"    → 结果: {result_json}")
        except Exception as e:
            print(f"    → 错误: {e}")

    print(f"\nDone. Session: {session_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# 模式：blank — 空白验证
# ═══════════════════════════════════════════════════════════════════════════════

def _run_blank() -> None:
    """空白验证：确认框架可启动、Skill 加载正常、路径正确。"""
    root = Path(PROJECT_ROOT)

    checks: list[tuple[str, bool, str]] = []

    # 1. 检查 .env 是否存在
    env_exists = (root / ".env").exists()
    checks.append((".env", env_exists, str(root / ".env")))

    # 2. 检查 platform.yaml
    plat_exists = (root / "Data" / "platform.yaml").exists()
    checks.append(("Data/platform.yaml", plat_exists, str(root / "Data" / "platform.yaml")))

    # 3. 检查 agents 配置
    agents_exists = (root / "Data" / "agents" / "main").exists()
    checks.append(("Data/agents/main/", agents_exists, str(root / "Data" / "agents" / "main")))

    # 4. 检查 pipeline.yaml
    pipeline_exists = (root / "Data" / "skills" / "pipeline.yaml").exists()
    checks.append(("Data/skills/pipeline.yaml", pipeline_exists, str(root / "Data" / "skills" / "pipeline.yaml")))

    # 5. 检查 DataCode 模块
    datacode_dir = root / "Code" / "DataCode"
    module_count = len(list(datacode_dir.glob("*.py")))
    checks.append(("DataCode/*.py", module_count > 0, f"{module_count} 个模块"))

    # 6. 检查前端
    frontend_exists = (root / "frontend" / "package.json").exists()
    checks.append(("frontend/", frontend_exists, str(root / "frontend")))

    # 7. 检查 TempData/ 目录
    tempdata_exists = (root / "TempData").exists()
    checks.append(("TempData/", tempdata_exists, str(root / "TempData")))

    # 8. 尝试加载 Skill
    try:
        from DataCode.skill_parser import SkillParser
        parser = SkillParser()
        skills = parser.parse_dir(root / "Data" / "skills")
        checks.append(("SkillParser", True, f"解析到 {len(skills)} 个 Skill"))
    except Exception as e:
        checks.append(("SkillParser", False, str(e)))

    # 9. 确认主入口唯一
    py_files = list((root / "Code").glob("*.py"))
    main_py = [f for f in py_files if f.name == "main.py"]
    extra = [f for f in py_files if f.name not in ("main.py", "__init__.py")]
    checks.append(("唯一主入口", len(main_py) == 1 and len(extra) == 0,
                   "Code/main.py OK" if not extra else f"多余文件: {[e.name for e in extra]}"))

    # 打印结果
    print("=" * 60)
    print("MedAgent 空白验证")
    print("=" * 60)
    all_pass = True
    for name, ok, detail in checks:
        status = "  PASS" if ok else "  FAIL"
        if not ok:
            all_pass = False
        print(f"[{status}] {name}: {detail}")

    print("=" * 60)
    if all_pass:
        print("All checks passed. Framework is ready.")
    else:
        print("Some checks failed. Please fix and retry.")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """主入口，按参数分发到对应模式。"""
    _load_env()

    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("web", "cli", "blank"):
        print("用法: python Code/main.py <mode>")
        print("  web     启动 FastAPI Web 服务（前端交互）")
        print("  cli     CLI 流水线模式（读 TempData/params.txt）")
        print("  blank   空白验证模式（检查目录/模块是否就绪）")
        sys.exit(1)

    if mode == "web":
        _run_web()
    elif mode == "cli":
        asyncio.run(_run_cli())
    elif mode == "blank":
        _run_blank()


if __name__ == "__main__":
    main()
