#!/usr/bin/env python3
"""
医学知识库 Tool 层 — 对 kb_manager 检索引擎的业务封装
供 Agent 通过 function calling 调用，也可独立使用

用法:
  from tool import search_guidelines, get_source_context
  results = search_guidelines("EGFR 19del 一线治疗", top_k=10)
  results = search_guidelines("NSCLC脑转移", source_orgs=["NCCN","CSCO"])
"""
import sys
import re
import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent))
from kb_manager import (
    query_knowledge as _rag_query,
    get_source_document,
    find_chunk_in_document,
    get_chunk_page,
    show_status,
)

logger = logging.getLogger("tool")
LAST_SEARCH_TRACE: dict[str, Any] = {}
_TOOL_CACHE: dict[str, str] = {}


# ══════════════════════════════════════════════════════
#  查询解析
# ══════════════════════════════════════════════════════

# 低频医学实体 → 英文同义词扩展（解决 Case 5 类问题）
CLINICAL_SYNONYMS = {
    "内脏静脉血栓": ["splanchnic vein thrombosis", "portal vein thrombosis", "mesenteric vein thrombosis", "visceral vein thrombosis"],
    "腹腔静脉血栓": ["splanchnic vein thrombosis", "portal vein thrombosis", "mesenteric vein thrombosis"],
    "内脏血栓": ["splanchnic vein thrombosis", "visceral vein thrombosis"],
    "门静脉血栓": ["portal vein thrombosis"],
    "肠系膜静脉血栓": ["mesenteric vein thrombosis", "superior mesenteric vein thrombosis"],
    "脾静脉血栓": ["splenic vein thrombosis"],
    "肝静脉血栓": ["hepatic vein thrombosis"],
    "免疫相关性心肌炎": ["immune checkpoint inhibitor myocarditis", "ICI myocarditis", "immune-related myocarditis"],
    "阿片类药物减量": ["opioid dose reduction", "opioid tapering", "opioid de-escalation"],
}

# 中文→英文 术语映射
EXACT_ZH_EN = {
    "局限期": "limited-stage", "广泛期": "extensive-stage",
    "一线": "first-line", "二线": "second-line", "三线": "third-line",
    "维持治疗": "maintenance therapy", "辅助治疗": "adjuvant", "新辅助": "neoadjuvant",
    "耐药": "resistance", "脑转移": "brain metastasis", "无脑转移": "without brain metastasis",
    "非小细胞肺癌": "NSCLC", "非鳞状": "non-squamous", "非鳞": "non-squamous",
    "肺腺癌": "lung adenocarcinoma", "小细胞肺癌": "SCLC",
    "分子检测": "molecular testing", "基因检测": "biomarker testing",
    "心肌炎": "myocarditis", "肌钙蛋白": "troponin", "心电图": "ECG",
    "心脏超声": "echocardiography", "心脏磁共振": "cardiac MRI",
    "癌痛": "cancer pain", "阿片": "opioid", "减量": "tapering",
    "血栓": "thrombosis", "静脉血栓": "venous thromboembolism",
    "腹腔静脉": "splanchnic vein", "内脏静脉": "visceral vein",
    "影像学": "imaging", "超声": "ultrasound", "CT": "CT", "MRI": "MRI",
    "阿替利珠单抗": "atezolizumab", "度伐利尤单抗": "durvalumab",
    "帕博利珠单抗": "pembrolizumab", "纳武利尤单抗": "nivolumab",
    "卡铂": "carboplatin", "顺铂": "cisplatin", "依托泊苷": "etoposide",
    "奥希替尼": "osimertinib", "阿美替尼": "almonertinib", "伏美替尼": "furmonertinib",
}

SOFT_QUERY_TERMS = {
    "ps": ["performance status", "ECOG"],
    "PS": ["performance status", "ECOG"],
    "0-2": ["ECOG 0-2"],
    "0–1": ["ECOG 0-1"],
    "稳定": ["stable disease"],
    "确诊": ["diagnosis", "diagnostic evaluation"],
    "初步诊断": ["initial diagnostic evaluation"],
    "必须": ["required", "recommended"],
    "首选": ["preferred"],
}


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        key = value.upper()
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def parse_query_intent(question: str) -> dict:
    """从用户查询中提取检索意图：高置信字段用于硬过滤，其余进入软扩展。"""
    text = question.lower()
    intent = {}
    soft_terms = []

    # 分期
    if re.search(r"IV期|stage\s*iv|晚期|转移性|metastatic", text):
        intent["stage"] = "IV"
    elif re.search(r"III期|stage\s*iii|局部晚期", text):
        intent["stage"] = "III"
    elif re.search(r"limited.stage|局限期", text):
        intent["stage"] = "limited"
    elif re.search(r"extensive.stage|广泛期", text):
        intent["stage"] = "extensive"

    # 治疗线
    if re.search(r"一线|first.line", text):
        soft_terms.append("first-line")
    elif re.search(r"二线|second.line|耐药", text):
        soft_terms.append("second-line")
    elif re.search(r"辅助|adjuvant", text):
        soft_terms.append("adjuvant")
    if re.search(r"维持|maintenance", text):
        soft_terms.append("maintenance therapy")

    # 靶点
    biomarkers = []
    for bm in ["EGFR", "ALK", "ROS1", "KRAS", "BRAF", "MET", "RET", "NTRK", "HER2", "PD-L1", "PD_L1"]:
        if bm.upper() in question.upper():
            biomarkers.append("PD-L1" if bm == "PD_L1" else bm)
    if biomarkers:
        intent["biomarkers"] = _dedupe_preserve_order(biomarkers)

    # 来源机构
    orgs = []
    for org_keyword, org_code in [
        ("NCCN", "NCCN"), ("ASCO", "ASCO"), ("ESMO", "ESMO"),
        ("CSCO", "CSCO"), ("SITC", "SITC"),
        ("中华医学会", "ChineseGuideline"), ("卫健委", "ChineseGuideline"),
        ("中国临床指南", "ChineseGuideline"), ("专家共识", "ExpertConsensus"),
    ]:
        if org_keyword.upper() in question.upper():
            orgs.append(org_code)
    if orgs:
        intent["source_orgs"] = _dedupe_preserve_order(orgs)

    for keyword, terms in SOFT_QUERY_TERMS.items():
        if keyword in question:
            soft_terms.extend(terms)
    if "心肌炎" in question:
        soft_terms.extend(["immune checkpoint inhibitor myocarditis", "troponin", "ECG"])
    if "分子" in question or "基因" in question:
        soft_terms.extend(["molecular testing", "biomarker testing", "actionable driver alterations"])
    if "血栓" in question:
        soft_terms.extend(["venous thromboembolism", "splanchnic vein thrombosis", "diagnostic imaging"])
    if "癌痛" in question or "阿片" in question:
        soft_terms.extend(["adult cancer pain", "opioid dose reduction", "survivorship"])
    if soft_terms:
        intent["soft_terms"] = _dedupe_preserve_order(soft_terms)

    if intent:
        logger.info(f"  [查询意图] {intent}")
    return intent


def bilingual_expand(question: str, intent: dict | None = None) -> str:
    """中文查询 → 附加英文术语扩展"""
    terms = []
    q_lower = question.lower()

    for zh, en in EXACT_ZH_EN.items():
        if zh in q_lower:
            terms.append(en)

    en_terms = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", question)
    terms.extend(en_terms)
    if intent:
        terms.extend(intent.get("soft_terms", []))

    seen = set()
    unique = []
    for t in terms:
        t_upper = t.upper()
        if t_upper not in seen:
            seen.add(t_upper)
            unique.append(t)

    # ── 低频实体同义词扩展 ──
    for zh_term, en_synonyms in CLINICAL_SYNONYMS.items():
        if zh_term in question:
            for syn in en_synonyms:
                if syn.lower() not in seen:
                    seen.add(syn.lower())
                    unique.append(syn)

    expanded = " ".join(unique)
    if expanded:
        logger.info(f"  [双语扩展] '{question[:60]}' → '+{expanded[:60]}'")
    return question + " " + expanded


# ══════════════════════════════════════════════════════
#  去重 / 过滤 / 均衡
# ══════════════════════════════════════════════════════

def deduplicate_series(results: list[dict]) -> list[dict]:
    """同系列文献只保留最新年份版本"""
    import re
    series = {}
    for r in results:
        sf = r.get("source_file", "")
        base = re.sub(r"[（(]?20\d{2}[版年）)]?", "", sf)
        key = f"{r['source']}|{base}"
        if key not in series or r["year"] > series[key]["year"]:
            series[key] = r
    kept = set(id(v) for v in series.values())
    filtered = [r for r in results if id(r) in kept]
    if len(filtered) < len(results):
        logger.info(f"  [同系列去重] {len(results)} → {len(filtered)} 条")
    return filtered


def rank_results(results: list[dict]) -> list[dict]:
    """按融合分优先，其次 rerank/vector 排序。"""
    return sorted(
        results,
        key=lambda r: (
            r.get("search_score", r.get("rerank_score", 0)),
            r.get("rerank_score", 0),
            r.get("vector_score", 0),
        ),
        reverse=True,
    )


def deduplicate_and_fill(results: list[dict], top_k: int) -> list[dict]:
    """同系列去重后用后备结果补位，避免 Top-K 被压缩得过少。"""
    ranked = rank_results(results)
    deduped = deduplicate_series(ranked)
    if len(deduped) >= top_k:
        return rank_results(deduped)[:top_k]

    used = {r.get("chunk_id") for r in deduped}
    for r in ranked:
        if r.get("chunk_id") not in used:
            deduped.append(r)
            used.add(r.get("chunk_id"))
        if len(deduped) >= top_k:
            break
    return rank_results(deduped)[:top_k]


def ensure_org_diversity(results: list[dict], source_orgs: list,
                         all_candidates: list[dict], top_k: int) -> list[dict]:
    """多机构查询时，确保每个机构至少1条结果"""
    if len(source_orgs) < 2:
        return rank_results(results)[:top_k]

    result_orgs = set(r["source"] for r in results)
    missing = [o for o in source_orgs if o not in result_orgs]
    if not missing:
        return rank_results(results)[:top_k]

    for org in missing:
        org_chunks = [c for c in all_candidates if c.get("metadata", {}).get("source_org") == org]
        org_chunks.sort(key=lambda x: x.get("vector_score", 0), reverse=True)
        if org_chunks:
            c = org_chunks[0]
            results.append({
                "content": c["content"],
                "chunk_id": c.get("chunk_id", ""),
                "source": c["metadata"].get("source_org", org),
                "source_org_cn": c["metadata"].get("source_org_cn", ""),
                "source_file": c["metadata"].get("source_file", ""),
                "year": c["metadata"].get("year", 0),
                "evidence_rank": c["metadata"].get("evidence_rank", 0),
                "evidence_rank_label": c["metadata"].get("evidence_rank_label", ""),
                "evidence_label": c["metadata"].get("evidence_label", ""),
                "section_title": c["metadata"].get("section_title", ""),
                "chunk_index": c["metadata"].get("chunk_index", 0),
                "total_chunks": c["metadata"].get("total_chunks", 0),
            "recommendation_grade": c["metadata"].get("recommendation_grade", ""),
            "recommendation_grades": c["metadata"].get("recommendation_grades", []),
            "language": c["metadata"].get("language", ""),
            "extraction_mode": c["metadata"].get("extraction_mode", ""),
                "source_page": get_chunk_page(c.get("chunk_id", "")),
                "rerank_score": 0,
                "vector_score": c["vector_score"],
                "search_score": c.get("vector_score", 0),
                "retrieval_paths": c.get("retrieval_paths", ["org-fill"]),
            })
            logger.info(f"    [机构补充] {org} 强制保留1条")
    return rank_results(results)[:top_k]


# ══════════════════════════════════════════════════════
#  格式化
# ══════════════════════════════════════════════════════

def _clean_ocr(text: str) -> str:
    """清洗 MinerU OCR 痕迹"""
    return (text or "").replace("NCCN指南?", "NCCN Guidelines").replace("NCCN指南@", "NCCN Guidelines")


def format_for_llm(results: list[dict]) -> str:
    """将检索结果格式化为 LLM 可读的上下文文本"""
    if not results:
        return "（无检索结果）"

    parts = []
    for i, r in enumerate(results):
        page = r.get("source_page", "")
        page_info = f"PDF{page}页" if page else ""
        pos = ""
        if r.get("total_chunks", 0) > 0:
            pos = f"第{r['chunk_index']+1}/{r['total_chunks']}段"

        header = (
            f"【文献{i+1}】{r.get('evidence_rank_label', '')} | "
            f"{r.get('source_org_cn', r['source'])} ({r['year']}) | "
            f"{pos} | {page_info}"
        ).replace("  ", " ")
        if r.get("recommendation_grade"):
            header += f" | 推荐等级: {r.get('recommendation_grade')}"

        if r.get("section_title"):
            header += f"\n章节: {_clean_ocr(r['section_title'])}"
        if r.get("source_file"):
            header += f"\n文件: {_clean_ocr(r['source_file'])}"

        parts.append(f"{header}\n{r['content']}")

    return "\n\n---\n\n".join(parts)


def format_for_agent(results: list[dict]) -> str:
    """结构化证据卡（给 Agent 用，兼顾证据完整性和 token 预算）"""
    if not results:
        return "（无检索结果）"

    parts = []
    for i, r in enumerate(results):
        page = r.get("source_page", "")
        page_info = f"PDF{page}页" if page else ""
        content_snippet = r["content"][:420].replace("\n", " ").strip()
        score = r.get("search_score", r.get("rerank_score", 0))
        line = (
            f"【证据{i+1}】{r.get('evidence_rank_label', '')} | "
            f"{r.get('source_org_cn', r['source'])} {r['year']} | {page_info} | score={score:.3f}\n"
            f"章节: {_clean_ocr(r.get('section_title', ''))}\n"
            f"推荐等级: {r.get('recommendation_grade', '') or '未标注'}\n"
            f"来源文件: {r.get('source_file', '')}\n"
            f"推荐/证据片段: {content_snippet}..."
        )
        parts.append(line)
    return "\n\n".join(parts)


def format_for_human(results: list[dict]) -> list[dict]:
    """返回结构化的检索结果（供程序使用）"""
    output = []
    for r in results:
        page = r.get("source_page", "")
        pos = ""
        if r.get("total_chunks", 0) > 0:
            pos = f"第{r['chunk_index']+1}/{r['total_chunks']}段"
        output.append({
            "source": r["source"],
            "year": r["year"],
            "evidence_rank": r.get("evidence_rank", 0),
            "evidence_label": r.get("evidence_rank_label", ""),
            "section": r.get("section_title", ""),
            "file": r.get("source_file", ""),
            "position": pos,
            "page": page,
            "score": r.get("search_score", r.get("rerank_score", 0)),
            "rerank_score": r.get("rerank_score", 0),
            "vector_score": r.get("vector_score", 0),
            "recommendation_grade": r.get("recommendation_grade", ""),
            "language": r.get("language", ""),
            "extraction_mode": r.get("extraction_mode", ""),
            "retrieval_paths": r.get("retrieval_paths", []),
            "content": r["content"],
        })
    return output


# ══════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════

def search_guidelines(
    question: str,
    top_k: int = 10,
    source_orgs: Optional[list] = None,
    year_from: Optional[int] = None,
    evidence_min: Optional[int] = None,
    mode: str = "llm",
    raw: bool = False,
) -> list[dict] | str:
    """
    搜索 279 篇肿瘤临床指南（NCCN/CSCO/ASCO/ESMO 等）

    Args:
        question: 临床问题（中文 / 英文）
        top_k: 返回结果数
        source_orgs: 限制来源机构，如 ['NCCN', 'CSCO']
        year_from: 最低年份
        evidence_min: 最低证据等级 (1-8)
        mode: "llm"=全文上下文(给evaluate), "agent"=精简摘要(给Agent)
        raw: True=返回结构化数据

    Returns:
        list[dict] 或 str
    """
    # ① 解析查询意图
    global LAST_SEARCH_TRACE
    intent = parse_query_intent(question)
    if source_orgs:
        intent["source_orgs"] = source_orgs

    # ② 双语扩展
    expanded_query = bilingual_expand(question, intent)

    # ③ 构建 where 过滤条件
    where = _build_where(intent)
    trace = {
        "question": question,
        "expanded_query": expanded_query,
        "intent": intent,
        "where": where,
        "top_k": top_k,
        "mode": mode,
    }

    # ④ 向量检索（多机构时走分机构查询）
    multi_org = intent.get("source_orgs", [])
    search_top_k = max(top_k * 2, top_k)
    if len(multi_org) >= 2:
        results, all_candidates = _multi_org_query(expanded_query, search_top_k, multi_org, intent, trace)
    else:
        results = _rag_query(expanded_query, top_k=search_top_k, where_filter=where, trace=trace)
        all_candidates = None
    trace["pre_filter_results"] = len(results)

    # ⑤ 后过滤
    if year_from:
        results = [r for r in results if r["year"] >= year_from]
    if evidence_min:
        results = [r for r in results if r.get("evidence_rank", 0) <= evidence_min]
    trace["post_filter_results"] = len(results)

    # ⑥ 多机构均衡（单机构跳过）
    if len(multi_org) < 2:
        results = deduplicate_and_fill(results, top_k)
    elif all_candidates:
        results = ensure_org_diversity(results, multi_org, all_candidates, top_k)
    else:
        results = rank_results(results)[:top_k]

    # ⑦ 去重
    # （已在步骤⑥处理）
    trace["final_results"] = len(results)
    trace["sources"] = [r.get("source") for r in results]
    LAST_SEARCH_TRACE = trace

    if raw:
        return format_for_human(results)
    elif mode == "agent":
        return format_for_agent(results)
    else:
        return format_for_llm(results)


def get_source_context(source_file: str, chunk_index: int = None) -> dict:
    """获取 chunk 的源文档上下文"""
    return find_chunk_in_document(source_file, chunk_index)


def get_status() -> dict:
    """查看知识库状态"""
    return show_status()


def get_last_search_trace() -> dict[str, Any]:
    """返回最近一次 search_guidelines 的检索 trace，供测试报告使用。"""
    return dict(LAST_SEARCH_TRACE)


# ══════════════════════════════════════════════════════
#  Agent Tool 封装
# ══════════════════════════════════════════════════════

SEARCH_TOOL_NAME = "search_medical_guidelines"
SOURCE_DETAIL_TOOL_NAME = "get_source_detail"

SEARCH_TOOL_DESCRIPTION = (
    "搜索 279 篇肿瘤临床指南知识库（NCCN/CSCO/ASCO/ESMO/中国指南/专家共识），"
    "返回指南摘要、来源机构、年份、证据等级和 PDF 页码。"
    "涵盖 NSCLC、SCLC、irAE、癌痛、血栓等领域。"
    "当你需要循证医学证据来回答临床问题时，务必调用此工具。"
)

SOURCE_DETAIL_TOOL_DESCRIPTION = "获取某个检索结果的全文上下文，查看前后段落。"


class SearchGuidelinesInput(BaseModel):
    """医学指南检索工具参数。"""

    query: str = Field(
        ...,
        description="临床问题，用中文或英文关键词，如 'EGFR 19del 一线治疗'",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=20,
        description="返回结果数，默认 10。Agent 场景建议 5-10，避免上下文过长。",
    )
    source_orgs: Optional[list[str]] = Field(
        default=None,
        description="限制来源机构，如 ['NCCN', 'CSCO', 'ASCO', 'ESMO']。",
    )
    year_from: Optional[int] = Field(
        default=None,
        ge=1900,
        description="最低指南年份，例如 2020。",
    )
    evidence_min: Optional[int] = Field(
        default=None,
        ge=1,
        le=8,
        description="最低证据等级阈值，数值越小证据级别越高。",
    )


class GetSourceDetailInput(BaseModel):
    """源文档上下文工具参数。"""

    source_file: str = Field(..., description="检索结果中的文件路径或文件名。")
    chunk_index: int = Field(..., ge=0, description="检索结果中的 chunk 序号。")


def search_medical_guidelines(
    query: str,
    top_k: int = 10,
    source_orgs: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    evidence_min: Optional[int] = None,
) -> str:
    """Agent 标准工具：检索医学指南并返回精简摘要。"""
    query = (query or "").strip()
    if not query:
        return "工具参数错误: query 不能为空"

    logger.info(f"  [Tool] 检索: '{query[:60]}' (top_k={top_k}, source_orgs={source_orgs})")
    result = search_guidelines(
        query,
        top_k=top_k,
        source_orgs=source_orgs,
        year_from=year_from,
        evidence_min=evidence_min,
        mode="agent",
    )
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def get_source_detail(source_file: str, chunk_index: int) -> str:
    """Agent 标准工具：获取检索结果所在源文档的上下文。"""
    result = get_source_context(source_file, chunk_index)
    return json.dumps(result, ensure_ascii=False) if result else "未找到"


TOOL_INPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    SEARCH_TOOL_NAME: SearchGuidelinesInput,
    SOURCE_DETAIL_TOOL_NAME: GetSourceDetailInput,
}

TOOL_HANDLERS: dict[str, Callable[..., str]] = {
    SEARCH_TOOL_NAME: search_medical_guidelines,
    SOURCE_DETAIL_TOOL_NAME: get_source_detail,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    SEARCH_TOOL_NAME: SEARCH_TOOL_DESCRIPTION,
    SOURCE_DETAIL_TOOL_NAME: SOURCE_DETAIL_TOOL_DESCRIPTION,
}


def _model_schema(model: type[BaseModel]) -> dict[str, Any]:
    """兼容 Pydantic v1/v2 的 JSON schema 导出。"""
    if hasattr(model, "model_json_schema"):
        schema = model.model_json_schema()
    else:
        schema = model.schema()

    schema.pop("title", None)
    return schema


def get_openai_tools() -> list[dict[str, Any]]:
    """返回 DeepSeek/OpenAI function calling 兼容的 tools 定义。"""
    return [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": TOOL_DESCRIPTIONS[tool_name],
                "parameters": _model_schema(schema),
            },
        }
        for tool_name, schema in TOOL_INPUT_SCHEMAS.items()
    ]


OPENAI_TOOLS = get_openai_tools()
TOOLS = OPENAI_TOOLS


def _model_dump(instance: BaseModel) -> dict[str, Any]:
    """兼容 Pydantic v1/v2 的模型转 dict。"""
    if hasattr(instance, "model_dump"):
        return instance.model_dump(exclude_none=True)
    return instance.dict(exclude_none=True)


def run_agent_tool(tool_name: str, args: dict | None) -> str:
    """按工具名统一校验参数并执行工具。"""
    if tool_name not in TOOL_HANDLERS:
        return f"未知工具: {tool_name}"

    try:
        validated = TOOL_INPUT_SCHEMAS[tool_name](**(args or {}))
        payload = _model_dump(validated)
    except Exception as exc:
        logger.warning(f"  [Tool参数错误] {tool_name}: {exc}")
        return f"工具参数错误: {exc}"

    cache_key = json.dumps([tool_name, payload], ensure_ascii=False, sort_keys=True)
    if cache_key in _TOOL_CACHE:
        logger.info(f"  [Tool缓存命中] {tool_name}")
        return _TOOL_CACHE[cache_key]

    try:
        result = TOOL_HANDLERS[tool_name](**payload)
    except Exception as exc:
        logger.exception(f"  [Tool执行失败] {tool_name}")
        return f"工具执行失败: {exc}"

    output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    _TOOL_CACHE[cache_key] = output
    return output


def get_langchain_tools() -> list[Any]:
    """返回 LangChain StructuredTool 列表；未安装 langchain-core 时给出明确错误。"""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise ImportError(
            "未安装 langchain-core，无法创建 LangChain Tool。"
            "如需使用 LangChain Agent，请先安装 langchain-core 或 langchain。"
        ) from exc

    return [
        StructuredTool.from_function(
            func=search_medical_guidelines,
            name=SEARCH_TOOL_NAME,
            description=SEARCH_TOOL_DESCRIPTION,
            args_schema=SearchGuidelinesInput,
        ),
        StructuredTool.from_function(
            func=get_source_detail,
            name=SOURCE_DETAIL_TOOL_NAME,
            description=SOURCE_DETAIL_TOOL_DESCRIPTION,
            args_schema=GetSourceDetailInput,
        ),
    ]


try:
    LANGCHAIN_TOOLS = get_langchain_tools()
except ImportError:
    LANGCHAIN_TOOLS = []


# ══════════════════════════════════════════════════════
#  内部辅助
# ══════════════════════════════════════════════════════

def _build_where(intent: dict) -> dict | None:
    """将意图转为 ChromaDB where 条件——当前版本 ChromaDB 1.5.x where 过滤不稳定，返回 None 走全量检索+Python后过滤。"""
    return None


def _multi_org_query(question: str, top_k: int, orgs: list,
                     intent: dict, trace: dict | None = None) -> tuple:
    """多机构分机构独立检索，合并结果"""
    from kb_manager import (
        get_chroma_collection, ollama_embed, cross_encoder_rerank,
        get_chunk_page, _resolve_evidence_rank, year_weight, evidence_weight,
    )

    collection, _ = get_chroma_collection()
    embedding = ollama_embed(question)
    if embedding is None:
        logger.error("  [多机构检索] query embedding 生成失败")
        return ([], [])
    per_org_k = min(max(top_k * 5, 30), 75)

    other_intent = {k: v for k, v in intent.items() if k != "source_orgs"}
    other_where = _build_where(other_intent)

    all_candidates = []
    per_org_counts = {}
    for org in orgs:
        org_where = {"source_org": org}
        if other_where:
            org_where = {"$and": [org_where, other_where]}
        try:
            vec = collection.query(
                query_embeddings=[embedding],
                n_results=per_org_k,
                where=org_where,
                include=["documents", "metadatas", "distances"],
            )
            if vec["documents"][0]:
                for doc, meta, dist in zip(vec["documents"][0], vec["metadatas"][0], vec["distances"][0]):
                    all_candidates.append({
                        "content": doc,
                        "metadata": meta,
                        "vector_score": 1 - dist,
                        "chunk_id": f"{meta.get('source_file','')}::{meta.get('chunk_index',0)}",
                        "retrieval_paths": [f"org:{org}"],
                    })
            per_org_counts[org] = len(vec["documents"][0]) if vec["documents"][0] else 0
            logger.info(f"    [{org}] {per_org_counts[org]} 条")
        except Exception as e:
            logger.warning(f"    [{org}] 检索失败: {e}")
            per_org_counts[org] = 0

    if not all_candidates:
        return ([], [])

    # 按 vector_score 预筛，再用 CrossEncoder 精排
    all_candidates.sort(key=lambda x: x["vector_score"], reverse=True)
    rerank_pool = all_candidates[:min(len(all_candidates), max(top_k * 5, 20), 50)]

    docs = [c["content"] for c in rerank_pool]
    reranked = cross_encoder_rerank(question, docs, top_k=len(docs))

    results = []
    for r in reranked:
        c = rerank_pool[r["index"]]
        meta = c["metadata"]
        year = meta.get("year", 0)
        evidence_rank = _resolve_evidence_rank(meta)
        rerank_score = r["score"]
        vector_score = c["vector_score"]
        search_score = (rerank_score * 0.78 + vector_score * 0.22) * year_weight(year) * evidence_weight(evidence_rank)
        results.append({
            "content": c["content"],
            "chunk_id": c.get("chunk_id", ""),
            "source": meta.get("source_org", ""),
            "source_org_cn": meta.get("source_org_cn", ""),
            "source_file": meta.get("source_file", ""),
            "year": year,
            "evidence_rank": evidence_rank,
            "evidence_rank_label": meta.get("evidence_rank_label", ""),
            "evidence_label": meta.get("evidence_label", ""),
            "section_title": meta.get("section_title", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "total_chunks": meta.get("total_chunks", 0),
            "recommendation_grade": meta.get("recommendation_grade", ""),
            "recommendation_grades": meta.get("recommendation_grades", []),
            "language": meta.get("language", ""),
            "extraction_mode": meta.get("extraction_mode", ""),
            "source_page": get_chunk_page(c.get("chunk_id", "")),
            "rerank_score": rerank_score,
            "vector_score": vector_score,
            "search_score": search_score,
            "retrieval_paths": c.get("retrieval_paths", []),
        })

    results = rank_results(results)
    if trace is not None:
        trace.update({
            "multi_org_counts": per_org_counts,
            "multi_org_candidates": len(all_candidates),
            "multi_org_rerank_pool": len(rerank_pool),
        })
    logger.info(f"  [多机构检索] {orgs} → {len(results)}/{top_k} 条")
    return (results[:top_k], all_candidates)
