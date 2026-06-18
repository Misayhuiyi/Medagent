"""Agent 管理器：生命周期管理、Skill 执行、子 Agent 调度。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from DataCode.deep_agent import create_deep_agent

if TYPE_CHECKING:
    from DataCode.execution_logger import ExecutionLogger
    from DataCode.memory_store import MemoryStore
    from DataCode.skill_parser import SkillDef
    from DataCode.tool_registry import ToolRegistry


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
            parallel_tool_calls=self._parallel_tool_calls,
        )
        self._agents[name] = {"agent": agent, "config": None, "status": "active"}

    async def run_skill(self, skill: SkillDef, args: dict | None = None) -> str:
        """执行指定 Skill。创建临时 Agent，执行后自动销毁。"""
        from DataCode.skill_parser import SkillParser

        parser = SkillParser()
        body = parser.resolve_vars(skill.body, args, skill_dir=skill.skill_dir)

        tools = self._assemble_tools_for_skill(skill)
        agent_name = f"skill:{skill.name}"

        agent = create_deep_agent(
            model=skill.model or self._config.get("llm.default_model", ""),
            system_prompt=body,
            tools=tools,
            base_url=self._config.get("llm.base_url", ""),
            api_key=self._config.get("llm.api_key", ""),
            mode=skill.mode,
            logger=self._logger,
            agent_name=agent_name,
            parallel_tool_calls=self._parallel_tool_calls,
        )

        input_text = "\n".join(f"{k}: {v}" for k, v in (args or {}).items()) if args else "开始执行"
        from langchain_core.messages import HumanMessage
        result = await agent.ainvoke({"messages": [HumanMessage(content=input_text)]})

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

    async def schedule_sub_agents(self, tasks: list[tuple[str, SkillDef, dict | None]]) -> list[str]:
        """调度多个子 Agent 任务（串行执行）。"""
        results = []
        for name, skill, args in tasks:
            result = await self.spawn_sub_agent(name, skill, args)
            results.append(result)
        return results

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
        """为 Skill 执行组装工具集。"""
        from DataCode.tool_registry import create_tool_search_tool, create_skill_search_tool
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
        ]
        return [t.to_langchain_tool() for t in tools]
