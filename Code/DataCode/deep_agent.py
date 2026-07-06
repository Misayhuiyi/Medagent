"""DeepAgent 工厂函数：基于 LangGraph ReAct 模式创建智能体。

支持 autonomous（标准 ReAct）和 sequential（步骤链）两种执行模式。
"""

from __future__ import annotations

import re
import ssl

import httpx
from typing import TYPE_CHECKING, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent

from DataCode.llm_callback import LLMCallbackHandler

if TYPE_CHECKING:
    from DataCode.execution_logger import ExecutionLogger
    from DataCode.tool_registry import ToolRegistry


def build_ssl_context() -> ssl.SSLContext:
    """构建兼容系统代理的 SSL 上下文（降低 SECLEVEL 解决 OpenSSL 3.0 TLS 握手失败）。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def create_deep_agent(
    model: str,
    system_prompt: str,
    tools: list,
    base_url: str = "",
    api_key: str = "",
    temperature: float = 0.7,
    mode: str = "autonomous",
    logger: ExecutionLogger | None = None,
    agent_name: str = "",
    parallel_tool_calls: bool = True,
    llm: Any = None,
    force_serial: bool = False,
):
    """创建 DeepAgent（LangGraph ReAct Agent）。

    Args:
        model: 模型名称。
        system_prompt: 系统提示词。
        tools: 可用工具列表（langchain Tool 对象）。
        base_url: LLM API 基础 URL。
        api_key: LLM API 密钥。
        temperature: LLM 生成温度，0=确定性输出。默认 0.7，医疗场景建议设为 0。
        mode: 执行模式 — "autonomous"（标准 ReAct）或 "sequential"（步骤链）。
        logger: 可选 ExecutionLogger，记录执行过程。
        agent_name: Agent 名称，用于日志。
        parallel_tool_calls: 是否允许并行工具调用。默认 True（允许并行）。设为 False 强制顺序执行，提升推理质量。
        llm: 可选预创建的 ChatOpenAI 实例。传入后跳过客户端创建，实现多 Agent 共享 LLM 客户端，减少重复初始化开销。
        force_serial: 强制串行工具调用（覆盖 parallel_tool_calls=False）。
            仅用于步骤 06（患者概况）等有严格 RAG→子Agent 依赖链的场景。
            轻量步骤（01-04、10）不传此参数，保持 parallel_tool_calls 配置不变。

    Returns:
        CompiledStateGraph：可调用的 LangGraph Agent。
    """
    if llm is None:
        llm = ChatOpenAI(
            model=model,
            base_url=base_url or None,
            api_key=api_key or "dummy",
            temperature=temperature,
            default_headers={"User-Agent": "curl/8.17.0"},
        )
    # LLMCallbackHandler 通过 agent.ainvoke(config={"callbacks": [...]}) 传入，
    # 不再绑定到 LLM 客户端构造函数（避免共享客户端时回调冲突）。

    # 仅当 force_serial=True 时才强制禁用并行工具调用。
    # 轻量步骤（01-04、10）不传 force_serial，保持 parallel_tool_calls 原配置。
    should_disable_parallel = force_serial or (not parallel_tool_calls)
    if should_disable_parallel:
        # 共享 LLM 客户端场景：上一个 create_deep_agent 调用可能已包装 bind_tools。
        # 先恢复原始版本，避免双重包装导致 "multiple values for keyword argument
        # 'parallel_tool_calls'" 错误。
        raw_bind = getattr(llm, "_raw_bind_tools", None)
        if raw_bind is not None:
            object.__setattr__(llm, "bind_tools", raw_bind)
        else:
            raw_bind = llm.bind_tools

        def _bind_tools_sequential(_tools, **kw):
            return raw_bind(_tools, parallel_tool_calls=False, **kw)

        object.__setattr__(llm, "_raw_bind_tools", raw_bind)
        object.__setattr__(llm, "bind_tools", _bind_tools_sequential)
    else:
        # 恢复原始 bind_tools（修复拼接顺序 bug：上一步可能已替换为 _bind_tools_sequential，
        # 但当前步骤需要并行工具调用）
        raw = getattr(llm, "_raw_bind_tools", None)
        if raw is not None:
            object.__setattr__(llm, "bind_tools", raw)
            object.__delattr__(llm, "_raw_bind_tools")

    if mode == "sequential":
        return _SequentialAgent(llm, system_prompt, tools, logger, agent_name)

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )


def build_tools_from_registry(
    registry: ToolRegistry,
    allowed_tools: list[str] | None = None,
) -> list:
    """从 ToolRegistry 构建工具列表，支持动态注入。"""
    if allowed_tools:
        tools = [t for t in registry.list_all() if t.name in allowed_tools]
    else:
        tools = registry.list_all()
    return [t.to_langchain_tool() for t in tools if t.handler is not None]


class _SequentialAgent:
    """顺序步骤执行 Agent：将 Skill body 按编号步骤拆分，逐步执行。"""

    def __init__(
        self,
        llm,
        system_prompt: str,
        tools: list,
        logger: ExecutionLogger | None = None,
        agent_name: str = "",
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self._tools = tools
        self._logger = logger
        self._agent_name = agent_name

    def invoke(self, input: dict, **kwargs) -> dict:
        """同步执行步骤链。"""
        messages = input.get("messages", [])
        prompt_text = messages[-1].content if messages else ""

        steps = self._split_steps(self._system_prompt)
        if not steps:
            steps = [self._system_prompt]

        context = prompt_text
        all_messages = list(messages)

        for i, step in enumerate(steps):
            step_prompt = f"步骤 {i + 1}/{len(steps)}: {step}\n\n上下文: {context}"
            if self._logger:
                self._logger.log("info", self._agent_name, message=f"执行步骤 {i + 1}/{len(steps)}")

            response = self._llm.invoke(
                [{"role": "system", "content": self._system_prompt}]
                + all_messages
                + [{"role": "user", "content": step_prompt}]
            )
            context = response.content
            all_messages.append(AIMessage(content=response.content))

        return {"messages": all_messages}

    async def ainvoke(self, input: dict, **kwargs) -> dict:
        """异步执行步骤链。"""
        messages = input.get("messages", [])
        prompt_text = messages[-1].content if messages else ""

        steps = self._split_steps(self._system_prompt)
        if not steps:
            steps = [self._system_prompt]

        context = prompt_text
        all_messages = list(messages)

        for i, step in enumerate(steps):
            step_prompt = f"步骤 {i + 1}/{len(steps)}: {step}\n\n上下文: {context}"
            if self._logger:
                self._logger.log("info", self._agent_name, message=f"执行步骤 {i + 1}/{len(steps)}")

            response = await self._llm.ainvoke(
                [{"role": "system", "content": self._system_prompt}]
                + all_messages
                + [{"role": "user", "content": step_prompt}]
            )
            context = response.content
            all_messages.append(AIMessage(content=response.content))

        return {"messages": all_messages}

    async def astream_events(self, input: dict, version: str = "v2", **kwargs):
        """流式事件输出（顺序模式简化实现）。"""
        result = await self.ainvoke(input, **kwargs)
        messages = result.get("messages", [])
        if messages:
            from langchain_core.messages import AIMessage
            last = messages[-1]
            if isinstance(last, dict):
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": AIMessage(content=last.get("content", ""))},
                }
            else:
                yield {
                    "event": "on_chat_model_stream",
                    "data": {"chunk": last},
                }

    @staticmethod
    def _split_steps(text: str) -> list[str]:
        """按编号步骤拆分文本：1. xxx  2. xxx ..."""
        parts = re.split(r"\n(?=\d+\.\s)", text)
        if len(parts) <= 1:
            return []
        return [re.sub(r"^\d+\.\s*", "", p).strip() for p in parts if p.strip()]
