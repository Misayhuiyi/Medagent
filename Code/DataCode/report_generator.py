"""报告生成器：Markdown / HTML / PDF。

PDF 格式对齐「肿瘤慢病化管理AI门诊报告V4」模板。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape

# 报告标题（对齐 V4 模板）
REPORT_TITLE = "肿瘤慢病化管理AI门诊报告V4"

# V4 模板起始标识行
V4_HEADER_LINE = "（红色：不良反应，蓝色：肿瘤负荷，绿色：治疗及疗效）"

# ── V4 模板章节映射 ──
# key → (章节标题, 数据源 tab key, 数据源字段名列表 | None)
# 字段名列表为 None 时使用整个 tab 的 _content
_V4_SECTIONS: list[tuple[str, str, str | list[str] | None]] = [
    # ── 来自 patient-history ──
    ("主诉",           "patient-history",  "chief_complaint"),
    ("现病史",         "patient-history",  "present_illness"),
    ("既往史",         "patient-history",  "past_history"),
    ("过敏史",         "patient-history",  "allergy_history"),
    ("个人史",         "patient-history",  "personal_history"),
    ("家族史",         "patient-history",  "family_history"),
    ("治疗史",         "patient-history",  "treatment_history"),
    # ── 来自 patient-overview ──
    ("体格检查",       "patient-overview", "physical_examination"),
    ("辅助检查",       "patient-overview", "auxiliary_examination"),
    ("AI 肿瘤负荷评估", "patient-overview", "ai_tumor_burden"),
    ("AI 肿瘤疗效评估", "patient-overview", "ai_efficacy"),
    ("AI 不良反应评估", "patient-overview", "ai_adverse_events"),
    ("AI 合并症评估",   "patient-overview", "ai_comorbidity"),
    ("AI 诊断",         "patient-overview", "diagnosis"),
    # ── 来自 treatment-plan ──
    ("AI 治疗方案",     "treatment-plan",   "treatment_plans"),
    ("不良反应处理",    "treatment-plan",   "adverse_reaction_plan"),
    ("合并症处理",      "treatment-plan",   "comorbidity_plan"),
    # ── 来自 efficacy-prediction ──
    ("肿瘤预测",        "efficacy-prediction", "tumor_prediction"),
    ("不良反应预测",    "efficacy-prediction", "adverse_prediction"),
    ("预后分析",        "efficacy-prediction", "prognosis"),
    # ── 来自 suggestions ──
    ("心理关怀",        "suggestions",      "psychological_care"),
    ("健康措施",        "suggestions",      "health_measures"),
    ("中医建议",        "suggestions",      "tcm_suggestions"),
    ("护理措施",        "suggestions",      "nursing_care"),
    ("随访计划",        "suggestions",      "follow_up_plan"),
]

# 英→中字段名映射（用于 LLM 输出中文键的兼容）
_FIELD_CN_MAP: dict[str, str] = {
    "chief_complaint": "主诉",
    "present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "family_history": "家族史",
    "treatment_history": "治疗史",
    "physical_examination": "体格检查",
    "auxiliary_examination": "辅助检查",
    "ai_tumor_burden": "AI 肿瘤负荷评估",
    "ai_efficacy": "AI 肿瘤疗效评估",
    "ai_adverse_events": "AI 不良反应评估",
    "ai_comorbidity": "AI 合并症评估",
    "diagnosis": "AI 诊断",
    "treatment_plans": "AI 治疗方案",
    "adverse_reaction_plan": "不良反应处理",
    "comorbidity_plan": "合并症处理",
    "tumor_prediction": "肿瘤预测",
    "adverse_prediction": "不良反应预测",
    "prognosis": "预后",
    "psychological_care": "心理关怀",
    "health_measures": "健康措施",
    "tcm_suggestions": "中医建议",
    "nursing_care": "护理",
    "follow_up_plan": "随访",
}


def _extract_field(tab_data: dict, field: str) -> str | None:
    """从 tab 数据中提取指定字段的文本。

    层级搜索：tab_data[field] → tab_data[中文键] → 深度查找。
    支持 str / dict(取summary) / list(拼接) 等格式。
    """
    if not isinstance(tab_data, dict):
        return None

    def _to_text(val) -> str | None:
        """将任意类型的字段值转为可读文本。"""
        if val is None:
            return None
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, bool):
            return str(val)
        if isinstance(val, (int, float)):
            return str(val)
        if isinstance(val, dict):
            # 含 summary 的对象 → 展示 summary
            if 'summary' in val and isinstance(val['summary'], str) and val['summary'].strip():
                return val['summary'].strip()
            # 含 details 数组 → 拼接
            if 'details' in val and isinstance(val['details'], list):
                parts = []
                for d in val['details']:
                    if isinstance(d, dict):
                        item = f"{d.get('system', '')}: {d.get('disease', '')}"
                        if d.get('notes'):
                            item += f"（{d['notes']}）"
                        parts.append(item)
                    elif isinstance(d, str):
                        parts.append(d)
                return '\n'.join(parts) if parts else None
            # surgicalHistory → 拼接
            if 'surgicalHistory' in val or 'surgical_history' in val:
                surgeriez = val.get('surgicalHistory') or val.get('surgical_history') or []
                if isinstance(surgeriez, list):
                    parts = [f"{s.get('surgery','')}（{s.get('date','')}）" for s in surgeriez if isinstance(s, dict)]
                    return '；'.join(parts) if parts else None
            # 其他 dict → JSON
            return None  # 让 _format_dict_value 处理
        if isinstance(val, list):
            parts = []
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    sub = ' | '.join(f"{k}: {v}" for k, v in item.items() if v is not None)
                    parts.append(sub)
            return '\n'.join(parts) if parts else None
        return None

    # 直接英文键
    if field in tab_data:
        result = _to_text(tab_data[field])
        if result:
            return result

    cn_key = _FIELD_CN_MAP.get(field, "")
    if cn_key and cn_key in tab_data:
        result = _to_text(tab_data[cn_key])
        if result:
            return result

    # 深度查找
    for v in tab_data.values():
        if isinstance(v, dict):
            found = _extract_field(v, field)
            if found:
                return found

    return None


def _format_dict_value(val) -> str:
    """将字段值格式化为可读文本。"""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, dict):
        lines = []
        for k, v in val.items():
            if k.startswith("_"):
                continue
            lines.append(f"- **{k}**：{_format_dict_value(v)}")
        return "\n".join(lines)
    if isinstance(val, list):
        lines = []
        for item in val:
            if isinstance(item, str):
                lines.append(f"- {item}")
            elif isinstance(item, dict):
                parts = [f"{k}: {v}" for k, v in item.items() if v is not None]
                lines.append(f"- {' | '.join(parts)}")
        return "\n".join(lines)
    return str(val)


def _get_content_from_tab(tab_data: dict, tab_key: str = "") -> str:
    """从 tab 数据中提取可读内容，去重并清理 Agent 中间输出。"""
    if not isinstance(tab_data, dict):
        return str(tab_data)

    md = tab_data.get("_content") or tab_data.get("content")
    if md and isinstance(md, str) and len(md) > 10:
        md = _deduplicate_section_content(md, tab_key)
        return md

    return _dict_to_text(tab_data)


def _dict_to_text(data: dict, indent: int = 0) -> str:
    """将 dict 递归转为可读文本。"""
    lines = []
    prefix = "  " * indent
    for key, value in data.items():
        if key in ("_content", "_raw", "step", "status", "error",
                    "display_name", "result"):
            continue
        if isinstance(value, str):
            if value:
                lines.append(f"{prefix}**{key}**：{value}")
        elif isinstance(value, list):
            lines.append(f"{prefix}**{key}**：")
            for item in value:
                if isinstance(item, dict):
                    item_parts = [f"{k}: {v}" for k, v in item.items()
                                   if v is not None]
                    lines.append(f"{prefix}  - {' | '.join(item_parts)}")
                else:
                    lines.append(f"{prefix}  - {item}")
        elif isinstance(value, dict):
            lines.append(f"{prefix}**{key}**：")
            lines.append(_dict_to_text(value, indent + 1))
        elif value is not None:
            lines.append(f"{prefix}**{key}**：{value}")
    return "\n".join(lines)


def _deduplicate_section_content(content: str, tab_key: str) -> str:
    """移除当前章节中明显属于其他章节的重复内容。"""
    _OTHER_SECTION_MARKERS = [
        r"\n#\s+肺癌综合诊疗报告\n",
        r"\n#\s+患者综合报告",
    ]
    _TAB_SECTION_CONFLICTS: dict[str, list[str]] = {
        "patient-history":    [r"\n#+\s*(治疗方案|疗效预测|其他建议|患者概况|预后预测)\b"],
        "patient-overview":   [r"\n#+\s*(治疗方案|疗效预测|其他建议|预后预测|患者病史总结|患者综合报告)\b"],
        "treatment-plan":     [r"\n#+\s*(患者病史|患者概况|疗效预测|其他建议|预后预测|不良反应预测)\b"],
        "efficacy-prediction":[r"\n#+\s*(治疗方案|患者病史|患者概况|其他建议|不良反应预测)\b"],
        "suggestions":        [r"\n#+\s*(治疗方案|患者病史|患者概况|疗效预测|不良反应预测)\b"],
    }

    import re
    for marker in _OTHER_SECTION_MARKERS:
        m = re.search(marker, content)
        if m:
            content = content[:m.start()].rstrip()
            break

    conflicts = _TAB_SECTION_CONFLICTS.get(tab_key, [])
    for pattern in conflicts:
        m = re.search(pattern, content)
        if m:
            content = content[:m.start()].rstrip()
            break

    return content


# ═══════════════════════════════════════════════════════════════
#  主生成函数
# ═══════════════════════════════════════════════════════════════

def report_to_markdown(report: dict, title: str = REPORT_TITLE,
                       patient_info: dict | None = None) -> str:
    """将报告 dict 转换为 V4 模板格式的 Markdown。

    Args:
        report: 报告数据 dict，key 为 tab name，value 为 tab 数据
        title: 报告标题
        patient_info: 患者信息 dict，包含 name, id, sex, age, phone,
                      department, visit_date 等字段
    """
    lines = [f"# {title}\n"]

    # 颜色标识行
    lines.append(f"{V4_HEADER_LINE}\n")

    # ── 基本信息 ──
    if patient_info:
        dept = patient_info.get("department", "肿瘤慢病化AI 门诊")
        visit_date = patient_info.get("visit_date") or patient_info.get("date", "")
        name = patient_info.get("name", "")
        sex = patient_info.get("sex") or patient_info.get("gender", "")
        age = str(patient_info.get("age", ""))
        pid = patient_info.get("id", patient_info.get("patient_id", ""))
        phone = patient_info.get("phone", "")

        lines.append(f"**科室**：{dept}  **就诊日期**：{visit_date}")
        lines.append(f"**姓名**：{name}  **性别**：{sex}  **年龄**：{age} 岁")
        lines.append(f"**门诊号**：{pid}  **联系电话**：{phone}")
        lines.append("")

    # ── V4 模板章节顺序 ──
    rendered_tabs: set = set()
    # 记录每个 Tab 是否为纯 Markdown（无结构化字段）→ 整块输出一次后跳过
    _tab_is_markdown_only: dict[str, bool] = {}
    for tab_key, tab_data in report.items():
        if not isinstance(tab_data, dict):
            continue
        _content = tab_data.get("_content", "")
        structured_keys = [k for k in tab_data
                          if not k.startswith("_")
                          and k not in ("step", "status", "error", "display_name", "result", "content")]
        _tab_is_markdown_only[tab_key] = (
            bool(_content) and len(str(_content)) > 50 and not structured_keys
        )

    for sec_title, tab_key, field_spec in _V4_SECTIONS:
        tab_data = report.get(tab_key)
        if not tab_data:
            continue

        # 纯 Markdown Tab：第一次命中时输出整块 _content，后续跳过
        if _tab_is_markdown_only.get(tab_key):
            if tab_key not in rendered_tabs:
                rendered_tabs.add(tab_key)
                content = str(tab_data.get("_content", ""))
                if content.strip():
                    # 使用 V4 模板中的第一个章节标题作为所有子章节的容器
                    lines.append(f"## {sec_title}\n")
                    lines.append(content.strip())
                    lines.append("")
            continue

        content = ""

        if isinstance(field_spec, str):
            # 单字段提取
            val = _extract_field(tab_data, field_spec) if isinstance(tab_data, dict) else None
            content = val or ""
        elif isinstance(field_spec, list):
            # 多字段提取
            parts = []
            if isinstance(tab_data, dict):
                for f in field_spec:
                    v = _extract_field(tab_data, f)
                    if v:
                        parts.append(v)
            content = "\n\n".join(parts) if parts else ""
        else:
            # 整 tab 提取
            content = _get_content_from_tab(tab_data, tab_key=tab_key)

        # 字段级提取无结果时回退到整 Tab _content（Agent 输出为 Markdown 文本块）
        if not content or not content.strip():
            content = _get_content_from_tab(tab_data, tab_key=tab_key)

        if content and content.strip():
            rendered_tabs.add(tab_key)
            lines.append(f"## {sec_title}\n")
            lines.append(content.strip())
            lines.append("")

    # 未被任何章节引用的 Tab（如新增或命名变更的 Tab）直接追加全文
    for tab_key, tab_data in report.items():
        if tab_key in rendered_tabs or tab_key.startswith("_"):
            continue
        if isinstance(tab_data, dict):
            content = _get_content_from_tab(tab_data, tab_key=tab_key)
            if content and content.strip():
                tb_cn = _FIELD_CN_MAP.get(tab_key, tab_key)
                lines.append(f"## {tb_cn}\n")
                lines.append(content.strip())
                lines.append("")

    # ── V4 特有：门诊医生修正建议 ──
    lines.append("## 门诊医生修正建议\n")
    lines.append("")
    lines.append("")

    # ── 门诊医生签字 ──
    lines.append("## 门诊医生签字\n")
    lines.append("门诊医生签字：_________\n")

    # ── 附录：注 ──
    lines.append("---\n")
    lines.append("> **注**：本报告由AI辅助生成，仅供门诊医生参考，"
                  "不能替代正式医疗文书或面诊意见。\n")
    lines.append(f"> 报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    # ── 附图页 ──
    lines.append("\n## 附图\n")
    lines.append("### AI 生成肿瘤大小变化和相对于基线百分比变化的趋势图\n")
    lines.append("（需额外图表生成支持）\n")
    lines.append("### 就诊时刻Tn 肿瘤慢病化管理三个维度权重\n")
    lines.append("（肿瘤负荷 / 肿瘤疗效 / 不良反应）\n")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  HTML 导出
# ═══════════════════════════════════════════════════════════════

def report_to_html(report: dict, title: str = REPORT_TITLE,
                   patient_info: dict | None = None) -> str:
    """将报告 dict 转换为 HTML。"""
    try:
        from DataCode.reporting.pdf_renderer_v4 import report_to_v4_html
        return report_to_v4_html(report, title, patient_info)
    except Exception:
        pass

    md = report_to_markdown(report, title, patient_info)

    lines = []
    in_code = False
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                lines.append("</code></pre>")
                in_code = False
            else:
                lines.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            lines.append(escape(line))
            continue
        if stripped.startswith("# "):
            lines.append(f"<h1>{escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            lines.append(f"<h2>{escape(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            lines.append(f"<h3>{escape(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            lines.append(f"<li>{escape(stripped[2:])}</li>")
        elif stripped.startswith("> "):
            lines.append(f"<blockquote>{escape(stripped[2:])}</blockquote>")
        elif stripped == "---":
            lines.append("<hr>")
        elif stripped.startswith("**"):
            lines.append(f"<p><strong>{escape(stripped)}</strong></p>")
        elif stripped:
            lines.append(f"<p>{escape(stripped)}</p>")
        else:
            lines.append("<br>")

    body = "\n".join(lines)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
body{{font-family:"Microsoft YaHei","SimHei",sans-serif;max-width:800px;margin:0 auto;padding:20px;line-height:1.8;color:#333;font-size:14px}}
h1{{color:#1a3a5c;font-size:22px;text-align:center;border-bottom:2px solid #1a3a5c;padding-bottom:8px}}
h2{{color:#2c5f8a;font-size:18px;border-left:4px solid #0071e3;padding-left:10px;margin-top:24px}}
h3{{color:#444;font-size:15px}}
blockquote{{background:#f0f6ff;border-left:4px solid #0071e3;padding:8px 16px;margin:12px 0;color:#555}}
pre{{background:#f5f5f7;padding:12px;border-radius:8px;overflow-x:auto;font-size:13px}}
li{{margin:4px 0}}
hr{{border:none;border-top:1px solid #ddd;margin:24px 0}}
</style>
</head>
<body>{body}</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
#  PDF 导出（fpdf2，V4 模板对齐）
# ═══════════════════════════════════════════════════════════════

def report_to_pdf_bytes(report: dict, title: str = REPORT_TITLE,
                        patient_info: dict | None = None) -> bytes:
    """生成 V4 模板 PDF。

    首选 HTML/CSS 模板 + 本机 Edge/Chrome 无头打印；不可用时回退到旧 fpdf2
    实现，保证下载接口可用。
    """
    try:
        from DataCode.reporting.pdf_renderer_v4 import report_to_v4_pdf_bytes
        return report_to_v4_pdf_bytes(report, title, patient_info)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "V4 HTML PDF renderer failed; falling back to fpdf2: %s", e
        )
        return _legacy_report_to_pdf_bytes(report, title, patient_info)


def _legacy_report_to_pdf_bytes(report: dict, title: str = REPORT_TITLE,
                                patient_info: dict | None = None) -> bytes:
    """使用 fpdf2 生成 V4 格式的中文 PDF 报告。

    字体优先级：SimHei > SimSun > MSYH > 内嵌字体。
    格式对齐「肿瘤慢病化管理AI门诊报告V4」模板。
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── 注册中文字体 ──
    # SimHei（黑体）是唯一在 fpdf2 下可靠渲染的 Windows 中文字体。
    # SimSun/MSYH 为 TTC 格式，SimKai 字宽数据异常，均导致 "Not enough horizontal space"。
    font_ok = False
    font_name = "SimHei"
    _simhei_path = os.environ.get("MEDAGENT_FONT_PATH", "")
    if not _simhei_path:
        # 从常见安装路径查找
        _candidates = [
            "C:/Windows/Fonts/simhei.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ]
        for _p in _candidates:
            if os.path.exists(_p):
                _simhei_path = _p
                break
    if _simhei_path and os.path.exists(_simhei_path):
        try:
            pdf.add_font(font_name, "", _simhei_path)
            font_ok = True
        except Exception:
            pass

    if not font_ok:
        import logging
        logging.getLogger(__name__).warning(
            "SimHei font not found (MEDAGENT_FONT_PATH=%s), PDF will use fallback (may show empty boxes)",
            _simhei_path,
        )

    def _p(text: str = "", size: int = 10, style: str = "", align: str = "L",
           color: tuple = (0, 0, 0), top_gap: int = 0) -> None:
        """辅助写行。"""
        if font_ok:
            pdf.set_font(font_name, style, size)
        else:
            pdf.set_font("Helvetica", style, size)
        r, g, b = color
        pdf.set_text_color(r, g, b)
        if top_gap:
            pdf.ln(top_gap)
        # Use explicit width (page width - margins) to avoid fpdf2 auto-width bugs
        page_w = pdf.w - pdf.r_margin - pdf.l_margin
        pdf.multi_cell(page_w, size * 0.6, text, align=align)
        pdf.set_text_color(0, 0, 0)

    def _h1(text: str) -> None:
        _p(text, size=18, align="C")

    def _h2(text: str) -> None:
        _p(text, size=13, top_gap=4)

    def _body(text: str) -> None:
        _p(text, size=10)

    def _note(text: str) -> None:
        _p(text, size=9, color=(100, 100, 100), top_gap=2)

    def _char_replacement(cp: int) -> str:
        """为不可渲染字符生成 ASCII 替代文本。"""
        _MAP: dict[int, str] = {
            0x2705: '[OK]', 0x26A0: '[!]', 0x274C: '[X]',
            0x1F4C1: '[FILE]', 0x1F4CA: '[CHART]', 0x1F4CB: '[LIST]',
            0x1F4C8: '[CHART]', 0x1F4D1: '[DOC]', 0x1F3AF: '[>]',
            0x1F48A: '[MED]', 0x1F3C3: '[EXERCISE]',
            0x2B50: '[*]', 0x1F534: '[*]', 0x1F7E2: '[*]', 0x1F7E1: '[*]',
            0x2191: '(up)', 0x2193: '(down)', 0x2192: '->',
            0x2265: '>=', 0x2248: '~=',
            0x2082: '2', 0x20E3: '',
        }
        if cp in _MAP:
            return _MAP[cp]
        if 0x2460 <= cp <= 0x2473:  # ①-⑳
            return str(cp - 0x2460 + 1)
        if 0x1F000 <= cp <= 0x1FFFF:  # Emoji
            return ''
        if 0x2600 <= cp <= 0x27BF:  # Misc Symbols
            return ''
        if 0xFE00 <= cp <= 0xFE0F:  # Variation Selectors
            return ''
        return ''

    def _clean_text(text: str) -> str:
        """移除 fpdf2 中文字体无法渲染的 Unicode 字符。

        SimHei/SimSun 等中文字体仅覆盖以下 Unicode 区块：
        - 基本拉丁 (U+0020-U+007E)
        - 拉丁补充 (U+00A0-U+00FF)
        - 常用标点 (U+2000-U+206F)
        - 制表符 (U+2500-U+257F)
        - CJK 符号 (U+3000-U+303F)
        - CJK 统一汉字 (U+4E00-U+9FFF)
        - 全角/半角 (U+FF00-U+FFEF)
        其他字符（emoji、箭头、数学符号、带圈数字等）替换为安全替代。
        """
        import re as _re

        def _is_safe(cp: int) -> bool:
            return (
                (0x0020 <= cp <= 0x007E) or   # Basic Latin
                (0x00A0 <= cp <= 0x00FF) or   # Latin-1 Supplement
                (0x2000 <= cp <= 0x206F) or   # General Punctuation
                (0x2500 <= cp <= 0x257F) or   # Box Drawing
                (0x3000 <= cp <= 0x303F) or   # CJK Symbols
                (0x4E00 <= cp <= 0x9FFF) or   # CJK Unified Ideographs
                (0xFF00 <= cp <= 0xFFEF) or   # Halfwidth/Fullwidth
                cp in (0x0A, 0x0D, 0x09, 0x20)  # newline, CR, tab, space
            )

        # 逐字符替换映射
        _UNSAFE_MAP: dict[int, str] = {}
        result: list[str] = []
        for ch in text:
            cp = ord(ch)
            if _is_safe(cp):
                result.append(ch)
                continue
            # 已知不安全字符的 ASCII 替换
            if cp not in _UNSAFE_MAP:
                replacement = _UNSAFE_MAP.get(cp)
                if replacement is None:
                    replacement = _char_replacement(cp)
                    _UNSAFE_MAP[cp] = replacement
                if replacement:
                    result.append(replacement)
            # 空字符串 = 删除该字符
        return ''.join(result)

    def _hr() -> None:
        _p("─" * 90, size=8, color=(180, 180, 180))

    # ── 第一页：标题 + 颜色标识 + 患者信息 ──
    _h1(title or "肿瘤慢病化管理AI门诊报告")
    _p(V4_HEADER_LINE, size=8, color=(150, 50, 50), align="C", top_gap=2)

    if patient_info:
        dept = patient_info.get("department", "肿瘤慢病化AI 门诊")
        visit_date = patient_info.get("visit_date") or patient_info.get("date", "")
        name = patient_info.get("name", "")
        sex = patient_info.get("sex") or patient_info.get("gender", "")
        age = str(patient_info.get("age", ""))
        pid = patient_info.get("id", patient_info.get("patient_id", ""))
        phone = patient_info.get("phone", "")

        pdf.ln(4)
        _p(f"科室：{dept}    就诊日期：{visit_date}", size=10)
        _p(f"姓名：{name}    性别：{sex}    年龄：{age} 岁", size=10)
        _p(f"门诊号：{pid}    联系电话：{phone}", size=10)
        pdf.ln(2)

    _hr()
    pdf.ln(2)

    # ── V4 模板章节顺序 ──
    has_content = False
    rendered_tabs: set = set()
    # 纯 Markdown Tab (no structured fields) → first hit outputs once, rest skip
    _tab_is_md: dict[str, bool] = {}
    for tk, td in report.items():
        if not isinstance(td, dict):
            continue
        _c = td.get("_content", "")
        sk = [k for k in td if not k.startswith("_")
              and k not in ("step", "status", "error", "display_name", "result", "content")]
        _tab_is_md[tk] = bool(_c) and len(str(_c)) > 50 and not sk

    for sec_title, tab_key, field_spec in _V4_SECTIONS:
        tab_data = report.get(tab_key)
        if not tab_data:
            continue

        # 纯 Markdown Tab：第一次命中时输出整块 _content，后续跳过
        if _tab_is_md.get(tab_key):
            if tab_key not in rendered_tabs:
                rendered_tabs.add(tab_key)
                content = str(tab_data.get("_content", ""))
                if content.strip():
                    has_content = True
                    _h2(sec_title)
                    _body(_clean_text(content.strip()))
            continue

        content = ""

        if isinstance(field_spec, str):
            val = _extract_field(tab_data, field_spec) if isinstance(tab_data, dict) else None
            content = val or ""
        elif isinstance(field_spec, list):
            parts = []
            if isinstance(tab_data, dict):
                for f in field_spec:
                    v = _extract_field(tab_data, f)
                    if v:
                        parts.append(v)
            content = "\n\n".join(parts) if parts else ""
        else:
            content = _get_content_from_tab(tab_data, tab_key=tab_key)

        # 字段级提取无结果时回退到整 Tab _content
        if not content or not content.strip():
            content = _get_content_from_tab(tab_data, tab_key=tab_key)

        if content and content.strip():
            has_content = True
            rendered_tabs.add(tab_key)
            _h2(sec_title)
            _body(_clean_text(content.strip()))

    if not has_content:
        _p("（暂无报告数据）", size=11, align="C", top_gap=6)

    # ── 门诊医生修正建议 ──
    pdf.ln(4)
    _h2("门诊医生修正建议")
    _p("", size=10)
    _p("", size=10)
    _p("", size=10)
    pdf.ln(4)

    # ── 门诊医生签字 ──
    _h2("门诊医生签字")
    _p("门诊医生签字：_________", size=10)
    pdf.ln(6)

    # ── 注 ──
    _hr()
    _note("注：本报告由AI辅助生成，仅供门诊医生参考，不能替代正式医疗文书或面诊意见。")
    _note(f"报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ── 附图页（新页） ──
    pdf.add_page()
    _h2("附图")
    pdf.ln(4)
    _p("AI 生成肿瘤大小变化和相对于基线百分比变化的趋势图", size=12, top_gap=4)
    _p("（需额外图表生成支持）", size=9, color=(150, 150, 150))
    pdf.ln(8)
    _p("就诊时刻Tn 肿瘤慢病化管理三个维度权重", size=12, top_gap=4)
    _p("（肿瘤负荷 / 肿瘤疗效 / 不良反应）", size=9, color=(150, 150, 150))

    return pdf.output()
