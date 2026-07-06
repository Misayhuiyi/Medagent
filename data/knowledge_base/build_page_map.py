#!/usr/bin/env python3
r"""从 D:\AI医生资料完成\ 的 MinerU JSON 构建 chunk→页码映射（精准）"""
import sys, os, re, json, time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from kb_manager import GUIDELINES_DIR, CHROMA_DIR, COLLECTION_NAME

PDF_ROOT = GUIDELINES_DIR
OUTPUT = Path(os.getenv("KB_PAGE_MAP_PATH", str(Path(__file__).parent / "page_mapping.json")))

def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()

def load_json_page_map(json_path: Path) -> dict:
    """从 MinerU _content_list.json 提取 text→page_idx 映射"""
    if not json_path.exists():
        return {}
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # data 是 list, 每个元素有 text + page_idx
    text_to_page = {}
    for item in data:
        t = normalize(item.get("text", ""))
        if len(t) > 20:  # 跳过太短的
            text_to_page[t] = item.get("page_idx", 0)
    return text_to_page

def count_pdf_pages(pdf_path: Path) -> int:
    """获取 PDF 实际页数"""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        pages = len(doc)
        doc.close()
        return pages
    except Exception:
        return 0


def find_page_from_json(json_path: Path, chunks: list[dict]) -> dict:
    """用 JSON 中的 page_idx 定位每个 chunk 的页码
    返回: {chunk_id: "start_page" 或 "start_page-end_page" 或 ""}
    - 跨页 chunk → "9-19"
    - 单页 chunk → "7"
    - 未匹配 → 按位置估算 → "~15"
    """
    text_to_page = load_json_page_map(json_path)
    if not text_to_page:
        return {}

    # 获取 PDF 实际页数做校验
    pdf_path = Path(str(json_path).replace("_content_list.json", "_origin.pdf"))
    total_pdf_pages = count_pdf_pages(pdf_path)

    results = {}
    for c in chunks:
        content = normalize(c["content"])
        matched_pages = set()

        # 剥离 H1/H2 标题行，取正文
        body_parts = []
        for part in content.split(". "):
            stripped = part.strip()
            if not stripped.startswith("#") and len(stripped) > 15:
                body_parts.append(stripped)
        body_text = ". ".join(body_parts) if body_parts else content

        # 策略1: 正文长句匹配 → 收集所有匹配的页码
        for text, page in text_to_page.items():
            if len(text) > 40 and text[:40] in body_text:
                matched_pages.add(page)

        # 策略2: 正文短句匹配
        if not matched_pages:
            for text, page in text_to_page.items():
                if len(text) > 25 and text[:25] in body_text:
                    matched_pages.add(page)

        # 策略3: 回退到全文匹配
        if not matched_pages:
            for text, page in text_to_page.items():
                if len(text) > 40 and text[:40] in content:
                    matched_pages.add(page)

        # 策略4: section_title 匹配
        if not matched_pages:
            section = normalize(c.get("section_title", ""))
            for text, page in text_to_page.items():
                if section and section[:30] in text[:80]:
                    matched_pages.add(page)

        # ── 构建页码字符串 ──
        if matched_pages:
            pages = sorted(matched_pages)
            # 过滤越界的页码
            valid_pages = [p for p in pages if total_pdf_pages == 0 or p < total_pdf_pages]
            if not valid_pages:
                valid_pages = pages  # 如果全部越界，保留原始值

            if len(valid_pages) == 1:
                page_str = str(valid_pages[0] + 1)
            else:
                page_str = f"{valid_pages[0]+1}-{valid_pages[-1]+1}"
        else:
            # 未匹配：按 chunk 位置估算（标记 ~）
            ci = c.get("chunk_index", 0)
            total = len(chunks)
            if total > 0 and total_pdf_pages > 0:
                est = max(1, int((ci / total) * total_pdf_pages) + 1)
                page_str = f"~{est}"
            else:
                page_str = ""

        results[c["chunk_id"]] = page_str

    return results


def main():
    print("🔨 构建 chunk→页码映射（MinerU JSON, 精准）...")
    start = time.time()
    fresh = "--fresh" in sys.argv

    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    print("  读取 ChromaDB...")
    all_data = collection.get(include=["metadatas", "documents"])
    print(f"  共 {len(all_data['ids'])} 个 chunk")

    # 按 source_file 分组
    groups = defaultdict(list)
    for chunk_id, meta, doc_content in zip(all_data["ids"], all_data["metadatas"], all_data["documents"]):
        sf = meta.get("source_file", "")
        groups[sf].append({
            "chunk_id": chunk_id,
            "chunk_index": meta.get("chunk_index", 0),
            "content": doc_content,
            "section_title": meta.get("section_title", ""),
        })

    unique_files = len(groups)
    print(f"  {unique_files} 个唯一文档")

    # 加载已有映射（断点续跑）；索引重构后应使用 --fresh 强制重建
    page_map = {}
    if OUTPUT.exists() and not fresh:
        with open(OUTPUT, "r", encoding="utf-8") as f:
            page_map = json.load(f)
        print(f"  已有 {len(page_map)} 条映射（断点续跑）")
    elif fresh:
        print("  fresh 模式：忽略已有 page_mapping.json，重新匹配全部 chunk")

    processed = skipped = 0
    for sf, chunks in groups.items():
        pending = [c for c in chunks if c["chunk_id"] not in page_map]
        if not pending:
            skipped += 1
            processed += 1
            continue

        # 构建 JSON 路径
        json_rel = sf.replace(".md", "_content_list.json")
        json_path = PDF_ROOT / json_rel
        if not json_path.exists():
            json_path = PDF_ROOT / sf.replace(".md", "_content_list_v2.json")
        if not json_path.exists():
            skipped += 1
            processed += 1
            continue

        result = find_page_from_json(json_path, pending)
        page_map.update(result)
        processed += 1

        if processed % 20 == 0:
            elapsed = time.time() - start
            matched = sum(1 for cid in result if result[cid] and result[cid] != "~")
            print(f"  [{processed}/{unique_files}] {sf[:60]}... ({len(page_map)} 条, {matched} 匹配, {elapsed:.0f}s)")
            with open(OUTPUT, "w", encoding="utf-8") as f:
                json.dump(page_map, f, ensure_ascii=False)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(page_map, f, ensure_ascii=False)

    elapsed = time.time() - start
    total = len(page_map)
    found = sum(1 for p in page_map.values() if p and not p.startswith("~"))
    print(f"\n✅ 完成: {total} 条映射 ({found} 有页码, {total-found} 未匹配), 耗时 {elapsed:.0f}s")
    print(f"   未找到JSON: {skipped} 个文件")
    print(f"   保存至: {OUTPUT}")

if __name__ == "__main__":
    main()
