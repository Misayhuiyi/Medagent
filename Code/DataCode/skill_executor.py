"""SkillExecutor：Web 层与 Agent 层之间的桥梁。

包装 AgentManager + SkillParser + KnowledgeBase，
支持两种模式：
  - Tab 模式：并行执行多个独立 Skill（按配置生成标签页）
  - Pipeline 模式：串行执行流水线步骤（按 pipeline.yaml 驱动）

所有业务逻辑（步骤名称、顺序、输出 Schema）均由 skills/pipeline.yaml + 各步骤
目录下的 schema.json 控制，引擎层不做硬编码。
"""

from __future__ import annotations

import json
import logging
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from DataCode.llm_callback import LLMCallbackHandler, LLMCallTracker

if TYPE_CHECKING:
    from DataCode.agent_manager import AgentManager
    from DataCode.knowledge_base import KnowledgeBase
    from DataCode.skill_parser import SkillDef, SkillParser

logger = logging.getLogger(__name__)
LLM_CHAT_TIMEOUT_SECONDS = 30
LLM_CHAT_STREAM_IDLE_TIMEOUT = 45
LLM_TAB_TIMEOUT_SECONDS = 60
SKILL_FILES_CHAR_BUDGET = 60000
SKILL_PER_FILE_CHAR_BUDGET = 6000


# ═══════════════════════════════════════════════════════════════
# 流水线配置
# ═══════════════════════════════════════════════════════════════

@dataclass
class PipelineStep:
    """流水线中的单个步骤。"""
    name: str
    display_name: str
    skill_file: str = ""
    keywords: list[str] = field(default_factory=list)
    has_schema: bool = False


def load_pipeline_config(pipeline_yaml_path: str) -> list[PipelineStep]:
    """从 skills/pipeline.yaml 加载流水线步骤配置。"""
    path = Path(pipeline_yaml_path)
    if not path.exists():
        logger.warning("Pipeline config not found: %s, using empty pipeline", path)
        return []
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to parse pipeline config: %s", path)
        return []
    steps = []
    for step_data in config.get("pipeline", {}).get("steps", []):
        steps.append(PipelineStep(
            name=step_data.get("name", ""),
            display_name=step_data.get("display_name", step_data.get("name", "")),
            skill_file=step_data.get("skill_file", ""),
            keywords=step_data.get("keywords", []),
            has_schema=step_data.get("has_schema", False),
        ))
    return steps


def _load_step_schema(skills_dir: str, step: PipelineStep) -> dict | None:
    """加载步骤的 Function Calling Schema（可选）。"""
    schema_path = Path(skills_dir) / step.name / "schema.json"
    if not schema_path.exists():
        return None
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load schema for step %s", step.name)
        return None


def _score_result_for_step(result: dict, keywords: list[str]) -> int:
    """对单条 KB 结果按步骤关键词打分。"""
    if not keywords:
        return 0
    content = result.get("content", "") + result.get("source", "")
    return sum(content.count(kw) for kw in keywords)


# ═══════════════════════════════════════════════════════════════
# 辅助函数（通用，不依赖业务）
# ═══════════════════════════════════════════════════════════════

def _file_category_summary(files: list[dict]) -> str:
    """统计患者资料分类摘要（按文件所在目录自动归类，不假定业务分类体系）。"""
    counts: dict[str, int] = {}
    for file in files:
        name = str(file.get("name", ""))
        # 自动从文件路径提取父目录作为类别
        parts = name.replace("\\", "/").split("/")
        if len(parts) >= 2:
            category = parts[-2]
        else:
            category = "资料"
        counts[category] = counts.get(category, 0) + 1
    if not counts:
        return "暂无可解析文件"
    return "、".join(f"{key}{value}份" for key, value in counts.items())


def _first_content_snippet(files: list[dict], limit: int = 160) -> str:
    """获取第一个有内容的文件摘要。"""
    for file in files:
        content = str(file.get("content", "")).strip()
        if content:
            return content.replace("\n", " ")[:limit]
    return "当前未读取到可用资料，请补充患者数据。"


def _format_files_for_prompt(
    files: list[dict],
    total_budget: int = SKILL_FILES_CHAR_BUDGET,
    per_file_budget: int = SKILL_PER_FILE_CHAR_BUDGET,
) -> str:
    """把患者文件列表渲染成有上限的可读文本。"""
    if not files:
        return "（无可用患者文件）"
    parts: list[str] = []
    used = 0
    for index, file in enumerate(files, start=1):
        name = str(file.get("name", f"file_{index}"))
        content = str(file.get("content", "")).strip()
        if len(content) > per_file_budget:
            content = content[:per_file_budget] + f"\n……（该文件已截断，原长 {len(content)} 字）"
        block = f"### 文件 {index}: {name}\n{content}"
        if used + len(block) > total_budget:
            remaining = len(files) - index + 1
            parts.append(f"（其余 {remaining} 个文件因长度限制未全部展开，请结合关键资料分析）")
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# SkillExecutor
# ═══════════════════════════════════════════════════════════════

class SkillExecutor:
    """Skill 执行器：支持 Tab 模式（并行）和 Pipeline 模式（串行）。"""

    def __init__(
        self,
        agent_manager: AgentManager,
        knowledge_base: KnowledgeBase,
        llm_candidates: list[dict] | None = None,
        pipeline_steps: list[PipelineStep] | None = None,
        skills_dir: str = "",
    ):
        self._agent_manager = agent_manager
        self._kb = knowledge_base
        self._skills: dict[str, SkillDef] = {}
        self._llm_candidates = llm_candidates or []
        self._disabled_providers: set[str] = set()
        self._pipeline_steps = pipeline_steps or []
        self._skills_dir = skills_dir

    def load_skills(self, skills_dir: str) -> list[str]:
        """解析 skills 目录下所有 SKILL.md。"""
        from DataCode.skill_parser import SkillParser
        parser = SkillParser()
        loaded = []
        for skill in parser.parse_dir(skills_dir):
            self._skills[skill.name] = skill
            loaded.append(skill.name)
        self._skills_dir = skills_dir
        return loaded

    def load_pipeline(self, pipeline_yaml_path: str) -> list[PipelineStep]:
        """加载流水线配置。"""
        self._pipeline_steps = load_pipeline_config(pipeline_yaml_path)
        return self._pipeline_steps

    @property
    def pipeline_steps(self) -> list[PipelineStep]:
        return self._pipeline_steps

    # ── 知识库 ──

    def _format_knowledge(self, results: list[dict]) -> str:
        if not results:
            return "无相关知识库资料。"
        lines = []
        for i, r in enumerate(sorted(results, key=lambda x: x.get("evidence_level", 0), reverse=True), 1):
            edition = r.get("guideline_edition", "")
            lines.append(
                f"[KB-{i}] {r['source']}"
                + (f" ({edition})" if edition else "")
                + f" | 证据等级: {r.get('evidence_label', '')}"
                + f" | 发布: {r.get('publish_date', '')}"
                + f"\n{r['content'][:800]}"
            )
        return "\n\n".join(lines)

    # ── LLM 路由 ──

    def _apply_llm_candidate(self, candidate: dict) -> None:
        config = getattr(self._agent_manager, "_config", None)
        if config is None:
            return
        llm = config._platform.setdefault("llm", {})
        llm["api_key"] = candidate["api_key"]
        llm["base_url"] = candidate["base_url"]
        llm["default_model"] = candidate["model"]

    def _candidate_names(self) -> str:
        names = [item.get("name", "LLM") for item in self._llm_candidates]
        return "、".join(names) if names else "平台默认 LLM"

    @staticmethod
    def _classify_llm_error(error: Exception) -> str:
        text = str(error)
        lower = text.lower()
        if any(kw in lower for kw in ("401", "403", "invalid api key", "autherror",
                                        "authentication", "forbidden", "access denied",
                                        "error code: 1010")):
            return "认证失败"
        if "timeout" in lower or isinstance(error, TimeoutError):
            return "调用超时"
        return "调用失败"

    @staticmethod
    def _extract_system_prompt(body: str) -> str:
        """从 SKILL.md body 中提取 ## System Prompt 代码块。"""
        import re
        pattern = r'## System Prompt\s*\n\s*```[^\n]*\n(.*?)```'
        match = re.search(pattern, body, re.DOTALL)
        if match:
            return match.group(1).strip()
        return body

    @staticmethod
    def _extract_json(text: str) -> str:
        """从模型输出中提取 JSON 主体。"""
        import re
        cleaned = text.strip()
        if "```" in cleaned:
            fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
            if fence:
                cleaned = fence.group(1).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            result = cleaned[start:end + 1]
            result = re.sub(r',\s*}', '}', result)
            result = re.sub(r',\s*]', ']', result)
            open_braces = result.count('{') - result.count('}')
            open_brackets = result.count('[') - result.count(']')
            result += '}' * open_braces + ']' * open_brackets
            return result
        return cleaned

    def reset_disabled_providers(self) -> None:
        self._disabled_providers.clear()

    def llm_status(self) -> dict:
        return {
            "candidates": [
                {
                    "name": item.get("name", ""),
                    "model": item.get("model", ""),
                    "base_url": item.get("base_url", ""),
                    "api_key_tail": ("****" + item["api_key"][-4:]) if item.get("api_key") else "",
                }
                for item in self._llm_candidates
            ],
            "disabled": sorted(self._disabled_providers),
            "tab_timeout_s": LLM_TAB_TIMEOUT_SECONDS,
            "chat_timeout_s": LLM_CHAT_TIMEOUT_SECONDS,
        }

    # ── Skill 执行 ──

    async def _run_skill_with_llm_candidates(self, skill: SkillDef, args: dict) -> str:
        """执行 Skill，自动路由多个 LLM 候选（认证失败/超时自动切换）。"""
        candidates = self._llm_candidates or [None]
        last_error: Exception | None = None
        for candidate in candidates:
            provider = candidate.get("name", "平台默认 LLM") if candidate else "平台默认 LLM"
            if provider in self._disabled_providers:
                continue
            if candidate:
                self._apply_llm_candidate(candidate)
            try:
                return await asyncio.wait_for(
                    self._run_skill_single_shot(skill, args, candidate, provider),
                    timeout=LLM_TAB_TIMEOUT_SECONDS,
                )
            except TimeoutError as e:
                self._disabled_providers.add(provider)
                last_error = e
                logger.warning("LLM provider %s timed out for skill %s", provider, skill.name)
                break
            except Exception as e:
                last_error = e
                kind = self._classify_llm_error(e)
                logger.warning(
                    "LLM provider %s failed for skill %s: %s (%s: %s)",
                    provider, skill.name, kind, type(e).__name__, str(e)[:300],
                )
                if kind == "认证失败":
                    self._disabled_providers.add(provider)
                    continue
                break
        if last_error:
            raise RuntimeError(f"{self._classify_llm_error(last_error)}，已尝试：{self._candidate_names()}")
        raise RuntimeError(f"没有可用 LLM 候选，已尝试：{self._candidate_names()}")

    async def _run_skill_single_shot(self, skill: SkillDef, args: dict,
                                     candidate: dict | None, provider: str) -> str:
        """单次 Skill 执行（含 Function Calling 或纯文本模式）。"""
        import json as _json
        from openai import AsyncOpenAI
        from DataCode.skill_parser import SkillParser

        parser = SkillParser()
        full_body = parser.resolve_vars(skill.body, args, skill_dir=skill.skill_dir)
        body = self._extract_system_prompt(full_body)

        files_text = args.get("files", "")
        knowledge_text = args.get("knowledge", "")
        if files_text:
            body += f"\n\n【患者资料】\n{files_text}"
        if knowledge_text:
            body += f"\n\n【知识库参考】\n{knowledge_text}"

        config = getattr(self._agent_manager, "_config", None)
        base_url = (candidate or {}).get("base_url") or (config.get("llm.base_url", "") if config else "")
        model = (candidate or {}).get("model") or (config.get("llm.default_model", "") if config else "")
        api_key = (candidate or {}).get("api_key") or (config.get("llm.api_key", "") if config else "")
        agent_name = f"skill:{skill.name}:{provider}"

        # 尝试加载该 Skill 的 Function Schema
        tool = None
        schema_path = Path(self._skills_dir) / skill.name / "schema.json"
        if schema_path.exists():
            try:
                tool = _json.loads(schema_path.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("Failed to load schema for skill %s", skill.name)

        client = AsyncOpenAI(
            api_key=api_key or "dummy",
            base_url=base_url or None,
            default_headers={"User-Agent": "curl/8.17.0"},
        )

        from DataCode.llm_callback import LLMCallTracker
        tracker = LLMCallTracker.instance()
        call_id = tracker.start(agent=agent_name, model=model, base_url=base_url,
                                api_key=api_key, prompt=body, kind="chat")

        try:
            if tool:
                func_name = tool["function"]["name"]
                tool_schema = _json.dumps(tool["function"]["parameters"], ensure_ascii=False)
                is_flash = "flash" in model.lower()
                if is_flash:
                    system_msg = f"{body}\n\n你必须输出以下JSON结构，字段名不可改变：\n{tool_schema}"
                    for attempt in range(2):
                        response = await client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": system_msg},
                                {"role": "user", "content": "请输出JSON。"},
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.3 if attempt == 0 else 0.5,
                        )
                        content = response.choices[0].message.content or ""
                        try:
                            result = self._extract_json(str(content))
                            _json.loads(result)
                            tracker.succeed(call_id, content)
                            return result
                        except Exception:
                            if attempt == 0:
                                system_msg = f"{body}\n\n字段名不可改变，只输出纯JSON。\n{tool_schema}"
                                continue
                            tracker.succeed(call_id, content)
                            return self._extract_json(str(content))
                else:
                    system_msg = f"{body}\n\n请调用 {func_name} 函数提交数据。"
                    for attempt in range(2):
                        response = await client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": system_msg},
                                {"role": "user", "content": f"请调用 {func_name} 函数提交数据。你必须调用此函数, 不要输出任何文本。"},
                            ],
                            tools=[tool],
                            temperature=0.4,
                        )
                        msg = response.choices[0].message
                        if msg.tool_calls and len(msg.tool_calls) > 0:
                            args_str = msg.tool_calls[0].function.arguments
                            tracker.succeed(call_id, args_str)
                            return args_str
                        if attempt == 0:
                            system_msg = f"你必须只调用 {func_name} 函数, 绝不能输出文本。\n\n{body}"
                            continue
                        content = msg.content or ""
                        tracker.succeed(call_id, content)
                        return self._extract_json(str(content))
            else:
                # 无 Schema → 纯文本模式
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": body},
                        {"role": "user", "content": args.get("message", "请开始执行。")},
                    ],
                    temperature=0.4,
                )
                content = response.choices[0].message.content or ""
                tracker.succeed(call_id, content)
                # 包装为 JSON 以便后续统一处理
                return _json.dumps({"step": skill.name, "result": content}, ensure_ascii=False)
        except Exception as e:
            tracker.fail(call_id, e)
            raise

    # ── 对话模式 ──

    async def execute_chat(
        self,
        patient_id: str,
        files: list[dict],
        message: str,
        history: list[dict],
    ) -> AsyncIterator[dict]:
        """主 LLM 对话流。"""
        self.reset_disabled_providers()
        event_id = 1
        yield {"id": event_id, "event": "status", "data": {"state": "thinking"}}

        prompt_messages = self._build_chat_prompt(patient_id, files, message, history)
        last_error: Exception | None = None
        for candidate in (self._llm_candidates or [None]):
            provider = candidate.get("name", "平台默认 LLM") if candidate else "平台默认 LLM"
            if provider in self._disabled_providers:
                continue
            if candidate:
                self._apply_llm_candidate(candidate)
            try:
                async for chunk in self._stream_main_llm(prompt_messages, candidate, provider):
                    if not chunk or not chunk.get("text"):
                        continue
                    event_id += 1
                    if chunk.get("kind") == "reasoning":
                        yield {"id": event_id, "event": "reasoning", "data": {"content": chunk["text"]}}
                    else:
                        yield {"id": event_id, "event": "token", "data": {"content": chunk["text"]}}
                event_id += 1
                yield {"id": event_id, "event": "done", "data": {"provider": provider}}
                return
            except TimeoutError as e:
                self._disabled_providers.add(provider)
                last_error = e
                continue
            except Exception as e:
                last_error = e
                kind = self._classify_llm_error(e)
                if kind == "认证失败":
                    self._disabled_providers.add(provider)
                continue

        kind = self._classify_llm_error(last_error) if last_error else "无可用 LLM"
        fallback_text = self._build_chat_fallback(patient_id, files, message, kind)
        for piece in self._chunked(fallback_text, 60):
            event_id += 1
            yield {"id": event_id, "event": "token", "data": {"content": piece}}
        event_id += 1
        yield {"id": event_id, "event": "done", "data": {"provider": "fallback", "reason": kind}}

    @staticmethod
    def _chunked(text: str, size: int) -> list[str]:
        return [text[i:i + size] for i in range(0, len(text), size)] if text else []

    def _build_chat_prompt(self, patient_id: str, files: list[dict], message: str, history: list[dict]) -> list[dict]:
        sys_prompt = (
            "你是一个 AI 辅助分析助手。请基于已读取的资料用简体中文给出专业、严谨的回答。"
            "若信息不足请明确说明，不要捏造数据。"
        )
        summary = _file_category_summary(files)
        snippet = _first_content_snippet(files, 600)
        context_lines = [
            f"数据编号: {patient_id}",
            f"已读取资料: {summary}",
            f"资料摘要: {snippet}",
        ]
        messages: list[dict] = [
            {"role": "system", "content": sys_prompt},
            {"role": "system", "content": "\n".join(context_lines)},
        ]
        for entry in (history or [])[-8:]:
            role = entry.get("role")
            content = str(entry.get("content", "")).strip()
            if not content:
                continue
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": message})
        return messages

    @staticmethod
    def _build_chat_fallback(patient_id: str, files: list[dict], message: str, reason: str) -> str:
        summary = _file_category_summary(files)
        snippet = _first_content_snippet(files, 240)
        return (
            f"【离线模式】当前未能调用大模型（{reason}），以下是基于已上传资料的本地摘要回答，仅供参考。\n\n"
            f"- 数据: {patient_id}\n"
            f"- 已读取: {summary}\n"
            f"- 片段: {snippet}\n\n"
            f"针对问题「{message}」，建议结合原始数据进一步分析。"
        )

    async def _stream_main_llm(self, messages: list[dict], candidate: dict | None, provider: str) -> AsyncIterator[dict]:
        """OpenAI SDK 流式调用，支持 reasoning_content。"""
        from openai import AsyncOpenAI

        config = getattr(self._agent_manager, "_config", None)
        base_url = (candidate or {}).get("base_url") or (config.get("llm.base_url", "") if config else "")
        model = (candidate or {}).get("model") or (config.get("llm.default_model", "") if config else "")
        api_key = (candidate or {}).get("api_key") or (config.get("llm.api_key", "") if config else "")
        agent_name = f"main_chat:{provider}"

        tracker = LLMCallTracker.instance()
        prompt_text = "\n---\n".join(str(m.get("content", "")) for m in messages)
        call_id = tracker.start(agent=agent_name, model=model, base_url=base_url,
                                api_key=api_key, prompt=prompt_text, kind="chat")

        client = AsyncOpenAI(
            api_key=api_key or "dummy",
            base_url=base_url or None,
            default_headers={"User-Agent": "curl/8.17.0"},
        )

        async def _do_stream() -> AsyncIterator[dict]:
            stream = await client.chat.completions.create(
                model=model, messages=messages, temperature=0.4, stream=True,
            )
            async for ev in stream:
                if not ev.choices:
                    continue
                delta = ev.choices[0].delta
                if delta is None:
                    continue
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    yield {"kind": "reasoning", "text": str(reasoning)}
                if delta.content:
                    yield {"kind": "content", "text": str(delta.content)}

        gen = _do_stream()
        collected_content: list[str] = []
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(gen.__anext__(), timeout=LLM_CHAT_STREAM_IDLE_TIMEOUT)
                except StopAsyncIteration:
                    break
                if chunk and chunk.get("kind") == "content":
                    collected_content.append(chunk["text"])
                yield chunk
            tracker.succeed(call_id, "".join(collected_content))
        except BaseException as e:
            tracker.fail(call_id, e if isinstance(e, BaseException) else RuntimeError(str(e)))
            raise
        finally:
            await gen.aclose()

    # ── 报告/流水线模式 ──

    async def execute_report_skills(
        self,
        patient_id: str,
        files: list[dict],
        message: str,
        visit_date: str,
    ) -> AsyncIterator[dict]:
        """执行报告生成流水线（支持 Tab 并行 / Pipeline 串行 两种模式）。"""
        self.reset_disabled_providers()
        event_id = 1
        yield {"id": event_id, "event": "status", "data": {"state": "reading_files"}}

        # 确定流水线步骤
        steps = self._pipeline_steps
        if not steps:
            event_id += 1
            yield {"id": event_id, "event": "error", "data": {
                "message": "流水线未配置。请在 skills/pipeline.yaml 中注册步骤。"
            }}
            event_id += 1
            yield {"id": event_id, "event": "done", "data": {}}
            return

        # KB 查询
        kb_query = " ".join(
            kw for step in steps for kw in step.keywords[:3]
        ) or "诊疗 指南 评估"
        try:
            knowledge_results = await self._kb.query(question=kb_query, top_k=15, before_date=visit_date)
            knowledge_text = self._format_knowledge(knowledge_results)
            # 缓存到 app_state
            from DataCode.web_server import _app_state
            cache = _app_state.setdefault("trace_cache", {})
            cache[patient_id] = knowledge_results
            for step in steps:
                scored = [(r, _score_result_for_step(r, step.keywords)) for r in knowledge_results]
                scored.sort(key=lambda x: x[1], reverse=True)
                step_results = [r for r, s in scored if s > 0]
                cache[f"{patient_id}:{step.name}"] = step_results if step_results else knowledge_results[:2]
            asyncio.create_task(self._background_clean_cache(patient_id, knowledge_results))
        except Exception as e:
            logger.exception("Knowledge query failed")
            knowledge_text = f"知识库查询失败：{e}"

        # 串行执行流水线步骤
        files_text = _format_files_for_prompt(files)
        llm_disabled_note = ""
        pipeline_results: dict = {}

        for step in steps:
            skill = self._skills.get(step.name)
            fallback_note = ""
            result_json: dict | None = None

            if llm_disabled_note:
                fallback_note = llm_disabled_note
            elif skill:
                try:
                    result_text = await self._run_skill_with_llm_candidates(
                        skill,
                        args={
                            "files": files_text,
                            "patient_id": patient_id,
                            "message": message,
                            "knowledge": knowledge_text,
                            "visit_date": visit_date,
                            "previous_results": json.dumps(pipeline_results, ensure_ascii=False),
                        },
                    )
                    result_json = json.loads(result_text)
                except TimeoutError:
                    fallback_note = f"LLM 调用超过 {LLM_TAB_TIMEOUT_SECONDS} 秒"
                    llm_disabled_note = fallback_note
                    logger.warning("Step %s timed out", step.name)
                except json.JSONDecodeError:
                    fallback_note = "LLM 输出非有效 JSON"
                    logger.exception("JSON decode failed for step %s", step.name)
                except Exception as e:
                    fallback_note = f"LLM {self._classify_llm_error(e)}"
                    llm_disabled_note = fallback_note
                    logger.exception("Step %s failed", step.name)
            else:
                fallback_note = f"Skill {step.name} 未找到"

            if result_json is None:
                logger.warning("Step %s failed: %s", step.name, fallback_note)
                # 生成通用兜底
                result_json = {
                    "step": step.name,
                    "display_name": step.display_name,
                    "status": "fallback",
                    "error": fallback_note,
                    "summary": f"患者 {patient_id}，已读取 {_file_category_summary(files)}",
                }

            pipeline_results[step.name] = result_json
            event_id += 1
            yield {"id": event_id, "event": "tab_ready", "data": {"tab": step.name, "data": result_json}}
            event_id += 1
            suffix = f"（{fallback_note}）" if fallback_note else ""
            yield {"id": event_id, "event": "token", "data": {"content": f"已完成{step.display_name}{suffix}\n"}}

        event_id += 1
        yield {"id": event_id, "event": "done", "data": {}}

    @staticmethod
    async def _background_clean_cache(patient_id: str, knowledge_results: list[dict]) -> None:
        """后台任务：用 LLM 清洗 KB 结果。"""
        try:
            from DataCode.text_cleaner import TextCleaner
            from DataCode.web_server import _app_state

            cleaner = TextCleaner()
            contents = [r.get("content", "") for r in knowledge_results]
            cleaned_contents = await cleaner.clean_batch(contents)

            updated = 0
            for i, cleaned in enumerate(cleaned_contents):
                if i < len(knowledge_results) and cleaned:
                    knowledge_results[i]["content"] = cleaned
                    updated += 1

            if updated > 0:
                cache = _app_state.get("trace_cache", {})
                cache[patient_id] = knowledge_results
                logger.info("Background clean: updated %d/%d chunks for %s",
                            updated, len(knowledge_results), patient_id)
        except Exception:
            logger.exception("Background clean failed for %s", patient_id)
