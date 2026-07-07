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
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from DataCode.llm_callback import LLMCallTracker
from DataCode.deep_agent import make_async_llm_http_client

if TYPE_CHECKING:
    from DataCode.agent_manager import AgentManager
    from DataCode.knowledge_base import KnowledgeBase
    from DataCode.skill_parser import SkillDef, SkillParser

logger = logging.getLogger(__name__)
LLM_CHAT_TIMEOUT_SECONDS = 60
LLM_CHAT_STREAM_IDLE_TIMEOUT = 60
# Tab 模式单次 LLM 调用超时（秒）。
# agent_manager.run_skill 内部有 600s ainvoke 超时，此处需 ≥ 600s。
LLM_TAB_TIMEOUT_SECONDS = 660
SKILL_FILES_CHAR_BUDGET = 150000
SKILL_PER_FILE_CHAR_BUDGET = 8000

# 步骤感知文件文本预算：(total_budget, per_file_budget)
# 轻量步骤（01-02）只需文件摘要做归类/校验，无需完整临床数据
# 中间步骤（03-04, 10）只需文件索引和名称
# 重量步骤（05-09）需要完整病史和检查数据做临床推理
_STEP_FILES_BUDGETS: dict[str, tuple[int, int]] = {
    "01-": (20_000, 1_000),   # 资料整理：文件名+简要内容即可归类
    "02-": (20_000, 1_000),   # 资料预处理：文件名+简要内容即可验证
    "03-": (6_000, 200),      # 循环次数确定：仅需文件索引
    "04-": (6_000, 200),      # 场景判断：仅需文件索引
    "05-": (120_000, 6_000),  # 病史总结：需要完整临床数据
    "06-": (120_000, 6_000),  # 患者概况：需要完整临床数据 + RAG
    "07-": (120_000, 6_000),  # 治疗方案：需要完整临床数据
    "08-": (120_000, 6_000),  # 疗效预测：需要完整临床数据
    "09-": (120_000, 6_000),  # 其他建议：需要完整临床数据
    "10-": (8_000, 200),      # 报告生成：从前序步骤输出组装
}
# ReAct Agent 最大递归轮次。
# 步骤 06 (patient-profile) 有 10 个子 Agent + 7 次 RAG 检索，每子 Agent 调用消耗
# 2-3 轮（tool call + result），加上主 Agent 思考轮次，50 轮可能不足。
# 提升至 100 以确保复杂 Skill 不会因递归轮次耗尽而失败。
SKILL_RECURSION_LIMIT = 50

# 按步骤分级的递归上限。
# platform.yaml parallel_tool_calls=false → 每轮仅 1 个工具调用。
# 步骤 01 (资料整理，21文件 read+组织)：25 轮。
# 步骤 02 (资料预处理，batch_pdf_to_md + 逐文件验证 + 质量报告)：30 轮。
# 步骤 03-04 (循环次数/场景判断)：20 轮。
# 步骤 05 (病史总结，逐文件提取)：25 轮。
# 步骤 06 (患者概况，10 子Agent + RAG)：100 轮。
# 步骤 10 (报告生成组装)：15 轮。
_STEP_RECURSION_LIMITS: dict[str, int] = {
    "01-data-organization": 20,
    "02-data-preprocessing": 20,
    "03-loop-count-determination": 40,
    "04-scenario-judgment": 40,
    "05-patient-history-summary": 40,
    "06-patient-profile": 50,
    "07-treatment-plan": 40,
    "08-efficacy-prediction": 35,
    "09-other-suggestions": 30,
    "10-report-generation": 20,
}

# 不需要知识库注入的轻量预处理步骤。
# 步骤 01-04 的 SKILL.md 不包含任何 RAG 检索指令，注入 KB 知识仅增加 LLM 处理耗时。
_NO_KB_STEP_PREFIXES = ("01-", "02-", "03-", "04-")

# Web 端报告生成时，患者 OCR Markdown 已由路由预读取。01-04 是内部资料整理/
# 预处理步骤，不直接产出前端报告页签；默认跳过可显著缩短报告生成时间。
_INTERNAL_PREP_STEP_PREFIXES = ("01-", "02-", "03-", "04-")

# Pipeline step → 前端 TabName 映射
# 步骤 1-4 为内部预处理步骤，不生成标签页
# 步骤 5-9 映射到前端 5 个报告标签页
# 步骤 10 为最终报告组装，不单独生成标签页
_STEP_TO_TAB: dict[str, str] = {
    "05-patient-history-summary": "patient-history",
    "06-patient-profile":         "patient-overview",
    "07-treatment-plan":          "treatment-plan",
    "08-efficacy-prediction":     "efficacy-prediction",
    "09-other-suggestions":       "suggestions",
}


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

# 步骤→依赖映射：当前步骤需要哪些前序步骤的输出
# 只传直接相关的步骤，避免全量 pipeline_results 序列化/截断浪费
_PREV_STEP_DEPS: dict[str, list[str]] = {
    "02-": ["01-"],                           # 资料预处理 ← 资料整理
    "03-": ["02-"],                           # 循环次数 ← 预处理
    "04-": ["02-", "03-"],                    # 场景判断 ← 预处理 + 循环次数
    "05-": ["02-"],                           # 病史总结 ← 预处理（病史从 files_text 提取）
    "06-": ["05-"],                           # 患者概况 ← 病史总结
    "07-": ["05-", "06-"],                    # 治疗方案 ← 病史 + 概况
    "08-": ["05-", "06-", "07-"],             # 疾病预测 ← 病史 + 概况 + 方案
    "09-": ["05-", "06-", "07-", "08-"],      # 健康建议 ← 全部临床输出
    "10-": ["05-", "06-", "07-", "08-", "09-"],  # 报告生成 ← 全部临床输出
}
_PREV_SUMMARY_MAX_CHARS = 3000
_PREV_FIELD_MAX_CHARS = 400  # 单个字段截断上限
_PRIOR_REPORT_STEP_PREFIXES = ("05-", "06-", "07-", "08-", "09-")


def _build_previous_summary(
    pipeline_results: dict,
    current_step_name: str,
    max_chars: int = _PREV_SUMMARY_MAX_CHARS,
) -> str:
    """构建当前步骤需要的上一步内容摘要。

    与旧方案（全量 pipeline_results JSON 序列化 → agent_manager 检测截断）不同：
    1. 只提取当前步骤实际依赖的前序步骤输出
    2. 保留内容字段（summary/history/plan/prognosis 等），而非仅元数据
    3. 单字段截断到 _PREV_FIELD_MAX_CHARS，总 JSON 控制在 max_chars 内

    Args:
        pipeline_results: 所有已完成步骤的输出 {step_name: result_json}
        current_step_name: 当前步骤名（如 "05-patient-history-summary"）
        max_chars: 摘要 JSON 的最大字符数（默认 3000，agent_manager 不会再次截断）

    Returns:
        格式化后的 previous_results JSON 字符串
    """
    # 查找匹配的依赖前缀
    deps: list[str] = []
    for prefix, dep_list in _PREV_STEP_DEPS.items():
        if current_step_name.startswith(prefix):
            deps = dep_list
            break
    if not deps:
        # 无匹配依赖，返回空
        deps = []

    summary: dict = {}
    for dep_prefix in deps:
        for key, value in pipeline_results.items():
            if key.startswith(dep_prefix):
                entry: dict = {}
                for field, field_value in value.items():
                    if field.startswith("_"):
                        continue  # 跳过 _content / _raw 等内部字段
                    if isinstance(field_value, str):
                        if len(field_value) > _PREV_FIELD_MAX_CHARS:
                            entry[field] = field_value[:_PREV_FIELD_MAX_CHARS] + "..."
                        else:
                            entry[field] = field_value
                    elif isinstance(field_value, (list, dict)):
                        s = json.dumps(field_value, ensure_ascii=False)
                        if len(s) > _PREV_FIELD_MAX_CHARS:
                            entry[field] = s[:_PREV_FIELD_MAX_CHARS] + "..."
                        else:
                            entry[field] = field_value
                    else:
                        entry[field] = field_value
                if entry:
                    summary[key] = entry
                break

    result = json.dumps(summary, ensure_ascii=False)
    if len(result) > max_chars:
        # 超限时降级：只保留 display_name + step，最后 3 个步骤的简短摘要
        fallback: dict = {}
        keys = list(summary.keys())[-3:]
        for k in keys:
            fb_entry = {"step": summary[k].get("step", k),
                        "display_name": summary[k].get("display_name", "")}
            # 保留第一个非空内容字段的前 200 字符
            for field in ("summary", "history", "overview", "plan", "prognosis", "recommendations"):
                content = summary[k].get(field, "")
                if content and isinstance(content, str) and len(content.strip()) > 10:
                    fb_entry["content_preview"] = content.strip()[:200] + "..."
                    break
            fallback[k] = fb_entry
        result = json.dumps(fallback, ensure_ascii=False)
    return result


def _file_category_summary(files: list[dict]) -> str:
    """统计患者资料分类摘要（按文件所在目录自动归类，不假定业务分类体系）。"""
    counts: dict[str, int] = {}
    for file in files:
        name = str(file.get("name", ""))
        # 自动从文件路径提取父目录作为类别
        parts = name.replace("\\", "/").split("/")
        if len(parts) >= 2 and not parts[-2].startswith("["):
            category = parts[-2]
        elif len(parts) >= 2:
            category = parts[-2].split("]")[-1].strip() or "OCR资料"
        else:
            category = "OCR资料" if file.get("content") else "资料"
        counts[category] = counts.get(category, 0) + 1
    if not counts:
        return "暂无可解析文件"
    total = len(files)
    details = "、".join(f"{key}{value}份" for key, value in counts.items())
    return f"共{total}份（{details}）"


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
    *,
    ocr_ready: bool = False,
) -> str:
    """把患者文件列表渲染成有上限的可读文本。

    ocr_ready=True 时在头部添加 OCR 完成标记，告知 Agent 无需执行 PDF 转换。
    """
    if not files:
        return "（无可用患者文件）"
    parts: list[str] = []
    # OCR 就绪信号：让 Agent 明确知道无需 PDF 转换，直接使用已有文本
    if ocr_ready:
        parts.append(
            "## ⚠️ OCR 状态：已完成\n"
            "以上文本已从 PDF 提取为 Markdown 格式，内容可直接用于临床分析。\n"
            "请直接使用这些数据，不要再执行 PDF 转换或 batch_pdf_to_md 操作。"
        )
    used = sum(len(p) for p in parts)
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


def _has_loaded_ocr_content(files: list[dict]) -> bool:
    """判断路由是否已把 OCR Markdown 内容加载到内存。"""
    return any(str(file.get("content", "")).strip() for file in files)


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
                + f"\n{r['content'][:350]}"
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
    def _is_step_specific_error(error: Exception) -> bool:
        """判断错误是否为单个 Skill 的问题（不应当连锁禁用后续步骤）。

        仅 LLM 基础设施不可用（认证/频率限制/服务异常/超时/网络故障）才应当禁用后续步骤。
        Agent 递归上限、上下文超限、未知调用失败 都是单步骤的问题。
        """
        text = str(error).lower()
        # 这些是基础设施问题，应连锁禁用 → 返回 False
        if any(kw in text for kw in ("401", "403", "authentication", "invalid api key",
                                       "forbidden", "access denied")):
            return False  # 认证失败 → 连锁禁用
        if "timeout" in text or isinstance(error, TimeoutError):
            return False  # 超时 → 连锁禁用
        if any(kw in text for kw in ("429", "rate limit", "quota")):
            return False  # 频率限制 → 连锁禁用
        if any(kw in text for kw in ("500", "502", "503", "server error", "service unavailable")):
            return False  # 服务异常 → 连锁禁用
        if any(kw in text for kw in ("connection", "network", "dns", "refused", "proxy")):
            return False  # 网络故障 → 连锁禁用
        # 其他所有情况（Agent 递归耗尽、上下文超限、未知错误）都是单步骤问题
        return True

    @staticmethod
    def _classify_llm_error(error: Exception) -> str:
        text = str(error)
        lower = text.lower()
        # 1. 认证/鉴权错误
        if any(kw in lower for kw in ("401", "403", "invalid api key", "autherror",
                                        "authentication", "forbidden", "access denied",
                                        "error code: 1010")):
            return "认证失败"
        # 2. 超时
        if "timeout" in lower or isinstance(error, TimeoutError):
            return "调用超时"
        # 3. LangGraph 递归上限 / Agent 未能在 N 轮内完成
        if any(kw in lower for kw in ("graphrecursion", "recursion limit", "agent 未能在")):
            return "ReAct 达到递归上限"
        # 4. 上下文长度超限
        if any(kw in lower for kw in ("context length", "maximum context", "too many token",
                                        "token limit", "max_token", "context_length_exceeded",
                                        "reduce the length")):
            return "上下文超限（请减少输入量）"
        # 5. 频率限制
        if any(kw in lower for kw in ("429", "rate limit", "too many request",
                                        "rate_limit", "quota")):
            return "请求频率限制"
        # 6. 服务端错误
        if any(kw in lower for kw in ("500", "502", "503", "server error", "internal error",
                                        "service unavailable", "bad gateway")):
            return "LLM 服务异常"
        # 7. 网络/连接错误
        if any(kw in lower for kw in ("connection", "network", "dns", "refused",
                                        "unreachable", "proxy", "ssl", "tls")):
            return "网络连接失败"
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

    # LangGraph recursion_limit 耗尽时的典型无效输出
    _INVALID_OUTPUT_PATTERNS = (
        "sorry, need more steps",
        "i need more steps",
        "need more steps to process",
        "i need more information",
        "i don't have enough information",
    )

    @classmethod
    def _is_invalid_agent_output(cls, text: str) -> bool:
        """检测 LangGraph Agent 的无效 fallback 输出。"""
        lower = text.lower().strip()
        if len(lower) < 80:
            # 短文本更可能是占位消息，逐一匹配
            for pattern in cls._INVALID_OUTPUT_PATTERNS:
                if pattern in lower:
                    return True
        return False

    @staticmethod
    def _json_to_markdown(data: dict, title: str = "") -> str:
        """将 JSON dict 转为可读 Markdown 文本，供前端 Markdown 回退渲染。"""
        lines: list[str] = []
        if title:
            lines.append(f"## {title}\n")
        for key, value in data.items():
            # 跳过元数据和内部字段（_开头为内部），
            # 但保留 summary / result 等实际内容字段。
            if key in ("_raw", "status", "error", "step", "display_name"):
                continue
            if key.startswith("_"):
                continue
            if isinstance(value, str):
                if value:
                    lines.append(f"### {key}\n\n{value}\n")
            elif isinstance(value, list):
                lines.append(f"### {key}\n")
                for item in value:
                    if isinstance(item, dict):
                        parts = [f"**{k}**: {v}" for k, v in item.items() if v is not None]
                        lines.append(f"- {' | '.join(parts)}")
                    else:
                        lines.append(f"- {item}")
                lines.append("")
            elif isinstance(value, dict):
                lines.append(f"### {key}\n")
                for k, v in value.items():
                    lines.append(f"- **{k}**: {v}")
                lines.append("")
            elif value is not None:
                lines.append(f"**{key}**: {value}\n")
        return "\n".join(lines) if lines else json.dumps(data, ensure_ascii=False, indent=2)

    @staticmethod
    def _clean_agent_content(md_text: str) -> str:
        """清理 Agent 思考/计划文本混入报告内容的污染。

        Agent 在生成 JSON 时经常附带「现在拥有所有所需信息…」「让我生成…」
        等规划性文字。这些是 Agent 的内部 monologue，不应出现在用户报告里。

        重要：「### result」和「```」仅移除行本身，不触发 monologue 块删除。
        因为「### result」后的内容才是真正的报告正文。
        """
        import re as _re

        # 1. 仅移除该行本身（不触发块删除）的轻量模式
        _LINE_REMOVE_PATTERNS = [
            r"^###\s*result\s*$",       # "### result" 空标题（_json_to_markdown 已跳过 result 键，此处为冗余安全网）
            r"^```\s*$",                 # 孤立的代码块标记
        ]
        _LINE_REMOVE_REGEX = _re.compile("|".join(_LINE_REMOVE_PATTERNS))
        _STRUCTURED_OUTPUT_REGEX = _re.compile(
            r"^(?:#{1,6}\s*)?(?:[一二三四五六七八九十]+[、.．]\s*)?"
            r"(?:完整结构化输出|合并输出JSON|结构化输出|JSON\s*输出)\s*$",
            _re.IGNORECASE,
        )

        # 2. 触发 monologue 块删除的模式（该行及后续非标题行全部移除）
        _AGENT_MONOLOGUE_PATTERNS = [
            r"^现在拥有所有所需信息",
            r"^让我生成",
            r"^报告已成功生成并保存",
            r"^子Agent调用遇到限制",
            r"^好的，我基于对患者",
            r"^报告已写入",
            r"^##\s*✅\s*治疗方案已生成",
            r"^>\s*\*\*完整报告已保存至",
            r"^##\s*✅",
            r"^第.*步（子Agent",
        ]
        _MONOLOGUE_REGEX = _re.compile("|".join(_AGENT_MONOLOGUE_PATTERNS))

        cleaned_lines: list[str] = []
        in_monologue_block = False

        for line in md_text.splitlines():
            stripped = line.strip()

            # 「完整结构化输出」之后通常是给程序消费的 JSON，不应进入前端报告正文。
            if _STRUCTURED_OUTPUT_REGEX.match(stripped):
                break
            if stripped.lower().startswith("```json"):
                break

            # 仅移除该行（不触发块删除）
            if _LINE_REMOVE_REGEX.match(stripped):
                continue

            # 检测 Agent monologue 块开头
            if _MONOLOGUE_REGEX.match(stripped):
                in_monologue_block = True
                continue

            if in_monologue_block:
                # monologue 块在空行或下一个标题处结束
                if not stripped or stripped.startswith("#"):
                    in_monologue_block = False
                    # 标题行保留（可能是有效内容）
                    if stripped.startswith("#"):
                        cleaned_lines.append(stripped)
                # 非标题行在 monologue 块中 → 跳过
                continue

            # 移除内嵌的 "完整报告已保存至..." 引用
            cleaned = _re.sub(
                r"\n?>?\s*\*?\*?\*?完整报告已保存至.*$", "", stripped
            ).strip()
            if cleaned:
                cleaned_lines.append(cleaned)

        return "\n".join(cleaned_lines)

    # ── Markdown → 结构化 JSON 提取 ──
    # 当 LLM 输出为 Markdown 而非 JSON 时，尝试从标题中提取结构化字段。
    # 匹配逻辑：按 ## 标题拆分 Markdown，将标题文本映射到对应的结构化字段名。
    _HEADING_TO_FIELD_MAP: dict[str, dict[str, str]] = {
        "05-patient-history-summary": {
            "主诉": "chief_complaint", "现病史": "present_illness",
            "既往史": "past_history", "过敏史": "allergy_history",
            "个人史": "personal_history", "家族史": "family_history",
            "治疗史": "treatment_history", "基本信息": "patient_info",
        },
        "06-patient-profile": {
            "主诉": "chief_complaint", "体格检查": "physical_examination",
            "辅助检查": "auxiliary_examination", "诊断": "diagnosis",
            "AI 肿瘤负荷": "ai_tumor_burden", "肿瘤负荷": "ai_tumor_burden",
            "AI 疗效": "ai_efficacy", "疗效评估": "ai_efficacy",
            "AI 不良反应": "ai_adverse_events", "不良反应": "ai_adverse_events",
            "合并症": "ai_comorbidity", "ECOG": "ecog_score",
        },
        "07-treatment-plan": {
            "治疗": "treatment_plans", "AI 治疗": "treatment_plans",
            "不良反应处理": "adverse_reaction_plan", "合并症处理": "comorbidity_plan",
            "临床": "clinical_trials",
        },
        "08-efficacy-prediction": {
            "肿瘤": "tumor_prediction", "疗效预测": "tumor_prediction",
            "不良反应预测": "adverse_prediction", "预后": "prognosis",
        },
        "09-other-suggestions": {
            "心理": "psychological_care", "健康": "health_measures",
            "中医": "tcm_suggestions", "护理": "nursing_care", "随访": "follow_up_plan",
        },
    }

    @staticmethod
    def _extract_structured_from_markdown(markdown_text: str, step_name: str) -> dict | None:
        """当 LLM 输出为 Markdown 而非 JSON 时，尝试提取结构化字段。
        返回 None 表示无法提取，调用方应走原有 fallback 逻辑。
        """
        import re as _re
        mapping = SkillExecutor._HEADING_TO_FIELD_MAP.get(step_name)
        if not mapping:
            return None
        if not markdown_text or len(markdown_text) < 100:
            return None

        result: dict = {"step": step_name, "_content": SkillExecutor._clean_agent_content(markdown_text)}
        found_any = False

        # 按 ## 标题拆分 Markdown 段落
        sections = _re.split(r'\n(?=#{1,3}\s+)', markdown_text)
        for section in sections:
            m = _re.match(r'^#{1,3}\s+([^\n]+)', section)
            if not m:
                continue
            heading = m.group(1).strip()
            # 去除标题中的 emoji 和编号前缀
            clean_heading = _re.sub(r'[^一-鿿\w\s]', '', heading).strip()
            # 去除编号（一、二、1. 等）
            clean_heading = _re.sub(r'^[一二三四五六七八九十]+[、.．]?\s*', '', clean_heading)
            clean_heading = _re.sub(r'^\d+[、.．]?\s*', '', clean_heading)

            # 匹配已知字段
            for pattern, field_name in mapping.items():
                if pattern in clean_heading or clean_heading == pattern:
                    body = section[m.end():].strip()
                    body = SkillExecutor._clean_agent_content(body)
                    if body and len(body) > 10:
                        # 不覆盖已有内容
                        if field_name not in result or len(body) > len(str(result.get(field_name, ''))):
                            result[field_name] = body
                        found_any = True
                    break

        return result if found_any else None

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
            "trust_env_proxy": os.environ.get("MEDAGENT_LLM_TRUST_ENV_PROXY", "").lower() in ("1", "true", "yes"),
            "proxy_env_present": any(os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")),
        }

    # ── Skill 执行 ──

    async def _run_skill_with_llm_candidates(self, skill: SkillDef, args: dict) -> str:
        """执行 Skill，自动路由多个 LLM 候选（认证失败/超时自动切换）。
        
        对瞬态错误（速率限制/服务端错误）自动重试 1 次，降低"LLM 调用失败"概率。
        """
        candidates = self._llm_candidates or [None]
        last_error: Exception | None = None
        for candidate in candidates:
            provider = candidate.get("name", "平台默认 LLM") if candidate else "平台默认 LLM"
            if provider in self._disabled_providers:
                continue
            if candidate:
                self._apply_llm_candidate(candidate)
            # 瞬态错误重试：每个 provider 最多尝试 2 次
            for attempt in (1, 2):
                try:
                    return await asyncio.wait_for(
                        self._run_skill_via_agent(skill, args, candidate, provider),
                        timeout=LLM_TAB_TIMEOUT_SECONDS,
                    )
                except TimeoutError as e:
                    last_error = e
                    logger.warning("LLM provider %s timed out for skill %s (attempt %d)", provider, skill.name, attempt)
                    break  # 超时跳出 provider，下次还可尝试
                except Exception as e:
                    last_error = e
                    kind = self._classify_llm_error(e)
                    logger.warning(
                        "LLM provider %s failed for skill %s: %s (%s: %.200s) (attempt %d)",
                        provider, skill.name, kind, type(e).__name__, str(e), attempt,
                    )
                    if kind == "认证失败":
                        self._disabled_providers.add(provider)
                        break  # 认证失败不重试
                    if "Agent 未能在" in str(e):
                        raise  # 递归耗尽不重试——直接抛出
                    if attempt == 1 and kind in ("请求频率限制", "调用超时", "LLM 服务异常", "网络连接失败"):
                        await asyncio.sleep(3)
                        continue  # 瞬态错误重试 1 次
                    # Agent 递归上限 / 上下文超限：不可恢复的步骤级错误
                    # 直接抛出原始异常，不包装为 "所有 LLM 均已失效"
                    # 否则 execute_report_skills 会将 GraphRecursionError 误判为 "调用失败"
                    if kind in ("ReAct 达到递归上限", "上下文超限（请减少输入量）"):
                        raise
                    break  # 其他错误放弃当前 provider
        if last_error:
            raise RuntimeError(f"{self._classify_llm_error(last_error)}，已尝试：{self._candidate_names()}")
        raise RuntimeError(f"没有可用 LLM 候选，已尝试：{self._candidate_names()}")

    async def _run_skill_via_agent(self, skill: SkillDef, args: dict,
                                   candidate: dict | None, provider: str) -> str:
        """通过 AgentManager 执行 Skill（替换旧版 _run_skill_single_shot）。

        旧版直接调用 AsyncOpenAI → Skill 无法使用工具/子Skill/子Agent。
        新版委托给 AgentManager.run_skill() → 完整的 LangGraph ReAct Agent 生命周期。
        """
        import json as _json

        from DataCode.skill_parser import SkillParser

        config = getattr(self._agent_manager, "_config", None)
        base_url = (candidate or {}).get("base_url") or (config.get("llm.base_url", "") if config else "")
        model = (candidate or {}).get("model") or (config.get("llm.default_model", "") if config else "")
        api_key = (candidate or {}).get("api_key") or (config.get("llm.api_key", "") if config else "")
        agent_name = f"skill:{skill.name}:{provider}"

        # 解析 body 用于 tracker
        parser = SkillParser()
        body = parser.resolve_vars(skill.body, args, skill_dir=skill.skill_dir)

        tracker = LLMCallTracker.instance()
        call_id = tracker.start(agent=agent_name, model=model, base_url=base_url,
                                api_key=api_key, prompt=body, kind="chat")

        try:
            # 委托给 AgentManager.run_skill() — Skill 将拥有完整的工具/子Agent 能力
            # 递归上限按步骤分级：轻量步骤用小值减少无效循环，重量步骤保持高值
            step_limit = _STEP_RECURSION_LIMITS.get(skill.name, SKILL_RECURSION_LIMIT)
            raw_result = await self._agent_manager.run_skill(skill, args, recursion_limit=step_limit)

            # 检测 LangGraph recursion_limit 耗尽时的无效 fallback 消息
            # （Agent 未给出有效答案，LangGraph 返回默认占位文本）
            stripped = str(raw_result).strip()
            if self._is_invalid_agent_output(stripped):
                raise RuntimeError(
                    f"Agent 未能在 {step_limit} 轮内完成 Skill {skill.name}，"
                    f"输出无效：{stripped[:200]}"
                )

            tracker.succeed(call_id, raw_result)

            # 尝试解析为 JSON；若失败则包装为 JSON
            try:
                parsed = _json.loads(self._extract_json(str(raw_result)))
                return _json.dumps(parsed, ensure_ascii=False)
            except Exception:
                return _json.dumps(
                    {"step": skill.name, "result": str(raw_result)},
                    ensure_ascii=False,
                )
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
            "你是一个 AI 辅助分析助手。以下「已加载的患者资料」是系统已预读取的真实患者数据，"
            "请直接基于这些资料用简体中文给出专业、严谨的回答。"
            "若资料中确实缺乏某项信息请明确说明，不要捏造数据。"
        )
        summary = _file_category_summary(files)
        files_preview = _format_files_for_prompt(files, total_budget=15000, per_file_budget=800)
        data_block = (
            f"患者编号: {patient_id}\n"
            f"资料统计: {summary}\n\n"
            f"--- 已加载的患者资料（共 {len(files)} 份）---\n\n"
            f"{files_preview}"
        )
        messages: list[dict] = [{"role": "system", "content": sys_prompt}]
        # 将文件内容放在 user 消息中而非 system prompt，确保模型将其视为对话上下文
        for entry in (history or [])[-8:]:
            role = entry.get("role")
            content = str(entry.get("content", "")).strip()
            if not content:
                continue
            if role == "user":
                messages.append({"role": "user", "content": content})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": f"{data_block}\n\n用户问题: {message}"})
        return messages

    @staticmethod
    def _build_chat_fallback(patient_id: str, files: list[dict], message: str, reason: str) -> str:
        summary = _file_category_summary(files)
        files_preview = _format_files_for_prompt(files, total_budget=10000, per_file_budget=600)
        return (
            f"【离线模式】当前未能调用大模型（{reason}），以下是已加载的患者资料本地摘要，仅供参考。\n\n"
            f"患者编号: {patient_id}\n"
            f"资料统计: {summary}\n\n"
            f"--- 已加载的患者资料（共 {len(files)} 份）---\n\n"
            f"{files_preview}\n\n"
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

        config = getattr(self._agent_manager, "_config", None)
        chat_temp = config.get("llm.chat_temperature", config.get("llm.temperature", 0.7)) if config else 0.7

        client = AsyncOpenAI(
            api_key=api_key or "dummy",
            base_url=base_url or None,
            default_headers={"User-Agent": "curl/8.17.0"},
            http_client=make_async_llm_http_client(),
        )

        async def _do_stream() -> AsyncIterator[dict]:
            stream = await client.chat.completions.create(
                model=model, messages=messages, temperature=chat_temp, stream=True,
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
        prior_reports: str = "",
        patient_dir: str = "",
    ) -> AsyncIterator[dict]:
        """执行报告生成流水线（支持 Tab 并行 / Pipeline 串行 两种模式）。"""
        self.reset_disabled_providers()
        event_id = 1
        yield {"id": event_id, "event": "status", "data": {"state": "reading_files"}}

        # 确定流水线步骤。默认 Web 报告模式走快速路径：患者 OCR 文本已加载时，
        # 跳过 01-04 内部预处理步骤，只执行真正产出报告页签的 05-09 和汇总 10。
        steps = self._pipeline_steps
        if not steps:
            event_id += 1
            yield {"id": event_id, "event": "error", "data": {
                "message": "流水线未配置。请在 skills/pipeline.yaml 中注册步骤。"
            }}
            event_id += 1
            yield {"id": event_id, "event": "done", "data": {}}
            return
        full_pipeline = os.environ.get("MEDAGENT_FULL_PIPELINE", "").lower() in ("1", "true", "yes")
        skipped_internal_steps: list[PipelineStep] = []
        if not full_pipeline and _has_loaded_ocr_content(files):
            skipped_internal_steps = [
                step for step in steps
                if any(step.name.startswith(prefix) for prefix in _INTERNAL_PREP_STEP_PREFIXES)
            ]
            steps = [
                step for step in steps
                if not any(step.name.startswith(prefix) for prefix in _INTERNAL_PREP_STEP_PREFIXES)
            ]
            if skipped_internal_steps:
                logger.info(
                    "Fast report mode: skipped internal prep steps=%s patient=%s files=%d",
                    [step.name for step in skipped_internal_steps], patient_id, len(files),
                )

        # KB 查询
        knowledge_results: list[dict] = []
        kb_query = " ".join(
            kw for step in steps for kw in step.keywords[:3]
        ) or "诊疗 指南 评估"
        try:
            kb_top_k = max(3, min(15, int(os.environ.get("MEDAGENT_KB_TOP_K", "8"))))
            knowledge_results = await self._kb.query(question=kb_query, top_k=kb_top_k, before_date=visit_date)
            knowledge_text = self._format_knowledge(knowledge_results)
            # 缓存到 app_state
            from DataCode.web_server import _app_state
            cache = _app_state.setdefault("trace_cache", {})
            cache[patient_id] = knowledge_results
            # 批量评分缓存：避免多个步骤对同一 KB 结果重复评分
            _kw_score_cache: dict[str, list[tuple]] = {}
            for step in steps:
                kw_key = tuple(sorted(step.keywords))
                if kw_key not in _kw_score_cache:
                    scored = [(r, _score_result_for_step(r, step.keywords)) for r in knowledge_results]
                    scored.sort(key=lambda x: x[1], reverse=True)
                    _kw_score_cache[kw_key] = scored
                else:
                    scored = _kw_score_cache[kw_key]
                step_results = [r for r, s in scored if s > 0]
                cache[f"{patient_id}:{step.name}"] = step_results if step_results else knowledge_results[:2]
        except Exception as e:
            logger.exception("Knowledge query failed")
            knowledge_text = f"知识库查询失败：{e}"

        # 串行执行流水线步骤
        # 步骤感知文件文本：按步骤复杂度分配不同粒度的患者资料
        # - 轻量步骤(01-04, 10)：文件摘要/索引 → 减少 LLM 每轮上下文体积 ~80%
        # - 重量步骤(05-09)：完整临床数据 → 保证医学分析精度
        _files_text_cache: dict[str, str] = {}

        def _get_files_text_for_step(step_name: str) -> str:
            prefix = step_name[:3]
            total, per_file = _STEP_FILES_BUDGETS.get(prefix, (SKILL_FILES_CHAR_BUDGET, SKILL_PER_FILE_CHAR_BUDGET))
            cache_key = f"{total}:{per_file}"
            if cache_key not in _files_text_cache:
                # OCR 文件已预加载 — 始终添加 OCR 完成标记（只要有文件内容就是 OCR 已完成）
                has_content = any(f.get("content", "").strip() for f in files)
                _files_text_cache[cache_key] = _format_files_for_prompt(
                    files, total_budget=total, per_file_budget=per_file, ocr_ready=has_content,
                )
            return _files_text_cache[cache_key]

        llm_disabled_note = ""
        pipeline_results: dict = {}
        step_timings: list[dict] = [
            {
                "step": step.name,
                "display_name": step.display_name,
                "elapsed_s": 0,
                "status": "skipped",
                "error": "fast_report_mode: OCR 已加载，跳过内部预处理步骤",
            }
            for step in skipped_internal_steps
        ]
        pipeline_start = time.time()

        for step in steps:
            step_start = time.time()
            skill = self._skills.get(step.name)
            fallback_note = ""
            result_json: dict | None = None

            if step.name == "10-report-generation":
                report_tabs = {
                    tab_name: pipeline_results[step_name]
                    for step_name, tab_name in _STEP_TO_TAB.items()
                    if step_name in pipeline_results
                }
                result_json = {
                    "step": step.name,
                    "display_name": step.display_name,
                    "status": "assembled",
                    "summary": f"已汇总 {len(report_tabs)} 个报告页签。",
                    "tabs": list(report_tabs.keys()),
                }
                pipeline_results[step.name] = result_json

                event_id += 1
                yield {"id": event_id, "event": "token", "data": {"content": f"已完成{step.display_name}（本地汇总）\n"}}

                step_elapsed = time.time() - step_start
                step_timings.append({
                    "step": step.name,
                    "display_name": step.display_name,
                    "elapsed_s": round(step_elapsed, 2),
                    "status": "assembled",
                    "error": None,
                })
                logger.info("Step %s completed in %.1fs (status=assembled)", step.name, step_elapsed)
                continue

            # 轻量预处理步骤（01-04）不注入知识库：其 SKILL.md 不含 RAG 检索指令，
            # 注入 KB 知识仅增加 system prompt 体积和 LLM 处理耗时，无业务收益。
            is_lightweight_step = any(step.name.startswith(p) for p in _NO_KB_STEP_PREFIXES)
            step_knowledge = "" if is_lightweight_step else knowledge_text

            if llm_disabled_note:
                fallback_note = llm_disabled_note
            elif skill:
                try:
                    # 构建 previous_results：按需摘要（只传当前步骤依赖的前序步骤输出）
                    # 替代旧方案的全量 pipeline_results 序列化 + agent_manager 截断
                    prev_summary = _build_previous_summary(pipeline_results, step.name)
                    result_text = await self._run_skill_with_llm_candidates(
                        skill,
                        args={
                            "files": _get_files_text_for_step(step.name),
                            "patient_id": patient_id,
                            "message": message,
                            "knowledge": step_knowledge,
                            "visit_date": visit_date,
                            "previous_results": prev_summary,
                            "prior_reports": prior_reports if step.name.startswith(_PRIOR_REPORT_STEP_PREFIXES) else "",
                        },
                    )
                    result_json = json.loads(result_text)
                    # 生成可读 Markdown 文本供前端 Tab 回退渲染
                    # （避免前端拿到 JSON 字符串无法渲染）
                    raw_md = self._json_to_markdown(result_json, step.display_name)
                    result_json["_content"] = self._clean_agent_content(raw_md)
                except TimeoutError:
                    fallback_note = f"LLM 调用超过 {LLM_TAB_TIMEOUT_SECONDS} 秒"
                    logger.warning("Step %s timed out", step.name)
                except json.JSONDecodeError:
                    # JSON 解析失败，尝试从 Markdown 中提取结构化字段
                    extracted = self._extract_structured_from_markdown(result_text or "", step.name)
                    if extracted and len(extracted) > 2:
                        extracted["_content"] = self._clean_agent_content(
                            self._json_to_markdown(extracted, step.display_name))
                        result_json = extracted
                        fallback_note = None
                        logger.info("Step %s: extracted %d structured fields from markdown (len=%d)",
                                    step.name, len(extracted) - 2, len(result_text))
                    else:
                        fallback_note = "LLM 输出非有效 JSON（已保留原始文本）"
                        result_json = {
                            "step": step.name,
                            "display_name": step.display_name,
                            "_content": self._clean_agent_content(result_text or ""),
                            "result": result_text or "",
                            "status": "markdown",
                        }
                        logger.warning("JSON decode failed for step %s, keeping raw markdown (len=%d)", step.name, len(result_text))
                except Exception as e:
                    fallback_note = f"LLM {self._classify_llm_error(e)}"
                    # 仅在 LLM 基础设施不可用时才禁用后续步骤：
                    # 认证失败 / 频率限制 / 服务异常 / 网络故障 表示 API 本身不可用。
                    # Agent 递归上限 / 上下文超限 / 调用失败 是单个 Skill 的问题，不应当连锁禁用。
                    if not self._is_step_specific_error(e):
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
                result_json["_content"] = (
                    f"## {step.display_name}\n\n"
                    f"> 本页签未能成功生成结构化报告。\n\n"
                    f"**原因**：{fallback_note}\n\n"
                    f"**已读取资料**：{_file_category_summary(files)}\n"
                )

            pipeline_results[step.name] = result_json
            event_id += 1

            # 映射到前端 TabName：仅步骤 5-9 生成标签页
            tab_name = _STEP_TO_TAB.get(step.name)
            if tab_name:
                yield {"id": event_id, "event": "tab_ready", "data": {"tab": tab_name, "data": result_json}}
            event_id += 1
            suffix = f"（{fallback_note}）" if fallback_note else ""
            yield {"id": event_id, "event": "token", "data": {"content": f"已完成{step.display_name}{suffix}\n"}}

            # ── 步骤 timing ──
            step_elapsed = time.time() - step_start
            step_status = "ok" if result_json and result_json.get("status") != "fallback" else "fallback"
            if fallback_note:
                step_status = "error"
            step_timings.append({
                "step": step.name,
                "display_name": step.display_name,
                "elapsed_s": round(step_elapsed, 2),
                "status": step_status,
                "error": fallback_note or None,
            })
            logger.info("Step %s completed in %.1fs (status=%s)", step.name, step_elapsed, step_status)

        # ── Pipeline 汇总 ──
        total_elapsed = time.time() - pipeline_start
        pipeline_summary = {
            "patient_id": patient_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "total_elapsed_s": round(total_elapsed, 2),
            "steps": step_timings,
            "total_files": len(files),
            "successful_report_steps": sum(
                1 for item in step_timings
                if item.get("step") in _STEP_TO_TAB and item.get("status") in ("ok", "markdown")
            ),
        }
        logger.info(
            "Pipeline completed patient=%s total=%.1fs steps=%d files=%d",
            patient_id, total_elapsed, len(step_timings), len(files),
        )
        # 写入 Result/logs/pipeline_*.json
        try:
            from DataCode.web_server import _app_state as _ps_app_state
            project_root = _ps_app_state.get("project_root", ".")
            pipeline_log_dir = Path(project_root) / "Result" / "logs"
            pipeline_log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pipeline_log = pipeline_log_dir / f"pipeline_{patient_id}_{ts}.json"
            pipeline_log.write_text(
                json.dumps(pipeline_summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to write pipeline summary log")

        # 流水线完成后，将 Tab 数据保存到磁盘（供下载和刷新加载）
        report_for_save: dict[str, object] = {}
        for step_name, step_result in pipeline_results.items():
            tab_name = _STEP_TO_TAB.get(step_name)
            if tab_name and isinstance(step_result, dict):
                report_for_save[tab_name] = step_result
        if report_for_save:
            try:
                from pathlib import Path as _Path
                from DataCode.web_server import _app_state as _res_app_state
                reports_root = _Path(_res_app_state.get("reports_dir", "Result"))
                report_file = reports_root / patient_id / "report.json"
                report_file.parent.mkdir(parents=True, exist_ok=True)
                report_file.write_text(
                    json.dumps(report_for_save, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info("Report saved: %s (%d tabs)", report_file, len(report_for_save))
                successful_tabs = [
                    tab for tab, data in report_for_save.items()
                    if isinstance(data, dict) and data.get("status") not in ("fallback", "error")
                ]
                if successful_tabs:
                    self._write_generated_report_context(
                        patient_id=patient_id,
                        report=report_for_save,
                        visit_date=visit_date,
                        patient_dir=patient_dir or str(_Path(_res_app_state.get("patients_dir", "TempData/patients")) / patient_id),
                    )
                else:
                    logger.warning(
                        "Skip generated report context archive for %s visit_date=%s: no successful report tabs",
                        patient_id, visit_date,
                    )
            except Exception:
                logger.exception("Failed to save report for %s", patient_id)

        if knowledge_results and os.environ.get("MEDAGENT_CLEAN_KB_CACHE", "").lower() in ("1", "true", "yes"):
            asyncio.create_task(self._background_clean_cache(patient_id, knowledge_results))

        event_id += 1
        yield {"id": event_id, "event": "done", "data": {}}

    @staticmethod
    def _write_generated_report_context(
        patient_id: str,
        report: dict[str, object],
        visit_date: str,
        patient_dir: str,
    ) -> None:
        """Persist the current report as prior context for later timepoints."""

        if not visit_date or len(visit_date) != 10:
            logger.info("Skip prior-context archive for %s: invalid visit_date=%s", patient_id, visit_date)
            return
        try:
            from pathlib import Path as _Path
            from DataCode.report_context import (
                generated_report_bucket_date,
                report_to_prior_json,
                write_generated_report_json,
                write_generated_report_markdown,
            )
            from DataCode.report_generator import REPORT_TITLE, report_to_markdown

            pdir = _Path(patient_dir)
            patient_name = patient_id.rsplit("-", 1)[0] if "-" in patient_id else patient_id
            patient_info = {
                "id": patient_id,
                "patient_id": patient_id,
                "name": patient_name,
                "visit_date": visit_date,
                "date": visit_date,
            }
            markdown = report_to_markdown(report, REPORT_TITLE, patient_info)
            md_path = write_generated_report_markdown(
                pdir,
                visit_date,
                markdown,
                patient_name=patient_name,
                patient_id=patient_id,
            )
            bucket_date = generated_report_bucket_date(pdir, visit_date)
            prior_json = report_to_prior_json(
                report,
                source_date=visit_date,
                bucket_date=bucket_date,
                encounter_type="selected",
            )
            json_path = write_generated_report_json(
                pdir,
                visit_date,
                prior_json,
                patient_name=patient_name,
                patient_id=patient_id,
            )
            logger.info("Generated report context archived: md=%s json=%s", md_path, json_path)
        except Exception:
            logger.exception("Failed to archive generated report context for %s", patient_id)

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
