"""Agent 管理器：生命周期管理、Skill 执行、子 Agent 调度。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from DataCode.deep_agent import create_deep_agent

if TYPE_CHECKING:
    from DataCode.execution_logger import ExecutionLogger
    from DataCode.memory_store import MemoryStore
    from DataCode.skill_parser import SkillDef
    from DataCode.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# 系统 prompt 中患者资料的最大字节数。
# 仅对步骤 05-09（临床推理）注入，轻量步骤（01-04、10）注入文件索引。
_FILES_MAX_BYTES = 15_000
_FILES_PER_FILE_CHARS = 300
# previous_results 注入系统 prompt 的最大字符数（防止上下文超限）
# skill_executor 已通过 _build_previous_summary 按需摘要，此上限作为兜底
_PREV_RESULTS_MAX_CHARS = 5_000
_PRIOR_REPORTS_MAX_CHARS = 30_000
# 需要注入患者资料正文的步骤前缀。
# 01-02 (资料整理+预处理) 需直接读取处理文件内容。
# 03-04 (循环次数+场景判断) 仅需文件索引做逻辑决策。
# 05-09 (临床推理) 需要完整病史数据。
# 10 (报告生成) 从步骤输出组装，不需原始文件。
_FILES_INJECT_STEP_PREFIXES = ("01-", "02-", "05-", "06-", "07-", "08-", "09-")


def _build_file_index(files_text: str) -> str:
    """从患者资料生成文件索引（仅文件名+大小，不含正文）。
    
    用于轻量步骤，避免 80KB 患者资料占用每轮 LLM 调用系统提示。
    """
    lines = []
    try:
        files_list = json.loads(files_text)
        if isinstance(files_list, list):
            for f in files_list:
                name = f.get("name", f.get("file", "?"))
                size = len(f.get("content", "")) if "content" in f else 0
                lines.append(f"- {name} ({size:,} 字符)")
    except (json.JSONDecodeError, TypeError):
        return "（文件索引生成失败）"
    if not lines:
        return "（无文件）"
    total = len(lines)
    return f"共 {total} 个文件：\n" + "\n".join(lines[:30])


def _truncate_files_text(files_text: str) -> str:
    """截断患者资料文本，防止注入系统 prompt 后 LLM 处理超时。

    支持两种格式：
    - JSON 数组 [{name: "...", content: "..."}, ...]
    - Markdown 文本（直接字节截断）

    策略：每文件仅保留前 _FILES_PER_FILE_CHARS 字符，总上限 _FILES_MAX_BYTES。
    """
    if len(files_text.encode("utf-8", errors="replace")) <= _FILES_MAX_BYTES:
        return files_text

    # 尝试 JSON 格式
    try:
        files_list = json.loads(files_text)
        if isinstance(files_list, list):
            truncated_files: list[dict] = []
            total = 0
            for f in files_list:
                content = f.get("content", "")
                if content:
                    f_copy = dict(f)
                    f_copy["content"] = content[:_FILES_PER_FILE_CHARS]
                    file_bytes = len(f_copy["content"].encode("utf-8", errors="replace"))
                    # 预检查：若加上此文件会超限则停止追加（至少保留一个文件）
                    if total + file_bytes > _FILES_MAX_BYTES and truncated_files:
                        break
                    truncated_files.append(f_copy)
                    total += file_bytes
                else:
                    truncated_files.append(f)
                if total > _FILES_MAX_BYTES:
                    break
            return json.dumps(truncated_files, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass

    # Markdown 格式：安全字节截断（避免切断多字节 UTF-8 字符）
    raw = files_text.encode("utf-8", errors="replace")
    if len(raw) > _FILES_MAX_BYTES * 2:
        raw = raw[:_FILES_MAX_BYTES * 2]
    return raw.decode("utf-8", errors="replace")


def _truncate_prior_reports(prior_reports_text: str) -> str:
    if len(prior_reports_text) <= _PRIOR_REPORTS_MAX_CHARS:
        return prior_reports_text
    return (
        prior_reports_text[:_PRIOR_REPORTS_MAX_CHARS]
        + f"\n（既往报告上下文过长，已截断；原长 {len(prior_reports_text)} 字）"
    )


def resolve_sub_skill_path(parent_skill_dir: str, ref_path: str,
                           skills_base_dir: str | None = None) -> str:
    """解析子 Skill 引用路径。

    支持两种引用模式：
    - 相对路径：skills/xxx/SKILL.md → 在 parent_skill_dir 下查找
    - 跨目录引用：../_shared/xxx/SKILL.md → 在 parent_skill_dir 父目录下查找
    若上述均未命中，回退到全局 skills_base_dir 搜索。

    Args:
        parent_skill_dir: 主 Skill 所在目录的绝对路径
        ref_path: 子 Skill 的引用路径（来自 SKILL.md body）
        skills_base_dir: 全局 skills 根目录路径（可选回退）

    Returns:
        子 Skill SKILL.md 的绝对路径

    Raises:
        FileNotFoundError: 路径不存在时抛出
    """
    parent = Path(parent_skill_dir)
    # 直接拼接处理相对路径和 ../ 跨目录引用
    candidate = (parent / ref_path).resolve()
    if candidate.exists():
        return str(candidate)
    # 回退：从全局 skills 目录搜索
    if skills_base_dir:
        candidate = (Path(skills_base_dir) / ref_path).resolve()
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        f"Sub-skill not found: {ref_path} (resolved from {parent_skill_dir})")


# 子 Agent 递归上限分档：
# - 简单子 Skill（患者检查、文件夹管理等）25 轮足够
# - 复杂子 Skill（RAG检索、报告格式转换等）保持 60 轮
# 减少简单子 Agent 的空转迭代，节省总耗时
_SUB_AGENT_RECURSION_SIMPLE = 15
_SUB_AGENT_RECURSION_FULL = 35
_SUB_AGENT_SIMPLE_PREFIXES = (
    "patient-check", "folder-management", "visit-time-categorization",
    "data-type-categorization", "data-verification",
)


def _get_sub_agent_recursion_limit(skill_name: str) -> int:
    """根据子 Skill 复杂度返回合适的递归上限。"""
    for prefix in _SUB_AGENT_SIMPLE_PREFIXES:
        if prefix in skill_name:
            return _SUB_AGENT_RECURSION_SIMPLE
    return _SUB_AGENT_RECURSION_FULL


class AgentManager:
    """管理 Agent 生命周期：启动主 Agent、发现子 Agent、Skill 执行、子 Agent 调度。"""

    def __init__(self, config, registry: ToolRegistry, memory: MemoryStore,
                 logger: ExecutionLogger | None = None,
                 context_manager=None,
                 todo_manager=None):
        self._config = config
        self._registry = registry
        self._memory = memory
        self._logger = logger
        self._context_manager = context_manager
        self._todo_manager = todo_manager
        self._agents: dict[str, dict] = {}
        self._parallel_tool_calls: bool = (
            config.get("llm.parallel_tool_calls", True)
            if hasattr(config, "get") else True
        )
        # LLM 客户端缓存：key=(model, base_url, api_key) → ChatOpenAI 实例
        # 复用避免每个 Agent/子Agent 重复初始化 HTTP 客户端和 SSL 上下文
        self._llm_cache: dict[tuple, Any] = {}

    # 允许并行工具调用的轻量步骤白名单。
    # 这些步骤不涉及 RAG→子Agent 严格依赖链（仅步骤 06 需要），
    # 恢复并行工具调用可减少 LLM 往返轮次 30-40%。
    # 步骤 05-09 的临床评估保持串行（force_serial=False, _parallel_tool_calls 生效）。
    _PARALLEL_TOOL_STEP_PREFIXES = ("01-", "02-", "03-", "04-", "10-")

    def _get_or_create_llm(self, model: str, base_url: str, api_key: str) -> Any:
        key = (model, base_url or "", api_key or "")
        if key not in self._llm_cache:
            from langchain_openai import ChatOpenAI
            self._llm_cache[key] = ChatOpenAI(
                model=model,
                base_url=base_url or None,
                api_key=api_key or "dummy",
                temperature=self._config.get("llm.temperature", 0.7) if hasattr(self, '_config') else 0.7,
                default_headers={"User-Agent": "curl/8.17.0"},
            )
        return self._llm_cache[key]

    def start_main_agent(self) -> None:
        """启动主 Agent。"""
        agent_config = self._config.get_agent_config("main")
        if agent_config is None:
            return

        tools = self._assemble_tools(agent_config)
        agent = create_deep_agent(
            model=agent_config.model,
            system_prompt=agent_config.system_prompt,
            tools=tools,
            base_url=self._config.get("llm.base_url", ""),
            api_key=self._config.get("llm.api_key", ""),
            temperature=self._config.get("llm.temperature", 0.7),
            logger=self._logger,
            agent_name="main",
            parallel_tool_calls=self._parallel_tool_calls,
        )
        self._agents["main"] = {
            "agent": agent,
            "config": agent_config,
            "status": "active",
        }

    def discover_sub_agents(self) -> list[str]:
        """发现并启动配置中除 main 外的所有子 Agent。"""
        created = []
        for name in self._config.list_agents():
            if name == "main" or name in self._agents:
                continue
            agent_config = self._config.get_agent_config(name)
            if agent_config is None:
                continue
            tools = self._assemble_tools(agent_config)
            agent = create_deep_agent(
                model=agent_config.model,
                system_prompt=agent_config.system_prompt,
                tools=tools,
                base_url=self._config.get("llm.base_url", ""),
                api_key=self._config.get("llm.api_key", ""),
                temperature=self._config.get("llm.temperature", 0.7),
                logger=self._logger,
                agent_name=name,
                parallel_tool_calls=self._parallel_tool_calls,
            )
            self._agents[name] = {
                "agent": agent,
                "config": agent_config,
                "status": "active",
            }
            created.append(name)
        return created

    def spawn_agent(self, name: str, system_prompt: str, model: str | None = None) -> None:
        """动态创建一个临时 Agent。"""
        if name in self._agents:
            raise ValueError(f"Agent '{name}' already exists")
        model = model or self._config.get("llm.default_model")
        agent = create_deep_agent(
            model=model,
            system_prompt=system_prompt,
            tools=[],
            base_url=self._config.get("llm.base_url", ""),
            api_key=self._config.get("llm.api_key", ""),
            temperature=self._config.get("llm.temperature", 0.7),
            parallel_tool_calls=self._parallel_tool_calls,
        )
        self._agents[name] = {"agent": agent, "config": None, "status": "active"}

    async def run_skill(self, skill: SkillDef, args: dict | None = None,
                        recursion_limit: int = 25) -> str:
        """执行指定 Skill。创建临时 Agent，执行后自动销毁。"""
        from DataCode.skill_parser import SkillParser

        parser = SkillParser()
        body = parser.resolve_vars(skill.body, args, skill_dir=skill.skill_dir)

        tools = self._assemble_tools_for_skill(skill)
        agent_name = f"skill:{skill.name}"

        model = skill.model or self._config.get("llm.default_model", "")
        base_url = self._config.get("llm.base_url", "")
        api_key = self._config.get("llm.api_key", "")
        shared_llm = self._get_or_create_llm(model, base_url, api_key)

        # 轻量步骤（01-04、10）恢复并行工具调用：减少 LLM 往返轮次。
        # 重量步骤（05-09）保持 platform.yaml 配置（通常 parallel_tool_calls=false）。
        is_lightweight = any(skill.name.startswith(p) for p in self._PARALLEL_TOOL_STEP_PREFIXES)
        step_parallel = True if is_lightweight else self._parallel_tool_calls

        agent = create_deep_agent(
            model=model,
            system_prompt=body,
            tools=tools,
            base_url=base_url,
            api_key=api_key,
            mode=skill.mode,
            logger=self._logger,
            agent_name=agent_name,
            parallel_tool_calls=step_parallel,
            llm=shared_llm,
        )

        # 构建用户消息：患者资料和知识库作为上下文放在首条消息（而非系统提示），
        # 避免每轮 ReAct 循环重复发送 65KB 静态数据。
        # 系统提示仅保留 SKILL.md（~4KB），files/knowledge 仅发送一次即驻留对话上下文。
        files_text = (args or {}).get("files", "")
        knowledge_text = (args or {}).get("knowledge", "")
        prior_reports_text = (args or {}).get("prior_reports", "")
        context_parts = []
        if files_text:
            if any(skill.name.startswith(p) for p in _FILES_INJECT_STEP_PREFIXES):
                context_parts.append(f"【患者资料】\n{_truncate_files_text(files_text)}")
            else:
                context_parts.append(f"【文件索引·按需读取】\n{_build_file_index(files_text)}")
        if prior_reports_text:
            context_parts.append(
                "【既往报告（纵向背景，仅用于连续性对比）】\n"
                "要求：当前报告仍以本次就诊资料为主；既往报告用于识别变化、疗效趋势、毒副反应延续性，"
                "不得把既往事件误写成本次新发生。\n"
                f"{_truncate_prior_reports(str(prior_reports_text))}"
            )
        if knowledge_text:
            context_parts.append(f"【知识库参考】\n{knowledge_text[:10000]}")
        context_block = "\n\n".join(context_parts)

        # 用户消息：context + 步骤指令（files/knowledge 仍在 args 中但不单独传入 user_args）
        user_args = {k: v for k, v in (args or {}).items() if k not in ("files", "knowledge", "prior_reports")}
        # 截断 previous_results 防止上下文超限。
        # skill_executor 已通过 _build_previous_summary 按需摘要（保留内容字段），
        # 此处在超限时仅做字节截断，不再丢失内容。
        if "previous_results" in user_args:
            prev = str(user_args["previous_results"])
            if len(prev) > _PREV_RESULTS_MAX_CHARS:
                try:
                    prev_data = json.loads(prev)
                    if isinstance(prev_data, dict):
                        # 降级：保留最后 3 个步骤的 content_preview + 元数据
                        summary_keys = list(prev_data.keys())[-3:]
                        trimmed = {}
                        for k in summary_keys:
                            item = prev_data[k]
                            if isinstance(item, dict):
                                trimmed[k] = {
                                    "step": item.get("step", k),
                                    "display_name": item.get("display_name", ""),
                                    "content_preview": str(item.get("content_preview", ""))[:200],
                                }
                            else:
                                trimmed[k] = str(item)[:200]
                        prev = json.dumps(trimmed, ensure_ascii=False)
                        if len(prev) > _PREV_RESULTS_MAX_CHARS:
                            prev = prev[:_PREV_RESULTS_MAX_CHARS] + "\n...(已截断)"
                    else:
                        prev = prev[:_PREV_RESULTS_MAX_CHARS] + "\n...(已截断)"
                except (json.JSONDecodeError, TypeError):
                    prev = prev[:_PREV_RESULTS_MAX_CHARS] + "\n...(已截断)"
            user_args["previous_results"] = prev
        instruction_text = "\n".join(f"{k}: {v}" for k, v in user_args.items()) if user_args else "请按上述步骤执行并输出结果。"
        input_text = f"{context_block}\n\n{instruction_text}" if context_block else instruction_text
        from langchain_core.messages import HumanMessage
        import asyncio
        from DataCode.llm_callback import LLMCallbackHandler

        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=input_text)]},
                config={
                    "recursion_limit": recursion_limit,
                    "callbacks": [LLMCallbackHandler(
                        agent_name=agent_name,
                        model=model,
                        base_url=base_url,
                        api_key=api_key,
                    )],
                },
            ),
            timeout=600,  # 600s，步骤 06 有 10 个子 Agent 需充足时间
        )

        messages = result.get("messages", [])

        # 方案 B: 自动卸载 — 将完整对话记录到短期记忆
        for msg in messages:
            if hasattr(msg, "content") and hasattr(msg, "type"):
                role = "assistant" if msg.type == "ai" else msg.type
                self._memory.add_short_term(role, str(msg.content))
        content_size = sum(len(str(getattr(m, "content", ""))) for m in messages)
        if self._memory.should_offload(content_size):
            dump_path = self._memory.dump_to_file()
            if self._logger:
                self._logger.log("info", agent_name, message=f"Memory offloaded to {dump_path}")

        # 方案 C: ContextManager 检查
        if self._context_manager and messages:
            action = self._context_manager.check(messages)
            if action == "force_compress" and self._logger:
                self._logger.log("warning", agent_name, message="Context force compress triggered")

        return messages[-1].content if messages else ""

    async def spawn_sub_agent(self, name: str, skill: SkillDef, args: dict | None = None) -> str:
        """创建临时子 Agent 执行指定 Skill，执行后自动销毁。"""
        result = await self.run_skill(skill, args)
        self._agents.pop(name, None)
        return result

    async def spawn_sub_agent_isolated(self, name: str, skill: SkillDef,
                                       args: dict | None = None,
                                       context: dict | None = None) -> str:
        """创建隔离子 Agent 执行 Skill。

        与 run_skill 的区别：
        - 注入独立上下文 context（如 patient_id、visit_date、previous_results 等），
          以 JSON 格式嵌入 System Prompt，不共享主 Agent 会话状态。
        - 适用于 SKILL.md 中「创建子Agent（sessions_spawn，context="isolated"）」
          的语义。
        - 执行完成后自动销毁。

        Args:
            name: 子 Agent 名称（建议与子 Skill 名一致）
            skill: 已解析的 SkillDef
            args: 变量替换参数（同 run_skill）
            context: 隔离子上下文 dict

        Returns:
            Agent 最终输出的消息文本
        """
        from DataCode.skill_parser import SkillParser

        parser = SkillParser()
        body = parser.resolve_vars(skill.body, args, skill_dir=skill.skill_dir)

        if context:
            serialized = json.dumps(context, ensure_ascii=False, indent=2)
            body += f"\n\n【当前步骤上下文 - 仅用于本次执行】\n```json\n{serialized}\n```"

        tools = self._assemble_tools_for_skill(skill)
        agent_name = f"sub:{name}"

        model = skill.model or self._config.get("llm.default_model", "")
        base_url = self._config.get("llm.base_url", "")
        api_key = self._config.get("llm.api_key", "")
        shared_llm = self._get_or_create_llm(model, base_url, api_key)

        agent = create_deep_agent(
            model=model,
            system_prompt=body,
            tools=tools,
            base_url=base_url,
            api_key=api_key,
            mode=skill.mode,
            logger=self._logger,
            agent_name=agent_name,
            parallel_tool_calls=self._parallel_tool_calls,
            llm=shared_llm,
        )

        input_text = (args or {}).get("message", "请按上述步骤执行并输出结果。")
        from langchain_core.messages import HumanMessage
        import asyncio
        from DataCode.llm_callback import LLMCallbackHandler

        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=input_text)]},
                config={
                    "recursion_limit": _get_sub_agent_recursion_limit(skill.name),  # 按复杂度分档
                    "callbacks": [LLMCallbackHandler(
                        agent_name=agent_name,
                        model=model,
                        base_url=base_url,
                        api_key=api_key,
                    )],
                },
            ),
            timeout=120,  # 子 Agent 120s 超时，避免无限阻塞父 Agent
        )

        messages = result.get("messages", [])
        self._agents.pop(agent_name, None)
        return messages[-1].content if messages else ""

    async def schedule_sub_agents(self, tasks: list[tuple[str, SkillDef, dict | None]]) -> list[str]:
        """调度多个子 Agent 任务（串行执行）。"""
        results = []
        for name, skill, args in tasks:
            result = await self.spawn_sub_agent(name, skill, args)
            results.append(result)
        return results

    async def spawn_sub_agents_parallel(
        self,
        tasks: list[tuple[str, SkillDef, dict | None]],
        max_concurrent: int = 4,
    ) -> list:
        """并行创建多个隔离子 Agent 执行子 Skill。

        用于步骤 06（患者概况）和步骤 05（病史总结）等子步骤相互独立的场景，
        将原串行 N×30s 缩短为 max(30s, 30s, ...) ≈ 30s。

        安全保证：
        1. 每个子 Agent 通过 spawn_sub_agent_isolated 创建，上下文相互隔离
        2. Semaphore 控制并发，避免 LLM API 限流（DeepSeek 通常支持 10+ 并发）
        3. 单个子 Agent 失败不影响其他任务，返回 Exception 对象而非抛出

        Args:
            tasks: [(name, skill, args), ...] — 与 schedule_sub_agents 入参格式一致
            max_concurrent: 最大并发数

        Returns:
            结果列表，与 tasks 顺序一一对应。失败项为 Exception 对象。
        """
        import asyncio as _asyncio

        sem = _asyncio.Semaphore(max_concurrent)

        async def _safe_run(name: str, skill: SkillDef, args: dict | None):
            async with sem:
                try:
                    return await self.spawn_sub_agent_isolated(name, skill, args)
                except Exception as e:
                    logger.warning("并行子 Agent [%s] 失败: %s", name, e)
                    return e  # 返回异常而非抛出，确保其他任务不受影响

        return await _asyncio.gather(*[
            _safe_run(name, skill, args) for name, skill, args in tasks
        ])

    def destroy_agent(self, name: str) -> None:
        """销毁指定 Agent。"""
        if name == "main":
            raise ValueError("Cannot destroy the main agent")
        self._agents.pop(name, None)

    def list_agents(self) -> list[str]:
        """返回所有已创建 Agent 的名称列表。"""
        return list(self._agents.keys())

    def get_agent_status(self, name: str) -> dict | None:
        """获取 Agent 状态。"""
        entry = self._agents.get(name)
        if entry is None:
            return None
        return {"name": name, "status": entry["status"]}

    def get_agent(self, name: str) -> Any:
        """获取 Agent 可调用实例。"""
        entry = self._agents.get(name)
        return entry["agent"] if entry else None

    async def route_message(self, target: str, message: dict) -> Any:
        """将消息路由到目标 Agent（异步，避免阻塞事件循环）。"""
        agent = self.get_agent(target)
        if agent is None:
            return f"Error: Agent '{target}' not found"
        return await agent.ainvoke({"messages": [message]})

    def _assemble_tools(self, agent_config) -> list:
        """为 Agent 组装工具集：ToolSearch + SkillSearch + ExecuteTool。"""
        from DataCode.tool_registry import create_tool_search_tool, create_skill_search_tool
        from DataCode.execute_tool import ExecuteTool

        available = agent_config.available_tools or []
        tools = [
            create_tool_search_tool(self._registry),
            create_skill_search_tool(self._registry),
            ExecuteTool(
                registry=self._registry,
                allowed_tools=available,
                logger=self._logger,
                todo_manager=self._todo_manager,
            ).as_tool(),
        ]
        return [t.to_langchain_tool() for t in tools]

    def _assemble_tools_for_skill(self, skill: SkillDef) -> list:
        """为 Skill 执行组装工具集。

        除通用工具外，还注入 sessions_spawn 工具，让 Agent 能创建隔离子 Agent
        调用子 Skill（SKILL.md 中「sessions_spawn, context="isolated"」语义）。
        """
        from DataCode.tool_registry import create_tool_search_tool, create_skill_search_tool, ToolDef
        from DataCode.execute_tool import ExecuteTool

        available = skill.allowed_tools or None
        tools = [
            create_tool_search_tool(self._registry),
            create_skill_search_tool(self._registry),
            ExecuteTool(
                registry=self._registry,
                allowed_tools=available,
                logger=self._logger,
                todo_manager=self._todo_manager,
            ).as_tool(),
            self._create_sessions_spawn_tool(skill),
            self._create_sessions_spawn_parallel_tool(skill),
        ]
        return [t.to_langchain_tool() for t in tools]

    async def _run_knowledge_retrieval_direct(self, context: dict | None) -> str:
        """直接执行共享 RAG 子 Skill，避免 LLM 在旧 exec 脚本说明里反复试错。"""
        import asyncio as _asyncio
        import re as _re

        ctx = context or {}

        def _pick_query(value: Any) -> str:
            if isinstance(value, dict):
                for key in ("query", "question", "查询问题", "查询内容", "message", "raw"):
                    found = _pick_query(value.get(key))
                    if found:
                        return found
                return json.dumps(value, ensure_ascii=False)
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return ""
                try:
                    parsed = json.loads(text)
                    nested = _pick_query(parsed)
                    if nested:
                        return nested
                except Exception:
                    pass
                match = _re.search(r'"(?:query|question|查询问题|查询内容)"\s*:\s*"([^"]+)"', text)
                if match:
                    return match.group(1)
                return text
            return ""

        query = _pick_query(ctx)
        if not query:
            query = "肺癌 诊疗 指南 随访 护理"

        top_k = 5
        if isinstance(ctx, dict):
            try:
                top_k = int(ctx.get("top_k") or ctx.get("topK") or ctx.get("检索数量") or top_k)
            except (TypeError, ValueError):
                top_k = 5

        rag_tool = self._registry.get("rag_query")
        if rag_tool is None or rag_tool.handler is None:
            return json.dumps({"error": "rag_query 工具未注册", "query": query}, ensure_ascii=False)

        handler = rag_tool.handler
        if _asyncio.iscoroutinefunction(handler):
            return await handler(query=query, top_k=top_k, mode="retrieve")
        return handler(query=query, top_k=top_k, mode="retrieve")

    def _create_sessions_spawn_tool(self, parent_skill: SkillDef) -> ToolDef:
        """创建 sessions_spawn 工具：创建隔离子 Agent 调用子 Skill。

        对应 SKILL.md 中「创建子Agent（sessions_spawn, context="isolated"）」语义。
        Agent 通过此工具指定子 Skill 路径，工具内部解析子 Skill 并调用
        spawn_sub_agent_isolated 执行，返回子 Skill 的输出文本。
        """
        import json as _json
        from DataCode.tool_registry import ToolDef

        parent_skill_dir = parent_skill.skill_dir or ""
        # skills 根目录 = parent_skill_dir 的父目录
        skills_base_dir = str(Path(parent_skill_dir).parent) if parent_skill_dir else ""

        async def handler(skill_path: str = "", context: str = "") -> str:
            if not skill_path:
                return "Error: skill_path 参数不能为空"

            # 解析子 Skill 路径
            try:
                resolved = resolve_sub_skill_path(
                    parent_skill_dir, skill_path, skills_base_dir
                )
            except FileNotFoundError as e:
                return f"Error: {e}"

            from DataCode.skill_parser import SkillParser
            parser = SkillParser()
            try:
                sub_skill = parser.parse(resolved)
                sub_skill.skill_dir = str(Path(resolved).parent.resolve())
            except Exception as e:
                return f"Error: 解析子 Skill 失败 - {e}"

            # 解析 context
            ctx = None
            if context:
                try:
                    ctx = _json.loads(context)
                except _json.JSONDecodeError:
                    ctx = {"raw": context}

            if sub_skill.name == "knowledge-retrieval":
                try:
                    return await self._run_knowledge_retrieval_direct(ctx)
                except Exception as e:
                    logger.exception("Direct knowledge retrieval failed")
                    return f"Error: RAG 查询失败 - {e}"

            try:
                result = await self.spawn_sub_agent_isolated(
                    name=sub_skill.name,
                    skill=sub_skill,
                    context=ctx,
                )
                return result
            except Exception as e:
                logger.exception("sessions_spawn failed for %s", skill_path)
                return f"Error: 子 Skill 执行失败 - {e}"

        return ToolDef(
            name="sessions_spawn",
            description=(
                "创建隔离子 Agent 调用子 Skill 执行。"
                "skill_path: 子 Skill 的 SKILL.md 相对路径"
                "（如 skills/present-illness/SKILL.md 或 present-illness/SKILL.md）；"
                "context: 可选上下文 JSON 字符串。"
                "返回子 Skill 的输出文本。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill_path": {
                        "type": "string",
                        "description": "子 Skill 的 SKILL.md 路径（相对于当前 Skill 目录或 skills 根目录）",
                    },
                    "context": {
                        "type": "string",
                        "description": "可选上下文，JSON 字符串",
                    },
                },
                "required": ["skill_path"],
            },
            source="builtin",
            handler=handler,
        )

    def _create_sessions_spawn_parallel_tool(self, parent_skill: SkillDef) -> ToolDef:
        """创建并行 sessions_spawn 工具：同时创建多个隔离子 Agent 调用子 Skill。

        对应 SKILL.md 中「同时创建多个子Agent」语义。
        Agent 通过此工具指定多个子 Skill 路径（JSON 字符串数组），各子 Skill 并行执行，
        汇总所有子 Skill 的输出文本。

        预期收益：步骤 06（10 个子步骤）从 300-500s 降至 100-200s。
        """
        import json as _json
        from DataCode.tool_registry import ToolDef

        parent_skill_dir = parent_skill.skill_dir or ""
        skills_base_dir = str(Path(parent_skill_dir).parent) if parent_skill_dir else ""

        async def handler(skill_paths: str = "", context: str = "") -> str:
            if not skill_paths:
                return "Error: skill_paths 参数不能为空"

            try:
                paths = _json.loads(skill_paths)
                if not isinstance(paths, list):
                    return "Error: skill_paths 必须是 JSON 字符串数组"
            except _json.JSONDecodeError:
                return "Error: skill_paths 必须是合法的 JSON 字符串数组"

            ctx = None
            if context:
                try:
                    ctx = _json.loads(context)
                except _json.JSONDecodeError:
                    ctx = {"raw": context}

            import asyncio as _asyncio
            from DataCode.skill_parser import SkillParser
            parser = SkillParser()

            async def _resolve_and_run(idx: int, skill_path: str) -> tuple[int, str]:
                if not isinstance(skill_path, str) or not skill_path.strip():
                    return (idx, "Error: 空的 skill_path")
                try:
                    resolved = resolve_sub_skill_path(
                        parent_skill_dir, skill_path, skills_base_dir
                    )
                except FileNotFoundError as e:
                    return (idx, f"Error: {e}")
                try:
                    sub_skill = parser.parse(resolved)
                    sub_skill.skill_dir = str(Path(resolved).parent.resolve())
                except Exception as e:
                    return (idx, f"Error: 解析子 Skill 失败 - {e}")
                try:
                    result = await self.spawn_sub_agent_isolated(
                        name=sub_skill.name, skill=sub_skill, context=ctx,
                    )
                    return (idx, result)
                except Exception as e:
                    return (idx, f"Error: 子 Skill 执行失败 - {e}")

            valid_paths = [(idx, p) for idx, p in enumerate(paths)
                          if isinstance(p, str) and p.strip()]
            if not valid_paths:
                return "Error: 没有有效的 skill_path"

            parallel_results = await _asyncio.gather(*[
                _resolve_and_run(idx, p) for idx, p in valid_paths
            ])
            result_map = dict(parallel_results)
            output_parts = []
            for idx in range(len(paths)):
                if idx in result_map:
                    label = paths[idx] if isinstance(paths[idx], str) else f"task_{idx}"
                    output_parts.append(f"【{label}】\n{result_map[idx]}")
            return "\n\n---\n\n".join(output_parts)

        return ToolDef(
            name="sessions_spawn_parallel",
            description=(
                "并行创建多个隔离子 Agent 同时调用多个子 Skill。"
                "skill_paths: JSON 字符串数组；"
                "context: 可选上下文 JSON 字符串（所有子 Skill 共享）。"
                "返回所有子 Skill 输出的拼接文本。"
                "典型应用：患者概况步骤中同时执行体格检查、辅助检查等互不依赖的子步骤。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill_paths": {
                        "type": "string",
                        "description": "子 Skill 路径 JSON 字符串数组",
                    },
                    "context": {
                        "type": "string",
                        "description": "可选上下文 JSON 字符串",
                    },
                },
                "required": ["skill_paths"],
            },
            source="builtin",
            handler=handler,
        )
