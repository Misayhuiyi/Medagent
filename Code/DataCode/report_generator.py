"""报告生成器：JSON → Markdown / HTML 文本。PDF 生成需要 weasyprint（后续）。"""

from __future__ import annotations

import json
from html import escape


def report_to_markdown(report: dict) -> str:
    """将报告 dict 转换为 Markdown 文本。"""
    lines = ["# MedAgent AI 辅助诊断报告\n"]
    lines.append("> 本报告由 AI 辅助生成，仅供医生参考，不能替代正式医疗文书或面诊意见。\n")

    tab_titles = {
        "history": "## 患者病史",
        "overview": "## 患者概况",
        "treatment": "## 治疗方案",
        "prediction": "## 疗效预测",
        "care": "## 人文关怀",
    }
    for tab, title in tab_titles.items():
        if tab in report:
            lines.append(f"\n{title}\n")
            lines.append(f"```json\n{json.dumps(report[tab], ensure_ascii=False, indent=2)}\n```\n")

    return "\n".join(lines)


def report_to_html(report: dict) -> str:
    """将报告 dict 转换为 HTML 文本。"""
    md = report_to_markdown(report)
    # 简易 Markdown → HTML（Demo 阶段足够）
    html = md.replace("# ", "<h1>").replace("\n## ", "</h1>\n<h2>")
    html = html.replace("```json\n", "<pre><code>").replace("\n```\n", "</code></pre>")
    html = html.replace("\n", "<br>\n")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>MedAgent 报告</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:0 auto;padding:20px}}
h1{{color:#0071e3}}h2{{color:#333}}pre{{background:#f5f5f7;padding:12px;border-radius:8px}}</style>
</head><body>{html}</body></html>"""


def report_to_pdf_bytes(report: dict) -> bytes:
    """生成一个无外部依赖的最小 PDF，内容为报告 Markdown 纯文本。"""
    text = report_to_markdown(report)
    lines = []
    for raw_line in text.splitlines():
        line = escape(raw_line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        while len(line) > 72:
            lines.append(line[:72])
            line = line[72:]
        lines.append(line)
    if not lines:
        lines = ["MedAgent AI Report"]

    content_lines = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
    for index, line in enumerate(lines[:52]):
        if index:
            content_lines.append("T*")
        safe_line = line.encode("latin-1", errors="replace").decode("latin-1")
        content_lines.append(f"({safe_line}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_index} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)
