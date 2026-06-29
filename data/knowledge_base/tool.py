"""RAG 知识库查询工具 — ChromaDB + SentenceTransformer 语义检索。

供 RagKnowledgeBase 内部调用，对齐接口：search_guidelines(query, top_k, raw) -> list[dict]
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent / "chroma_db"
_SUMMARY_PATH = _DB_PATH / "index_summary.json"

_collection = None
_embed_fn = None
_summary: dict = {}


def _load():
    """延迟加载 ChromaDB collection 和 embedding 模型。"""
    global _collection, _embed_fn, _summary

    if _collection is not None:
        return

    # 加载索引摘要
    if _SUMMARY_PATH.exists():
        with open(_SUMMARY_PATH, "r", encoding="utf-8") as f:
            _summary.update(json.load(f))

    model_name = _summary.get("embedding_model", "BAAI/bge-small-zh-v1.5")
    logger.info("Loading embedding model: %s", model_name)

    from sentence_transformers import SentenceTransformer
    _embed_fn = SentenceTransformer(model_name, device="cpu")

    import chromadb
    client = chromadb.PersistentClient(path=str(_DB_PATH))
    collections = client.list_collections()
    if not collections:
        raise RuntimeError(f"No collections found in {_DB_PATH}")
    # 优先选择 lung_cancer_guidelines 集合，否则选第一个
    target_name = "lung_cancer_guidelines"
    _collection = next((c for c in collections if c.name == target_name), collections[0])
    if _collection.name != target_name and len(collections) > 1:
        logger.warning("Multiple collections found, using '%s' (available: %s)",
                       _collection.name, [c.name for c in collections])
    logger.info("ChromaDB loaded: %s (%s docs)", _collection.name, _collection.count())


def _extract_year(source_file: str) -> str:
    """从文件名提取年份。"""
    m = re.match(r"(\d{4})", source_file)
    return m.group(1) if m else ""


def _extract_source_label(source_path: str) -> str:
    """从路径提取来源标签。"""
    parts = source_path.replace("\\", "/").split("/")
    org = ""
    cat = ""
    for part in parts:
        upper = part.upper()
        if upper in ("NCCN", "CSCO", "ESMO", "ASCO", "SITC", "CTCAE",
                      "IASLC", "ESTS", "ESTRO", "ASTRO", "ERS", "ACCP"):
            org = part
        if part in ("指南", "专家共识", "文献", "病例", "法规"):
            cat = part
    if org and cat:
        return f"{org} {cat}"
    if org:
        return org
    if cat:
        return cat
    return "未知来源"


def _extract_guideline_edition(source_file: str) -> str:
    """从文件名提取指南版本。"""
    m = re.match(r"(\d{4})", source_file)
    year = m.group(1) if m else ""
    name = os.path.splitext(source_file)[0]
    # 截取合理长度作为版本标识
    if len(name) > 60:
        name = name[:57] + "..."
    # 修复：有年份时拼接年份，无年份时返回文件名本身
    return f"{name} ({year})" if year else name


def search_guidelines(
    query: str,
    top_k: int = 5,
    raw: bool = False,
) -> list[dict]:
    """语义检索指南/文献。

    Args:
        query: 查询文本
        top_k: 返回结果数
        raw: True 返回原始 dict，False 返回格式化文本

    Returns:
        list[dict] with keys: content, source, evidence_level, publish_date, guideline_edition, page
    """
    _load()

    if _embed_fn is None or _collection is None:
        logger.error("RAG not initialized")
        return []

    try:
        query_vec = _embed_fn.encode(query, normalize_embeddings=True).tolist()
        results = _collection.query(query_embeddings=[query_vec], n_results=top_k)
    except Exception as e:
        logger.exception("ChromaDB query failed: %s", e)
        return []

    output = []
    if results.get("ids") and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            meta = (results.get("metadatas", [{}]) or [{}])[0]
            if isinstance(meta, list):
                meta = meta[i] if i < len(meta) else {}
            content = (results.get("documents", [[""]])[0] or [""])
            if isinstance(content, list):
                content = content[i] if i < len(content) else ""
            distance = 0
            if results.get("distances") and results["distances"][0]:
                d = results["distances"][0]
                if isinstance(d, list):
                    distance = d[i] if i < len(d) else 0

            source_file = meta.get("source_file", "")
            source_path = meta.get("source_path", "")
            source_label = _extract_source_label(source_path)
            year = _extract_year(source_file)

            relevance = round(1.0 / (1.0 + distance), 4)

            output.append({
                "content": str(content)[:2000],
                "source": source_label,
                "source_file": source_file,
                "source_path": source_path,
                "evidence_level": source_label,
                "publish_date": year,
                "guideline_edition": _extract_guideline_edition(source_file),
                "page": f"{meta.get('start_page', '')}-{meta.get('end_page', '')}",
                "relevance_score": relevance,
            })

    if not raw:
        # 格式化输出
        lines = []
        for i, r in enumerate(output, 1):
            lines.append(
                f"[{i}] {r['source']} | {r['guideline_edition']} "
                f"| 年份: {r['publish_date']} | 相关度: {r['relevance_score']}\n"
                f"{r['content'][:500]}"
            )
        return [{"content": "\n\n".join(lines), "raw_results": output}]

    return output


if __name__ == "__main__":
    # 快速测试
    results = search_guidelines("非小细胞肺癌 NCCN 免疫治疗", top_k=3, raw=True)
    print(f"\n返回 {len(results)} 条结果:")
    for r in results:
        print(f"  - {r['source']} | {r['publish_date']} | score={r['relevance_score']}")
        print(f"    文件: {r['source_file']}")
