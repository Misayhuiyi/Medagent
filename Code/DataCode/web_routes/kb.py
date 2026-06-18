"""知识库追溯路由。"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kb", tags=["kb"])

_OCR_FIX: list[tuple[str, str]] = [
    ("川级推荐", "Ⅱ级推荐"),
    ("川A期", "ⅢA期"),
    ("川B期", "ⅢB期"),
    ("）期", "期"),
]
_RE_CHUAN = re.compile(r'川\s*(?=[A-C级])')


def _normalize_trace_text(text: str) -> str:
    """去 surrogate + 高频 OCR 修正。"""
    text = text.encode('utf-8', 'surrogatepass').decode('utf-8', 'ignore')
    for old, new in _OCR_FIX:
        text = text.replace(old, new)
    text = _RE_CHUAN.sub('Ⅲ', text)
    return text


def _format_trace_results(raw: list) -> list[dict]:
    """格式化追溯结果，截断到 500 字符。"""
    results = []
    for r in raw:
        content = _normalize_trace_text(r.get("content", ""))
        results.append({
            "source": r.get("source", ""),
            "content": content[:500],
            "page": r.get("page", ""),
            "evidence_level": r.get("evidence_level", 0),
            "year": r.get("publish_date", ""),
        })
    return results


@router.post("/trace")
async def trace_knowledge(body: dict):
    """根据问题检索知识库, 优先使用报告生成时缓存在 app_state 的结果。

    缓存层级：
    1. {patient_id}:{tab}  — 页签专属结果（最精准）
    2. {patient_id}        — 整份报告的通用结果（兜底）
    3. 实时查询             — 缓存未命中
    """
    from DataCode.web_server import _app_state

    patient_id = str(body.get("patient_id", "")).strip()
    question = str(body.get("question", "")).strip()
    top_k = int(body.get("top_k", 5))
    tab = str(body.get("tab", "")).strip()

    cache = _app_state.get("trace_cache", {})

    # 优先查页签专属缓存
    if patient_id and tab:
        tab_key = f"{patient_id}:{tab}"
        if tab_key in cache:
            cached = cache[tab_key]
            logger.info("TRACE CACHE HIT (tab): key=%s results=%d", tab_key, len(cached))
            return {"results": _format_trace_results(cached[:top_k]), "cached": True}

    # 兜底：查患者级缓存
    if patient_id and patient_id in cache:
        cached = cache[patient_id]
        logger.info("TRACE CACHE HIT (patient): patient=%s results=%d", patient_id, len(cached))
        return {"results": _format_trace_results(cached[:top_k]), "cached": True}

    # 缓存未命中, 实时查询
    kb = _app_state.get("knowledge_base")
    if kb is None:
        return {"results": []}
    if not question:
        return {"results": []}

    try:
        raw = await kb.query(question, top_k=top_k)
        if patient_id and tab:
            cache[f"{patient_id}:{tab}"] = raw
        elif patient_id:
            cache[patient_id] = raw
    except Exception as e:
        logger.exception("Trace query failed")
        return {"results": [], "error": str(e)}

    logger.info("TRACE LIVE: patient=%s tab=%s question=%s results=%d", patient_id, tab, question[:50], len(raw))
    return {"results": _format_trace_results(raw[:top_k]), "cached": False}