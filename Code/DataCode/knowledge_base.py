"""知识库抽象接口 + Mock 实现 + RAG 实现 + 证据等级定义。"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

logger = logging.getLogger(__name__)


class EvidenceLevel:
    """证据等级定义，数值越高越权威。"""
    INTERNATIONAL_GUIDELINE = (7, "国际权威指南")
    NATIONAL_GUIDELINE = (6, "国内权威指南")
    INTERNATIONAL_CONSENSUS = (5, "国际专家共识")
    NATIONAL_CONSENSUS = (4, "国内专家共识")
    HIGH_QUALITY_RCT = (3, "临床试验（高质量Meta分析/RCT）")
    REAL_WORLD_STUDY = (2, "真实世界研究/观察性研究")
    CASE_REPORT = (1, "病例系列/个案报告")
    EXPERT_OPINION = (0, "个人专家意见")


class KnowledgeResult(TypedDict):
    content: str
    source: str
    evidence_level: int
    evidence_label: str
    publish_date: str
    effective_date: str
    guideline_edition: str


@runtime_checkable
class KnowledgeBase(Protocol):
    async def query(
        self,
        question: str,
        top_k: int = 3,
        min_evidence: int = 0,
        before_date: str | None = None,
    ) -> list[KnowledgeResult]: ...


class RagKnowledgeBase:
    """基于 ChromaDB + Ollama bge-m3 + CrossEncoder 的 RAG 知识库。

    调用 ai-doctor knowledge-base 的 search_guidelines 进行语义检索，
    返回 KnowledgeResult 格式对齐现有接口。
    """

    def __init__(self, kb_dir: str):
        self._kb_dir = Path(kb_dir)
        if str(self._kb_dir) not in sys.path:
            sys.path.insert(0, str(self._kb_dir))
        self._initialized = False

    def _ensure_init(self):
        if self._initialized:
            return
        # 延迟导入，避免启动时加载重型依赖
        try:
            from tool import search_guidelines
            self._search_fn = search_guidelines
            self._initialized = True
        except Exception as e:
            logger.error("RAG knowledge base init failed: %s", e)
            raise

    async def query(
        self,
        question: str,
        top_k: int = 3,
        min_evidence: int = 0,
        before_date: str | None = None,
    ) -> list[KnowledgeResult]:
        self._ensure_init()
        try:
            raw_results = await asyncio.to_thread(
                self._search_fn, question, top_k, raw=True
            )
        except Exception as e:
            logger.exception("RAG search failed for: %s", question[:100])
            return []

        results: list[KnowledgeResult] = []
        for item in raw_results:
            content = item.get("content", "")
            source = item.get("source", "")
            year = str(item.get("publish_date", ""))
            evidence_level = self._map_evidence(source)
            results.append(KnowledgeResult(
                content=content[:2000],
                source=source,
                evidence_level=evidence_level,
                evidence_label=self._evidence_label_for(evidence_level),
                publish_date=year,
                effective_date=year,
                guideline_edition=item.get("guideline_edition", ""),
            ))
        return results[:top_k]

    _evidence_mapping: dict | None = None

    @classmethod
    def _load_evidence_mapping(cls) -> dict:
        """从 platform.yaml 加载证据等级映射（缓存）。"""
        if cls._evidence_mapping is not None:
            return cls._evidence_mapping
        import yaml
        from pathlib import Path
        platform_path = Path(__file__).resolve().parent.parent.parent / "data" / "platform.yaml"
        try:
            with open(platform_path, encoding="utf-8") as f:
                platform = yaml.safe_load(f) or {}
            cls._evidence_mapping = platform.get("evidence_mapping", {})
        except Exception:
            cls._evidence_mapping = {}
        return cls._evidence_mapping

    @classmethod
    def _map_evidence(cls, source: str) -> int:
        """根据来源名称映射证据等级（通过 platform.yaml 中 evidence_mapping 配置驱动）。
        若未配置，默认返回 EXPERT_OPINION。
        """
        mapping = cls._load_evidence_mapping()
        if mapping:
            s = source.upper()
            label = mapping.get(s) or mapping.get(source)
            if label == "international_guideline":
                return EvidenceLevel.INTERNATIONAL_GUIDELINE[0]
            if label == "national_guideline":
                return EvidenceLevel.NATIONAL_GUIDELINE[0]
            if label == "international_consensus":
                return EvidenceLevel.INTERNATIONAL_CONSENSUS[0]
        return EvidenceLevel.EXPERT_OPINION[0]

    @classmethod
    def _evidence_label_for(cls, level: int) -> str:
        """将证据等级整数映射为人可读标签。"""
        mapping = {
            EvidenceLevel.INTERNATIONAL_GUIDELINE[0]: "国际权威指南",
            EvidenceLevel.NATIONAL_GUIDELINE[0]: "国内权威指南",
            EvidenceLevel.INTERNATIONAL_CONSENSUS[0]: "国际专家共识",
            EvidenceLevel.EXPERT_OPINION[0]: "专家意见",
        }
        return mapping.get(level, "未分类")


