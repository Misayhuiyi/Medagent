"""报告生成器：JSON → Markdown / HTML 文本。PDF 生成需要 weasyprint（后续）。"""

from __future__ import annotations

import json
from html import escape


def report_to_markdown(report: dict) -> str:
    """将报告 dict 转换为 Markdown 文本。"""
    lines = ["# MedAgent AI 辅助诊断报告\n"]
    lines.append("> 本报告由 AI 辅助生成，仅供医生参考，不能替代正式医疗文书或面诊意见。\n")

    tab_titles = {
        "patient-history": "## 患者病史",
        "patient-overview": "## 患者概况",
        "treatment-plan": "## 治疗方案",
        "efficacy-prediction": "## 疗效预测",
        "suggestions": "## 其他建议",
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
    """使用 fpdf2 生成 Unicode PDF，支持中文渲染。"""
    from fpdf import FPDF
    import io

    pdf = FPDF()
    pdf.add_page()
    # 注册支持中文的字体（使用系统自带 SimHei / 或回退到自带字体）
    font_ok = False
    for candidate in ("SimHei", "SimSun", "Microsoft YaHei"):
        try:
            pdf.add_font(candidate, style="", fname=None, uni=True)
            pdf.set_font(candidate, size=10)
            font_ok = True
            break
        except Exception:
            continue
    if not font_ok:
        import os as _os
        # 尝试 Windows 字体目录下的黑体
        for font_file, font_name in [
            ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
            ("C:/Windows/Fonts/simsun.ttc", "SimSun"),
            ("C:/Windows/Fonts/msyh.ttc", "MSYH"),
        ]:
            try:
                if _os.path.exists(font_file):
                    pdf.add_font(font_name, fname=font_file, uni=True)
                    pdf.set_font(font_name, size=10)
                    font_ok = True
                    break
            except Exception:
                continue
    if not font_ok:
        pdf.set_font("Helvetica", size=10)

    text = report_to_markdown(report)
    for raw_line in text.splitlines():
        line = raw_line.strip() or " "
        # 处理 markdown 标题
        if line.startswith("# "):
            pdf.set_font_size(14)
            pdf.cell(0, 10, line[2:], ln=True)
            pdf.set_font_size(10)
        elif line.startswith("## "):
            pdf.set_font_size(12)
            pdf.cell(0, 10, line[3:], ln=True)
            pdf.set_font_size(10)
        else:
            # 截断过长行
            while len(line) > 90:
                pdf.cell(0, 6, line[:90], ln=True)
                line = line[90:]
            pdf.cell(0, 6, line, ln=True)

    return pdf.output()
