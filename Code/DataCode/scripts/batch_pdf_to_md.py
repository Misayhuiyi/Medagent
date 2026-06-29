"""批量 PDF → MD 转换脚本。

将指定目录下所有 PDF 文件（含子目录）转换为 Markdown 文件。
一次 exec 调用完成全部转换，避免 Agent 逐文件调用导致递归耗尽。

用法：
  python batch_pdf_to_md.py --dir "本地患者库/张三_001/2026-01-15"
  
输出：
  每个 PDF 旁生成同名 .md 文件 + 生成 conversion_report.json
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


def convert_pdf_to_md(pdf_path: Path) -> dict:
    """使用 pymupdf 将单个 PDF 转为 Markdown 文本。

    Returns:
        {"status": "success"|"failed", "charCount": int, "pageCount": int, "method": str, "error": str|None}
    """
    result = {
        "status": "failed",
        "charCount": 0,
        "pageCount": 0,
        "method": "text",
        "error": None,
    }
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        result["pageCount"] = doc.page_count

        md_lines = []
        for i, page in enumerate(doc):
            page_text = page.get_text("text")
            if page_text.strip():
                md_lines.append(page_text)
            else:
                # 空文本页 → 标记
                md_lines.append(f"[Page {i+1}: no extractable text]")

        md_content = "\n\n".join(md_lines)
        result["charCount"] = len(md_content)
        doc.close()

        if result["charCount"] > 0:
            result["status"] = "success"
            result["text"] = md_content
        else:
            result["status"] = "failed"
            result["error"] = "No text extracted from PDF"
    except ImportError:
        result["error"] = "pymupdf (fitz) not installed"
    except Exception as e:
        result["error"] = str(e)

    return result


def scan_pdf_files(root_dir: Path) -> list[Path]:
    """递归扫描目录下所有 .pdf 文件。"""
    pdf_files = []
    for entry in root_dir.rglob("*.pdf"):
        if entry.is_file():
            pdf_files.append(entry)
    return sorted(pdf_files)


def main():
    parser = argparse.ArgumentParser(description="批量 PDF → Markdown 转换")
    parser.add_argument("--dir", required=True, help="患者就诊时间目录路径")
    parser.add_argument("--output", default=None, help="输出报告路径（默认：--dir下的 conversion_report.json）")
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        print(json.dumps({"error": f"Directory not found: {args.dir}"}, ensure_ascii=False))
        sys.exit(1)

    pdf_files = scan_pdf_files(root)
    if not pdf_files:
        report = {
            "totalFiles": 0,
            "successCount": 0,
            "failCount": 0,
            "mdFilePaths": [],
            "conversionResults": [],
            "message": "No PDF files found",
        }
        out_path = args.output or str(root / "conversion_report.json")
        Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return

    conversion_results = []
    success = 0
    failed = 0
    md_paths = []
    start_time = time.time()

    for pdf_path in pdf_files:
        t0 = time.time()
        result = convert_pdf_to_md(pdf_path)
        elapsed_ms = int((time.time() - t0) * 1000)

        entry = {
            "sourceFile": str(pdf_path.relative_to(root)) if pdf_path.is_relative_to(root) else str(pdf_path),
            "targetFile": "",
            "status": result["status"],
            "method": result["method"],
            "pageCount": result["pageCount"],
            "charCount": result["charCount"],
            "conversionTimeMs": elapsed_ms,
            "error": result.get("error"),
        }

        if result["status"] == "success":
            md_path = pdf_path.with_suffix(".md")
            md_path.write_text(result["text"], encoding="utf-8")
            entry["targetFile"] = str(md_path.relative_to(root)) if md_path.is_relative_to(root) else str(md_path)
            md_paths.append(str(md_path))
            success += 1
        else:
            failed += 1

        conversion_results.append(entry)

    total_elapsed_ms = int((time.time() - start_time) * 1000)

    report = {
        "totalFiles": len(pdf_files),
        "successCount": success,
        "failCount": failed,
        "mdFilePaths": md_paths,
        "conversionResults": conversion_results,
        "totalElapsedMs": total_elapsed_ms,
    }

    out_path = args.output or str(root / "conversion_report.json")
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 简洁输出供 Agent 读取
    summary = {
        "totalFiles": len(pdf_files),
        "successCount": success,
        "failCount": failed,
        "mdFilePaths": md_paths,
        "totalElapsedMs": total_elapsed_ms,
        "reportPath": out_path,
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
