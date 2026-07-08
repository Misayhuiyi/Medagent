"""HTML/CSS renderer for the V4 outpatient report template."""

from __future__ import annotations

import html
import re
from typing import Iterable

from DataCode.reporting.normalizer import ReportSection, ReportViewModel


def render_v4_html(model: ReportViewModel) -> str:
    section_html = "\n".join(_render_table_row(section) for section in model.sections)
    chart_html = _render_charts(model)
    patient = model.patient
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{_e(model.title)}</title>
  <style>{V4_CSS}</style>
</head>
<body>
  <main class="report-page">
    <header class="report-header">
      <div class="legend">{_highlight_legend(model.header_line)}</div>
      <h1>{_e(model.title)}</h1>
      <div class="department">科室：{_e(patient.department)}　就诊日期：{_e(patient.visit_date)}</div>
      <table class="patient-info">
        <tr>
          <td><strong>姓名</strong>：{_e(patient.name)}</td>
          <td><strong>性别</strong>：{_e(patient.sex)}</td>
          <td><strong>年龄</strong>：{_e(patient.age)}</td>
          <td><strong>门诊号</strong>：{_e(patient.patient_id)}</td>
          <td><strong>联系电话</strong>：{_e(patient.phone)}</td>
        </tr>
      </table>
    </header>

    <table class="clinical-table">
      <tbody>
        {section_html}
      </tbody>
    </table>

    <footer class="report-note">
      <p><strong>注</strong>：本报告由AI辅助生成，仅供门诊医生参考，不能替代正式医疗文书或面诊意见。</p>
      <p>报告生成时间：{_e(model.generated_at)}</p>
    </footer>
  </main>

  <section class="report-page appendix-page">
    {chart_html}
  </section>
</body>
</html>"""


def _render_table_row(section: ReportSection) -> str:
    content = section.content.strip()
    body = markdownish_to_html(content) if content else '<div class="blank-lines"></div>'
    return f"""<tr class="section-{_e(section.tone)}">
  <th>{_e(section.title)}</th>
  <td><div class="section-body">{body}</div></td>
</tr>"""


def markdownish_to_html(text: str) -> str:
    """Small Markdown subset renderer sufficient for LLM report output."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []
    i = 0

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + _inline(" ".join(line.strip() for line in paragraph)) + "</p>")
            paragraph = []

    def flush_bullets() -> None:
        nonlocal bullets
        if bullets:
            out.append("<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in bullets) + "</ul>")
            bullets = []

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_bullets()
            i += 1
            continue

        if _is_table_start(lines, i):
            flush_paragraph()
            flush_bullets()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            out.append(_render_table(table_lines))
            continue

        if stripped.startswith("#"):
            flush_paragraph()
            flush_bullets()
            title = stripped.lstrip("#").strip()
            out.append(f"<h3>{_inline(title)}</h3>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            flush_bullets()
            out.append(f"<blockquote>{_inline(stripped.lstrip('>').strip())}</blockquote>")
            i += 1
            continue

        if re.match(r"^[-*]\s+", stripped):
            flush_paragraph()
            bullets.append(re.sub(r"^[-*]\s+", "", stripped))
            i += 1
            continue

        if re.match(r"^\d+[.、]\s+", stripped):
            flush_paragraph()
            bullets.append(re.sub(r"^\d+[.、]\s+", "", stripped))
            i += 1
            continue

        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    flush_bullets()
    return "\n".join(out)


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    current = lines[index].strip()
    nxt = lines[index + 1].strip()
    return current.startswith("|") and current.endswith("|") and bool(re.match(r"^\|[-: |]+\|$", nxt))


def _render_table(lines: Iterable[str]) -> str:
    rows = []
    for line in lines:
        if re.match(r"^\|[-: |]+\|$", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return ""
    chart_html = _render_chart_table(rows)
    if chart_html:
        return chart_html
    header = rows[0]
    body = rows[1:]
    col_count = max(1, len(header))

    def normalize_row(row: list[str]) -> list[str]:
        if len(row) < col_count:
            return row + [""] * (col_count - len(row))
        if len(row) > col_count:
            return row[:col_count - 1] + ["；".join(row[col_count - 1:])]
        return row

    header = normalize_row(header)
    html_rows = [
        "<thead><tr>" + "".join(f"<th>{_inline(cell)}</th>" for cell in header) + "</tr></thead>"
    ]
    if body:
        html_rows.append("<tbody>")
        for row in body:
            row = normalize_row(row)
            html_rows.append("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>")
        html_rows.append("</tbody>")
    return '<div class="table-wrap"><table>' + "".join(html_rows) + "</table></div>"


def _render_chart_table(rows: list[list[str]]) -> str:
    header = [cell.strip() for cell in rows[0]]
    body = rows[1:]
    if {"时间点", "指标", "数值", "单位"}.issubset(set(header)):
        return _render_trend_visual(header, body)
    if {"不良反应", "预测概率", "风险等级"}.issubset(set(header)):
        return _render_risk_visual(header, body)
    if header[:2] == ["不良反应", "T1"] and "等级说明" in header:
        return _render_heatmap_visual(header, body)
    return ""


def _cell(row: list[str], header: list[str], name: str) -> str:
    try:
        index = header.index(name)
    except ValueError:
        return ""
    return row[index].strip() if index < len(row) else ""


def _number(text: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(text or ""))
    return float(match.group(0)) if match else None


def _render_trend_visual(header: list[str], body: list[list[str]]) -> str:
    points_by_metric: dict[str, list[tuple[str, float, str, str]]] = {}
    for row in body:
        metric = _cell(row, header, "指标") or "指标"
        label = _cell(row, header, "时间点") or f"T{len(points_by_metric.get(metric, [])) + 1}"
        value = _number(_cell(row, header, "数值"))
        if value is None:
            continue
        unit = _cell(row, header, "单位")
        note = _cell(row, header, "临床解释")
        points_by_metric.setdefault(metric, []).append((label, value, unit, note))
    if not points_by_metric:
        return ""
    metric, points = max(points_by_metric.items(), key=lambda item: len(item[1]))
    if len(points) < 2:
        return ""

    width, height = 650, 270
    left, right, top, bottom = 58, 24, 26, 48
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [point[1] for point in points]
    max_v = max(values)
    min_v = min(values)
    if abs(max_v - min_v) < 1e-9:
        max_v += 1
        min_v -= 1
    pad = (max_v - min_v) * 0.12
    max_v += pad
    min_v -= pad

    def xy(index: int, value: float) -> tuple[float, float]:
        x = left + plot_w * index / max(len(points) - 1, 1)
        y = top + plot_h - (value - min_v) / (max_v - min_v) * plot_h
        return x, y

    coords = [xy(index, point[1]) for index, point in enumerate(points)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    unit = next((point[2] for point in points if point[2]), "")
    first, last = points[0], points[-1]
    delta = last[1] - first[1]
    direction = "上升" if delta > 0 else "下降" if delta < 0 else "稳定"
    summary = f"{metric}：{first[0]} {first[1]:g}{unit}，{last[0]} {last[1]:g}{unit}，总体{direction} {abs(delta):g}{unit}。"
    grid = "".join(
        f'<line x1="{left}" y1="{top + plot_h * i / 4:.1f}" x2="{width - right}" y2="{top + plot_h * i / 4:.1f}" />'
        for i in range(5)
    )
    markers = []
    labels = []
    for index, (label, value, _, _note) in enumerate(points):
        x, y = coords[index]
        markers.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" />')
        labels.append(
            f'<text x="{x:.1f}" y="{height - 24}" text-anchor="middle">{_e(label)}</text>'
            f'<text x="{x:.1f}" y="{y - 8:.1f}" text-anchor="middle">{value:g}{_e(unit)}</text>'
        )
    compact_rows = [
        "| 时间点 | 数值 | 趋势 | 解释 |",
        "|---|---:|---|---|",
        *[
            f"| {label} | {value:g}{unit} | {_cell(row, header, '变化趋势')} | {_cell(row, header, '临床解释')} |"
            for row, (label, value, unit, _note) in zip(body, points)
        ],
    ]
    return f"""<div class="chart-visual chart-visual--trend">
  <div class="chart-summary">{_inline(summary)}</div>
  <svg class="clinical-svg-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(metric)}趋势图">
    <g class="grid">{grid}</g>
    <line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" />
    <line class="axis" x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" />
    <polyline class="trend-line" points="{polyline}" />
    <g class="trend-dots">{''.join(markers)}</g>
    <g class="trend-labels">{''.join(labels)}</g>
    <text class="axis-title" x="12" y="18">{_e(metric)} / {_e(unit)}</text>
  </svg>
  {_render_plain_table(compact_rows)}
</div>"""


def _render_risk_visual(header: list[str], body: list[list[str]]) -> str:
    rows = []
    for row in body:
        name = _cell(row, header, "不良反应") or "未命名"
        probability = _cell(row, header, "预测概率")
        value = _number(probability) or 0
        risk = _cell(row, header, "风险等级")
        monitor = _cell(row, header, "监测建议")
        action = _cell(row, header, "处理建议")
        color = "red" if "高" in risk or value >= 30 else "orange" if "中" in risk or value >= 10 else "green"
        rows.append(
            f'<div class="risk-row risk-row--{color}"><span>{_inline(name)}</span>'
            f'<b>{_e(probability)}</b><i style="width:{min(value, 100):.0f}%"></i>'
            f'<em>{_inline(risk)}</em><small>{_inline(monitor or action)}</small></div>'
        )
    if not rows:
        return ""
    return '<div class="chart-visual chart-visual--risk">' + "".join(rows) + _render_plain_table(_rows_to_markdown(header, body)) + "</div>"


def _render_heatmap_visual(header: list[str], body: list[list[str]]) -> str:
    time_cols = [name for name in header if re.fullmatch(r"T\d+", name)]
    if not time_cols:
        return ""
    cards = []
    for row in body:
        name = _cell(row, header, "不良反应")
        cells = []
        for col in time_cols:
            value = _cell(row, header, col)
            grade = int(_number(value) or 0)
            cells.append(f'<span class="heat-cell heat-cell--g{max(0, min(4, grade))}">{_e(value or "-")}</span>')
        cards.append(f'<div class="heat-row"><strong>{_inline(name)}</strong>{"".join(cells)}</div>')
    legend = '<div class="heat-legend"><span>0 无</span><span>1 轻度</span><span>2 中度</span><span>3 重度</span><span>4 危重</span></div>'
    return '<div class="chart-visual chart-visual--heatmap">' + legend + "".join(cards) + _render_plain_table(_rows_to_markdown(header, body)) + "</div>"


def _rows_to_markdown(header: list[str], body: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *["| " + " | ".join(row[:len(header)] + [""] * max(0, len(header) - len(row))) + " |" for row in body],
    ]


def _render_plain_table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        if re.match(r"^\|[-: |]+\|$", line):
            continue
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    if not rows:
        return ""
    header = rows[0]
    body = rows[1:]
    return (
        '<div class="table-wrap chart-data-table"><table>'
        + "<thead><tr>" + "".join(f"<th>{_inline(cell)}</th>" for cell in header) + "</tr></thead>"
        + "<tbody>" + "".join("<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>" for row in body) + "</tbody>"
        + "</table></div>"
    )


def _inline(text: str) -> str:
    escaped = _e(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return _mark_treatment_tokens(_highlight_terms(escaped))


def _highlight_legend(text: str) -> str:
    escaped = _e(text)
    escaped = escaped.replace("红色：不良反应", '<span class="mark-red">红色：不良反应</span>')
    escaped = escaped.replace("蓝色：肿瘤负荷", '<span class="mark-blue">蓝色：肿瘤负荷</span>')
    escaped = escaped.replace("绿色：治疗及疗效", '<span class="mark-green">绿色：治疗及疗效</span>')
    return escaped


def _highlight_terms(text: str) -> str:
    red_terms = [
        "免疫检查点抑制相关肺炎", "免疫相关性肺炎", "肺泡蛋白沉积症", "炎症后肺纤维化",
        "不良反应", "毒副反应", "肺炎", "间质性炎症", "间质性肺病", "肺纤维化",
        "CIP", "ILD", "PAP", "irAE", "CTCAE", "G3", "3级",
        "气胸", "咯血", "发热", "低热", "感染", "高血糖", "肝功能异常",
        "风险", "禁忌", "警惕", "恶化", "延误", "进展风险",
    ]
    blue_terms = [
        "左肺腺癌", "肺恶性肿瘤", "肿瘤负荷", "原发灶", "靶病灶", "非靶病灶",
        "肿瘤", "病灶", "结节", "分期", "复发", "进展", "转移", "淋巴结",
        "KRAS G12C", "KRAS", "TP53", "PD-L1", "PDL1", "TMB", "RECIST", "CT", "PET-CT", "PET",
        "TNM", "cT", "pT", "N0", "N1", "N2", "N3", "M0", "M1", "IIIC", "ⅢB", "ⅠB",
    ]
    green_terms = [
        "新辅助治疗", "辅助治疗", "维持治疗", "抗血管生成", "靶向治疗", "免疫治疗",
        "治疗", "疗效", "缓解", "缩小", "稳定", "改善", "随访", "复查",
        "手术", "切除", "清扫", "化疗", "培美曲塞", "卡铂", "信迪利单抗",
        "贝伐珠单抗", "索托拉西布", "阿达格拉西布", "DLCO", "HRCT", "WLL", "MRD",
        "康复", "护理", "监测",
    ]
    for css, terms in (("red", red_terms), ("blue", blue_terms), ("green", green_terms)):
        for term in sorted(terms, key=len, reverse=True):
            text = re.sub(
                rf"(?<![\\w>])({_e(term)})(?![\\w<])",
                rf'<span class="mark-{css}">\1</span>',
                text,
            )
    return text


def _mark_treatment_tokens(text: str) -> str:
    text = re.sub(r"(\[R[1-9]\d?\])", r'<span class="ref-token">\1</span>', text)
    text = re.sub(
        r"(?<![\\w>])(Ⅰ类|ⅡA类|ⅡB类|Ⅲ类|1类|2A类|2B类|3类|I类|IIA类|IIB类|III类)(?![\\w<])",
        r'<span class="evidence-token">\1</span>',
        text,
    )
    return text


def _render_charts(model: ReportViewModel) -> str:
    return f"""
    <h2>附图</h2>
    <div class="chart-card">
      <h3>AI 生成肿瘤大小变化和相对于基线百分比变化的趋势图</h3>
      {_render_tumor_trend_chart(model.chart_source)}
    </div>
    <div class="chart-card">
      <h3>就诊时刻 Tn 肿瘤慢病化管理三个维度权重</h3>
      {_render_weight_chart(model)}
    </div>
    """


def _render_tumor_trend_chart(source: str) -> str:
    points = _extract_tumor_points(source)
    if len(points) < 2:
        return '<div class="chart-note">当前资料未提供连续、可比的肿瘤长径数据，暂不绘制趋势线；建议补充初诊影像原始报告。</div>'

    width, height = 660, 300
    left, right, top, bottom = 58, 22, 24, 52
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [p[1] for p in points]
    base = values[0] or max(values)
    pct_values = [((value - base) / base * 100) if base else 0 for value in values]
    all_values = values + pct_values
    max_value = max(all_values + [100]) * 1.12
    min_value = min(all_values + [-30, 0])

    def to_xy(index: int, value: float) -> tuple[float, float]:
        x = left + (plot_w * index / max(len(points) - 1, 1))
        ratio = (value - min_value) / max(max_value - min_value, 1)
        y = top + plot_h - ratio * plot_h
        return x, y

    size_coords = [to_xy(index, value) for index, value in enumerate(values)]
    pct_coords = [to_xy(index, value) for index, value in enumerate(pct_values)]
    size_line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in size_coords)
    pct_line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pct_coords)
    circles = []
    labels = []
    for (label, value, note), change, (x, y) in zip(points, pct_values, size_coords):
        circles.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" />')
        labels.append(
            f'<text x="{x:.1f}" y="{height - 28}" text-anchor="middle">{_e(label)}</text>'
            f'<text x="{x:.1f}" y="{y - 9:.1f}" text-anchor="middle">{value:.0f}mm / {change:+.0f}%</text>'
        )
    trend_text = _tumor_trend_summary(points, pct_values)
    grid = "\n".join(
        f'<line x1="{left}" y1="{top + plot_h * i / 4:.1f}" x2="{width - right}" y2="{top + plot_h * i / 4:.1f}" />'
        for i in range(5)
    )
    return f"""<div class="chart-summary">{_e(trend_text)}</div>
    <svg class="trend-chart" viewBox="0 0 {width} {height}" role="img" aria-label="肿瘤趋势图">
      <g class="grid">{grid}</g>
      <line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" />
      <line class="axis" x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" />
      <polyline class="trend-line" points="{size_line_points}" />
      <polyline class="trend-pct-line" points="{pct_line_points}" />
      <g class="trend-dots">{''.join(circles)}</g>
      <g class="trend-labels">{''.join(labels)}</g>
      <text class="axis-title" x="12" y="18">长径 / 基线变化</text>
      <text class="axis-title" x="145" y="18" style="fill:#2e7d32">绿色：较基线变化%</text>
    </svg>"""


def _tumor_trend_summary(points: list[tuple[str, float, str]], pct_values: list[float]) -> str:
    if len(points) < 2:
        return ""
    first_label, first_value, _ = points[0]
    last_label, last_value, _ = points[-1]
    delta = last_value - first_value
    pct = pct_values[-1] if pct_values else 0
    direction = "下降" if delta < 0 else "上升" if delta > 0 else "稳定"
    return (
        f"趋势说明：{first_label} 基线长径约 {first_value:.0f}mm，"
        f"{last_label} 最近长径约 {last_value:.0f}mm，较基线{direction} {abs(delta):.0f}mm（{pct:+.0f}%）。"
        "蓝线表示肿瘤长径，绿线表示相对基线变化百分比。"
    )


def _extract_tumor_points(source: str) -> list[tuple[str, float, str]]:
    results: list[tuple[str, float, str]] = []
    seen: set[tuple[str, int]] = set()
    pattern = re.compile(
        r"(?P<a>\d+(?:\.\d+)?)\s*(?P<u1>cm|mm)?\s*[×xX*]\s*(?P<b>\d+(?:\.\d+)?)\s*(?P<u2>cm|mm)",
        re.I,
    )
    for match in pattern.finditer(source):
        context = source[max(0, match.start() - 120):match.end() + 80]
        unit = (match.group("u1") or match.group("u2") or "mm").lower()
        value = max(float(match.group("a")), float(match.group("b")))
        if unit == "cm":
            value *= 10
        date_match = list(re.finditer(r"20\d{2}(?:[-/年]\d{1,2}(?:[-/月]\d{1,2}日?)?)?", context))
        label = date_match[-1].group(0).replace("年", "-").replace("月", "-").replace("日", "") if date_match else f"T{len(results) + 1}"
        key = (label, round(value))
        if key in seen:
            continue
        seen.add(key)
        results.append((label, value, match.group(0)))
        if len(results) >= 8:
            break
    results.sort(key=lambda item: (_date_sort_key(item[0]), item[0]))
    return results


def _date_sort_key(label: str) -> int:
    match = re.search(r"(20\d{2})[-/年]?(\d{1,2})?[-/月]?(\d{1,2})?", label)
    if not match:
        return 99999999
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    return year * 10000 + month * 100 + day


def _render_weight_chart(model: ReportViewModel) -> str:
    source_by_tone = {
        "red": " ".join(s.content for s in model.sections if s.tone == "adverse"),
        "blue": " ".join(s.content for s in model.sections if s.tone == "burden"),
        "green": " ".join(s.content for s in model.sections if s.tone == "treatment"),
    }
    scores = {
        "blue": _keyword_score(source_by_tone["blue"], ["肿瘤", "病灶", "分期", "转移", "负荷", "复发"]),
        "green": _keyword_score(source_by_tone["green"], ["治疗", "疗效", "随访", "康复", "手术", "用药"]),
        "red": _keyword_score(source_by_tone["red"], ["不良反应", "肺炎", "气胸", "风险", "合并症", "禁忌"]),
    }
    total = sum(scores.values()) or 1
    items = [
        ("blue", "肿瘤负荷", scores["blue"] / total),
        ("green", "治疗及疗效", scores["green"] / total),
        ("red", "不良反应", scores["red"] / total),
    ]
    bars = []
    for index, (css, label, ratio) in enumerate(items):
        y = 42 + index * 64
        width = 430 * ratio
        bars.append(
            f'<text x="16" y="{y + 18}">{label}</text>'
            f'<rect class="bar-bg" x="120" y="{y}" width="430" height="28" rx="3" />'
            f'<rect class="bar-{css}" x="120" y="{y}" width="{width:.1f}" height="28" rx="3" />'
            f'<text x="568" y="{y + 18}" text-anchor="end">{ratio * 100:.0f}%</text>'
        )
    return f"""<svg class="weight-chart" viewBox="0 0 600 245" role="img" aria-label="三个维度权重图">
      <text class="chart-subtitle" x="16" y="22">基于本次报告各维度证据密度自动估算</text>
      {''.join(bars)}
    </svg>"""


def _keyword_score(text: str, terms: list[str]) -> int:
    return max(1, sum(text.count(term) for term in terms))


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


V4_CSS = r"""
@page {
  size: A4;
  margin: 12mm 10mm;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: #fff;
  color: #000;
  font-family: "SimSun", "Songti SC", "Microsoft YaHei", "Noto Sans CJK SC", serif;
  font-size: 10.5px;
  line-height: 1.55;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}

.report-page {
  width: 190mm;
  margin: 0 auto;
}

@media screen {
  body {
    background: #f1f1f1;
  }

  .report-page {
    min-height: 267mm;
    padding: 0;
    background: #fff;
  }
}

@media print {
  .report-page {
    width: auto;
    margin: 0;
  }
}

.report-header {
  margin-bottom: 4px;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

h1 {
  margin: 0 0 2px;
  text-align: center;
  color: #000;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0;
}

.legend {
  margin: 0 0 1px;
  text-align: center;
  font-size: 9.5px;
  font-weight: 700;
}

.department {
  margin-bottom: 3px;
  text-align: center;
  font-size: 10px;
  font-weight: 700;
}

.patient-info {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 4px;
  border: 1px solid #000;
  table-layout: fixed;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.patient-info td {
  padding: 2px 4px;
  border: 1px solid #000;
  vertical-align: middle;
  white-space: nowrap;
}

.clinical-table {
  width: 100%;
  border-collapse: collapse;
  border: 1.2px solid #000;
  table-layout: fixed;
}

.clinical-table thead {
  display: table-header-group;
}

.clinical-table tr {
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.clinical-table th,
.clinical-table td {
  border: 1px solid #000;
  vertical-align: top;
}

.clinical-table th {
  width: 56px;
  padding: 4px 3px;
  text-align: center;
  font-size: 10.5px;
  font-weight: 700;
  background: #fff;
}

.clinical-table td {
  padding: 4px 6px;
}

.section-body p {
  margin: 0 0 3px;
  text-align: justify;
  orphans: 3;
  widows: 3;
}

.section-body {
  overflow-wrap: anywhere;
  word-break: normal;
  line-break: strict;
  hyphens: none;
}

.section-body h3 {
  margin: 3px 0 2px;
  color: #000;
  font-size: 10.5px;
  break-after: avoid-page;
  page-break-after: avoid;
}

.section-body ul {
  margin: 2px 0 3px 15px;
  padding: 0;
  orphans: 3;
  widows: 3;
}

.section-body li {
  margin: 1px 0;
}

blockquote {
  margin: 3px 0;
  padding: 2px 5px;
  border-left: 2px solid #888;
  background: #fafafa;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.table-wrap {
  width: 100%;
  margin: 2px 0 4px;
  overflow: visible;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 9.5px;
}

thead {
  display: table-header-group;
}

th,
td {
  padding: 2px 3px;
  border: 1px solid #000;
  vertical-align: top;
  word-break: normal;
  overflow-wrap: anywhere;
  line-break: strict;
  hyphens: none;
}

tr {
  break-inside: avoid-page;
  page-break-inside: avoid;
}

th {
  background: #f5f5f5;
  color: #000;
  font-weight: 700;
}

code {
  font-family: Consolas, "Microsoft YaHei", monospace;
  font-size: 9px;
}

.blank-lines {
  height: 36px;
}

.report-note {
  margin-top: 4px;
  color: #333;
  font-size: 9px;
}

.report-note p {
  margin: 2px 0;
}

.appendix-page {
  break-before: page;
  page-break-before: always;
}

.appendix-page h2 {
  margin: 0 0 12px;
  text-align: center;
  font-size: 16px;
}

.chart-card {
  margin: 0 0 18px;
  padding: 8px;
  border: 1px solid #000;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.chart-card h3 {
  margin: 0 0 6px;
  text-align: center;
  font-size: 12px;
}

.trend-chart,
.weight-chart {
  width: 100%;
  height: auto;
  display: block;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.grid line {
  stroke: #d7d7d7;
  stroke-width: 1;
}

.axis {
  stroke: #111;
  stroke-width: 1.2;
}

.trend-line {
  fill: none;
  stroke: #1976d2;
  stroke-width: 2.4;
}

.trend-pct-line {
  fill: none;
  stroke: #2e7d32;
  stroke-width: 2.2;
  stroke-dasharray: 6 4;
}

.trend-dots circle {
  fill: #1976d2;
  stroke: #fff;
  stroke-width: 1.5;
}

.trend-labels,
.axis-title,
.chart-subtitle {
  font-size: 11px;
  fill: #111;
}

.bar-bg {
  fill: #eeeeee;
}

.bar-blue {
  fill: #1976d2;
}

.bar-green {
  fill: #2e7d32;
}

.bar-red {
  fill: #d32f2f;
}

.chart-note {
  min-height: 90px;
  padding: 18px;
  border: 1px dashed #777;
  text-align: center;
  color: #333;
}

.chart-summary {
  margin: 2px 0 6px;
  color: #333;
  font-size: 10.5px;
  line-height: 1.55;
}

.chart-visual {
  margin: 3px 0 6px;
  padding: 5px 6px;
  border: 1px solid #777;
  background: #fff;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.clinical-svg-chart {
  width: 100%;
  height: auto;
  display: block;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.chart-data-table {
  margin-top: 4px;
}

.chart-data-table table {
  font-size: 8.8px;
}

.risk-row {
  min-height: 28px;
  margin: 3px 0;
  display: grid;
  grid-template-columns: 92px 48px 1fr 44px 1.4fr;
  gap: 5px;
  align-items: center;
  font-size: 9.3px;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.risk-row b,
.risk-row em,
.risk-row small {
  font-style: normal;
  font-weight: 700;
}

.risk-row small {
  color: #333;
  font-weight: 400;
}

.risk-row i {
  height: 8px;
  border-radius: 0;
  display: block;
  background: #2e7d32;
}

.risk-row--orange i {
  background: #ef8f00;
}

.risk-row--red i {
  background: #d32f2f;
}

.risk-row--green em {
  color: #2e7d32;
}

.risk-row--orange em {
  color: #8a5a00;
}

.risk-row--red em {
  color: #d32f2f;
}

.heat-legend {
  margin-bottom: 5px;
  display: flex;
  gap: 8px;
  font-size: 9px;
}

.heat-row {
  display: grid;
  grid-template-columns: 94px repeat(5, 1fr);
  gap: 3px;
  align-items: stretch;
  margin: 3px 0;
  font-size: 9.2px;
  break-inside: avoid-page;
  page-break-inside: avoid;
}

.heat-row strong {
  padding: 3px 4px;
  border: 1px solid #999;
  font-weight: 700;
}

.heat-cell {
  min-height: 20px;
  padding: 3px 2px;
  border: 1px solid #999;
  text-align: center;
  font-weight: 700;
}

.heat-cell--g0 {
  background: #f3f7f3;
  color: #2e7d32;
}

.heat-cell--g1 {
  background: #e8f3ff;
  color: #1976d2;
}

.heat-cell--g2 {
  background: #fff5d9;
  color: #8a5a00;
}

.heat-cell--g3,
.heat-cell--g4 {
  background: #fde3e1;
  color: #d32f2f;
}

.mark-red {
  color: #d32f2f;
  font-weight: 700;
}

.mark-blue {
  color: #1976d2;
  font-weight: 700;
}

.mark-green {
  color: #2e7d32;
  font-weight: 700;
}

.ref-token {
  color: #5f4b00;
  font-weight: 700;
  white-space: nowrap;
}

.evidence-token {
  color: #2e7d32;
  font-weight: 700;
  white-space: nowrap;
}
"""
