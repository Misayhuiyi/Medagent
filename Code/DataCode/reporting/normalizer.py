"""Normalize report tabs into a V4 template view model.

The React UI keeps using the existing five-tab report shape. Export code uses
this module to create a stable, template-oriented representation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


V4_HEADER_LINE = "（红色：不良反应，蓝色：肿瘤负荷，绿色：治疗及疗效）"


@dataclass
class PatientInfo:
    department: str = "肿瘤慢病化AI 门诊"
    visit_date: str = ""
    name: str = ""
    sex: str = ""
    age: str = ""
    patient_id: str = ""
    phone: str = ""


@dataclass
class ReportSection:
    title: str
    content: str
    tone: str = "default"


@dataclass
class ReportViewModel:
    title: str
    header_line: str
    patient: PatientInfo
    sections: list[ReportSection] = field(default_factory=list)
    chart_source: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))


FIELD_CN_MAP: dict[str, str] = {
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


V4_SECTIONS: list[tuple[str, str, str | None, str]] = [
    ("主诉", "patient-history", "chief_complaint", "default"),
    ("现病史", "patient-history", "present_illness", "default"),
    ("既往史", "patient-history", "past_history", "default"),
    ("过敏史", "patient-history", "allergy_history", "adverse"),
    ("个人史", "patient-history", "personal_history", "default"),
    ("家族史", "patient-history", "family_history", "default"),
    ("治疗史", "patient-history", "treatment_history", "treatment"),
    ("体格检查", "patient-overview", "physical_examination", "default"),
    ("辅助检查", "patient-overview", "auxiliary_examination", "default"),
    ("AI 肿瘤负荷评估", "patient-overview", "ai_tumor_burden", "burden"),
    ("AI 肿瘤疗效评估", "patient-overview", "ai_efficacy", "treatment"),
    ("AI 不良反应评估", "patient-overview", "ai_adverse_events", "adverse"),
    ("AI 合并症评估", "patient-overview", "ai_comorbidity", "adverse"),
    ("AI 诊断", "patient-overview", "diagnosis", "default"),
    ("AI 治疗方案", "treatment-plan", "treatment_plans", "treatment"),
    ("不良反应处理", "treatment-plan", "adverse_reaction_plan", "adverse"),
    ("合并症处理", "treatment-plan", "comorbidity_plan", "adverse"),
    ("肿瘤预测", "efficacy-prediction", "tumor_prediction", "burden"),
    ("不良反应预测", "efficacy-prediction", "adverse_prediction", "adverse"),
    ("预后分析", "efficacy-prediction", "prognosis", "default"),
    ("心理关怀", "suggestions", "psychological_care", "default"),
    ("健康措施", "suggestions", "health_measures", "treatment"),
    ("中医建议", "suggestions", "tcm_suggestions", "treatment"),
    ("护理措施", "suggestions", "nursing_care", "adverse"),
    ("随访计划", "suggestions", "follow_up_plan", "treatment"),
]


SECTION_PATTERNS: dict[str, list[str]] = {
    "主诉": ["主诉", "主诉与现病史", "首发症状"],
    "现病史": ["现病史"],
    "既往史": ["既往史"],
    "过敏史": ["过敏史"],
    "个人史": ["个人史"],
    "家族史": ["家族史"],
    "治疗史": ["治疗史", "重要治疗过程", "治疗过程", "治疗经过"],
    "体格检查": ["体格检查", "查体", "生命体征"],
    "辅助检查": ["辅助检查", "检查结果", "影像学检查", "实验室检查"],
    "AI 肿瘤负荷评估": ["肿瘤负荷", "疗效检测曲线", "肿瘤大小变化", "病灶"],
    "AI 肿瘤疗效评估": ["疗效评估", "疗效评价", "疗效预测评分"],
    "AI 不良反应评估": ["不良反应热力图", "不良反应评估", "不良反应预测评分"],
    "AI 合并症评估": ["合并症", "并发症", "基础疾病"],
    "AI 诊断": ["诊断", "核心诊断", "综合评估结论"],
    "AI 治疗方案": ["针对肿瘤的治疗方案", "综合治疗计划", "完整治疗方案"],
    "不良反应处理": ["针对不良反应的治疗方案", "不良反应处理", "重要风险提示"],
    "合并症处理": ["针对合并症的治疗方案", "合并症处理"],
    "肿瘤预测": ["疗效预测评分与肿瘤大小变化曲线", "肿瘤大小变化预测曲线", "疗效预测"],
    "不良反应预测": ["不良反应预测评分报告", "不良反应预测"],
    "预后分析": ["预后预测报告", "预后影响因素", "预后"],
    "心理关怀": ["心理疏导", "心理关怀"],
    "健康措施": ["健康教育", "生活方式调整", "用药依从性"],
    "中医建议": ["中医中药辅助康复", "中医建议"],
    "护理措施": ["护理措施", "日常护理", "治疗相关护理"],
    "随访计划": ["随访计划", "具体随访建议"],
}


OUTPUT_NOISE_MARKERS = [
    "合并输出JSON",
    "```json",
    "【当前步骤上下文",
    "各子Skill输出文件",
    "参考文献汇总",
    "请按上述步骤执行",
    "所有阶段已完成",
    "所有子Skill已执行完毕",
    "三个子Skill已全部成功执行",
    "现在让我整合",
    "让我直接整理输出",
    "现在进行**步骤",
    "第1阶段和第2阶段全部完成",
]

STATUS_SYMBOLS = "✅❓⚠️⚡✳️📋🎯🔴🟠🟡🟢🔵🅰🅱🅲🅳🅴❌"
SUPPLEMENTAL_SECTION_TITLE = "补充资料"
MAX_SUPPLEMENTAL_SECTIONS = 12


def normalize_patient_info(patient_info: dict | None) -> PatientInfo:
    data = patient_info or {}
    return PatientInfo(
        department=str(data.get("department") or "肿瘤慢病化AI 门诊"),
        visit_date=str(data.get("visit_date") or data.get("date") or ""),
        name=str(data.get("name") or ""),
        sex=str(data.get("sex") or data.get("gender") or ""),
        age=str(data.get("age") or ""),
        patient_id=str(data.get("id") or data.get("patient_id") or ""),
        phone=str(data.get("phone") or ""),
    )


def normalize_report(report: dict, title: str, patient_info: dict | None = None) -> ReportViewModel:
    model = ReportViewModel(
        title=title,
        header_line=V4_HEADER_LINE,
        patient=normalize_patient_info(patient_info),
    )
    raw_tabs = {
        str(tab_key): _get_raw_content(tab_data)
        for tab_key, tab_data in report.items()
        if isinstance(tab_data, dict)
    }
    cleaned_tabs = {
        tab_key: _clean_section_content(content, tab_key)
        for tab_key, content in raw_tabs.items()
    }
    model.chart_source = "\n\n".join(raw_tabs.values())

    matches_found: dict[str, set[str]] = {}

    for title_text, tab_key, field, tone in V4_SECTIONS:
        tab_data = report.get(tab_key)
        content = ""
        if not isinstance(tab_data, dict):
            tab_data = {}

        if isinstance(tab_data, dict) and not _is_markdown_only_tab(tab_data):
            content = _extract_field(tab_data, field or "") if field else _get_content_from_tab(tab_data, tab_key)
        else:
            content = _extract_markdown_section(cleaned_tabs.get(tab_key, ""), title_text)

        if not content:
            content = _extract_markdown_section(model.chart_source, title_text)
        if not content and title_text == "主诉":
            content = _infer_chief_complaint(model.chart_source)

        if content and content.strip():
            model.sections.append(ReportSection(title=title_text, content=_polish_content(content), tone=tone))
            matches_found.setdefault(tab_key, set()).add(title_text)

    # Collect unmatched useful sections into one stable row. This preserves
    # extra information without expanding the fixed V4 table into dozens of
    # noisy rows from LLM headings, emoji labels, ASCII charts, or tool chatter.
    supplemental_parts: list[str] = []
    for tab_key, cleaned in cleaned_tabs.items():
        sections = _split_markdown_sections(cleaned)
        for heading, body in sections:
            heading = _clean_heading_title(heading)
            norm = _normalize_heading(heading)
            if _is_noise_heading(heading, body):
                continue
            is_matched = False
            for patterns in SECTION_PATTERNS.values():
                if any(p and _normalize_heading(p) in norm for p in patterns):
                    is_matched = True
                    break
            if not is_matched and body.strip() and len(body.strip()) > 10:
                polished = _polish_content(body, max_chars=1600)
                if polished:
                    supplemental_parts.append(f"【{heading}】\n{polished}")
                if len(supplemental_parts) >= MAX_SUPPLEMENTAL_SECTIONS:
                    break
        if len(supplemental_parts) >= MAX_SUPPLEMENTAL_SECTIONS:
            break

    if supplemental_parts:
        model.sections.append(ReportSection(
            title=SUPPLEMENTAL_SECTION_TITLE,
            content="\n\n".join(supplemental_parts),
            tone="default",
        ))

    for tab_key, tab_data in report.items():
        if str(tab_key) in cleaned_tabs or str(tab_key).startswith("_"):
            continue
        if isinstance(tab_data, dict):
            content = _get_content_from_tab(tab_data, tab_key)
        else:
            content = str(tab_data)
        if content and content.strip():
            model.sections.append(ReportSection(title=str(tab_key), content=content.strip()))

    model.sections.extend([
        ReportSection("门诊医生修正建议", "", "default"),
        ReportSection("门诊医生签字", "门诊医生签字：_________", "default"),
    ])
    return model


def _get_raw_content(tab_data: Any) -> str:
    if isinstance(tab_data, dict):
        for key in ("_content", "result", "content"):
            value = tab_data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return _dict_to_text(tab_data)
    return str(tab_data or "")


def _is_markdown_only_tab(tab_data: dict) -> bool:
    content = tab_data.get("_content") or tab_data.get("content") or tab_data.get("result")
    structured_keys = [
        key for key in tab_data
        if not str(key).startswith("_")
        and key not in ("step", "status", "error", "display_name", "result", "content")
    ]
    return bool(isinstance(content, str) and len(content.strip()) > 50 and not structured_keys)


def _extract_field(tab_data: dict, field: str) -> str:
    if not field:
        return ""
    value = _lookup_value(tab_data, field)
    if value is None:
        cn_key = FIELD_CN_MAP.get(field, "")
        value = _lookup_value(tab_data, cn_key) if cn_key else None
    if value is None:
        return ""
    return _value_to_text(value)


def _lookup_value(data: Any, key: str) -> Any:
    if not key or not isinstance(data, dict):
        return None
    if key in data:
        return data[key]
    for value in data.values():
        if isinstance(value, dict):
            found = _lookup_value(value, key)
            if found is not None:
                return found
    return None


def _get_content_from_tab(tab_data: dict, tab_key: str = "") -> str:
    content = tab_data.get("_content") or tab_data.get("content") or tab_data.get("result")
    if isinstance(content, str) and len(content.strip()) > 10:
        return _clean_section_content(content, tab_key)
    return _dict_to_text(tab_data)


def _value_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(" | ".join(f"{k}: {_value_to_text(v)}" for k, v in item.items() if v is not None))
            else:
                parts.append(_value_to_text(item))
        return "\n".join(f"- {part}" for part in parts if part)
    if isinstance(value, dict):
        if isinstance(value.get("summary"), str):
            return value["summary"].strip()
        return _dict_to_text(value)
    return str(value)


def _dict_to_text(data: dict, indent: int = 0) -> str:
    lines: list[str] = []
    prefix = "  " * indent
    for key, value in data.items():
        if key in ("_content", "_raw", "step", "status", "error", "display_name", "result", "content"):
            continue
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            lines.append(f"{prefix}**{key}**：")
            nested = _dict_to_text(value, indent + 1)
            if nested:
                lines.append(nested)
        elif isinstance(value, list):
            text = _value_to_text(value)
            if text:
                lines.append(f"{prefix}**{key}**：\n{text}")
        else:
            lines.append(f"{prefix}**{key}**：{_value_to_text(value)}")
    return "\n".join(lines)


def _clean_section_content(content: str, tab_key: str) -> str:
    content = content.strip()
    if not content:
        return ""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    for marker in OUTPUT_NOISE_MARKERS:
        pos = content.find(marker)
        if pos > 0:
            content = content[:pos].rstrip()
    content = re.sub(r"(?s)```json.*?```", "", content)
    content = re.sub(r"(?im)^好的[，,].{0,80}$", "", content)
    content = re.sub(r"(?im)^现在我.{0,120}$", "", content)
    content = re.sub(r"(?im)^第\d+阶段完成.*$", "", content)
    content = re.sub(r"(?im)^让我整合.{0,120}$", "", content)
    conflicts: dict[str, list[str]] = {
        "patient-history": ["\n# 治疗方案", "\n# 疗效预测", "\n# 其他建议", "\n# 患者概况"],
        "patient-overview": ["\n# 治疗方案", "\n# 疗效预测", "\n# 其他建议", "\n# 患者病史"],
        "treatment-plan": ["\n# 患者病史", "\n# 患者概况", "\n# 疗效预测", "\n# 其他建议"],
        "efficacy-prediction": ["\n# 治疗方案", "\n# 患者病史", "\n# 患者概况", "\n# 其他建议"],
        "suggestions": ["\n# 治疗方案", "\n# 患者病史", "\n# 患者概况", "\n# 疗效预测"],
    }
    for marker in conflicts.get(tab_key, []):
        pos = content.find(marker)
        if pos > 0:
            return content[:pos].rstrip()
    return content


def _extract_markdown_section(content: str, section_title: str) -> str:
    if not content:
        return ""
    if section_title == "主诉":
        return _extract_chief_complaint_section(content)
    candidates = SECTION_PATTERNS.get(section_title, [section_title])
    ranged = _extract_heading_range(content, candidates)
    if ranged:
        return _polish_content(ranged)
    sections = _split_markdown_sections(content)
    for heading, body in sections:
        normalized_heading = _normalize_heading(heading)
        if any(_normalize_heading(candidate) in normalized_heading for candidate in candidates):
            return _polish_content(body)
    if section_title == "辅助检查":
        return _extract_exam_lines(content)
    return ""


def _extract_heading_range(content: str, candidates: list[str]) -> str:
    lines = content.splitlines()
    normalized_candidates = [_normalize_heading(candidate) for candidate in candidates]
    start_index = -1
    start_level = 99
    start_kind = ""

    for index, line in enumerate(lines):
        heading = _line_heading_text(line)
        if not heading:
            continue
        normalized = _normalize_heading(heading)
        if any(candidate and candidate in normalized for candidate in normalized_candidates):
            start_index = index
            start_level, start_kind = _heading_level(line)
            break

    if start_index < 0:
        return ""

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if not _line_heading_text(lines[index]):
            continue
        level, kind = _heading_level(lines[index])
        if _is_peer_or_parent_heading(start_level, start_kind, level, kind):
            end_index = index
            break

    body = "\n".join(lines[start_index + 1:end_index]).strip()
    return body


def _line_heading_text(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("|"):
        return ""
    patterns = [
        r"^#{1,5}\s+(.+)$",
        r"^[一二三四五六七八九十]+[、.．]\s*(.+)$",
        r"^\d+(?:\.\d+)*[、.．]?\s+(.+)$",
        r"^[🅰🅱🅲🅳🅴]\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, stripped)
        if match:
            return match.group(1).strip()
    return ""


def _heading_level(line: str) -> tuple[int, str]:
    stripped = line.strip()
    if stripped.startswith("#"):
        return len(stripped) - len(stripped.lstrip("#")), "hash"
    if re.match(r"^[一二三四五六七八九十]+[、.．]", stripped):
        return 1, "cn"
    if re.match(r"^[🅰🅱🅲🅳🅴]", stripped):
        return 2, "letter"
    number_match = re.match(r"^(\d+(?:\.\d+)*)", stripped)
    if number_match:
        return number_match.group(1).count(".") + 1, "num"
    return 99, "text"


def _is_peer_or_parent_heading(start_level: int, start_kind: str, level: int, kind: str) -> bool:
    if start_kind == kind and level <= start_level:
        return True
    if start_kind in {"cn", "letter"} and kind == "cn" and level <= start_level:
        return True
    if start_kind == "hash" and kind == "hash" and level <= start_level:
        return True
    return False


def _split_markdown_sections(content: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(
        r"(?m)^\s*(?:#{1,5}\s*)?(?:[一二三四五六七八九十]+[、.．]\s*|\d+(?:\.\d+)*[、.．]?\s*)?([^\n#|]{2,80})\s*$",
        content,
    ))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        heading = _clean_heading_title(heading)
        if _looks_like_body_line(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if body:
            result.append((heading, body))
    return result


def _looks_like_body_line(text: str) -> bool:
    if len(text) > 48 and any(ch in text for ch in "，。；："):
        return True
    if text.startswith(("-", "*", "|", ">", "```")):
        return True
    if re.fullmatch(r"[─━═■□█▌▐▔▁▂▃▄▅▆▇\s]+", text):
        return True
    return False


def _normalize_heading(text: str) -> str:
    text = re.sub(r"[*`#✅⚠️📋🅰🅱🅲🅳🅴❌]", "", text)
    text = re.sub(r"^\s*(?:[一二三四五六七八九十]+[、.．]|\d+(?:\.\d+)*[、.．]?)\s*", "", text)
    return re.sub(r"\s+", "", text)


def _clean_heading_title(text: str) -> str:
    text = _clean_display_line(text)
    text = re.sub(r"^\s*(?:[一二三四五六七八九十]+[、.．]|\d+(?:\.\d+)*[、.．]?)\s*", "", text)
    text = text.strip(" ：:.-")
    return text


def _is_noise_heading(heading: str, body: str = "") -> bool:
    norm = _normalize_heading(heading)
    if not norm:
        return True
    noise_headings = {
        "合并输出JSON",
        "参考文献汇总",
        "基本信息",
        "报告生成依据",
        "报告生成时间",
        "患者概况报告",
        "患者病史总结报告",
        "完整治疗方案报告",
        "疗效预测报告",
        "其他建议报告",
    }
    if norm in {_normalize_heading(item) for item in noise_headings}:
        return True
    if any(marker in heading or marker in body[:120] for marker in OUTPUT_NOISE_MARKERS):
        return True
    if len(norm) > 42:
        return True
    return False


def _extract_chief_complaint_section(content: str) -> str:
    sections = _split_markdown_sections(content)
    for heading, body in sections:
        norm = _normalize_heading(heading)
        if norm == "主诉" or norm == "主诉与现病史":
            first = []
            for line in body.splitlines():
                clean = _clean_display_line(line)
                if not clean:
                    continue
                if any(word in clean for word in ("病理类型", "驱动基因", "分子分型", "治疗方案")):
                    continue
                first.append(clean)
                if len(first) >= 3:
                    break
            return "\n".join(first)
    return ""


def _extract_exam_lines(content: str) -> str:
    lines = []
    for line in content.splitlines():
        if any(word in line for word in ("CT", "PET", "MRI", "病理", "免疫组化", "KRAS", "PD-L1", "TMB", "肿瘤标志物", "肺功能")):
            stripped = line.strip(" -*|")
            if 8 <= len(stripped) <= 160:
                lines.append(stripped)
        if len(lines) >= 8:
            break
    return "\n".join(f"- {line}" for line in lines)


def _infer_chief_complaint(content: str) -> str:
    for pattern in (
        r"(\d{4}年\d{1,2}月\d{1,2}日因[^。\n]{4,80})",
        r"(\d{4}-\d{1,2}-\d{1,2}[^。\n]{0,20}因[^。\n]{4,80})",
        r"(因[^。\n]{2,40}(?:就诊|入院|发现)[^。\n]{0,40})",
    ):
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip(" ，。；")
    return ""


def _polish_content(content: str, max_chars: int = 12000) -> str:
    content = _clean_section_content(content, "")
    content = _markdown_tables_to_lines(content)
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line in ("---", "——"):
            continue
        line = _clean_display_line(line)
        if _is_ascii_chart_line(line):
            continue
        if line.startswith("|") and set(line.replace("|", "").strip()) <= {"-", ":"}:
            continue
        if any(marker in line for marker in OUTPUT_NOISE_MARKERS):
            continue
        if line.startswith(("好的，", "现在我", "让我整合", "第2阶段完成", "第1阶段", "所有阶段")):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        last_break = max(cut.rfind("\n"), cut.rfind("。"), cut.rfind("；"))
        if last_break > max_chars * 0.55:
            cut = cut[:last_break + 1]
        text = cut.rstrip()
    return text


def _markdown_tables_to_lines(content: str) -> str:
    lines = content.splitlines()
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|"):
            block: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            output.extend(_table_block_to_lines(block))
            continue
        output.append(line)
        i += 1
    return "\n".join(output)


def _table_block_to_lines(block: list[str]) -> list[str]:
    rows: list[list[str]] = []
    for raw in block:
        stripped = raw.strip()
        if re.match(r"^\|[-: |]+\|$", stripped):
            continue
        cells = [_clean_table_cell(cell) for cell in stripped.strip("|").split("|")]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    if not rows:
        return []

    header = rows[0]
    body = rows[1:]
    if not body:
        return ["；".join(header)]

    converted: list[str] = []
    for row in body[:10]:
        if len(row) == len(header) and len(header) <= 7:
            converted.append(_row_to_sentence(header, row))
        elif row:
            converted.append("；".join(row))
    return [line for line in converted if line]


def _row_to_sentence(header: list[str], row: list[str]) -> str:
    label = row[0]
    rest = []
    for key, value in zip(header[1:], row[1:]):
        if not value or value in {"—", "-", "NA"}:
            continue
        if key in {"内容", "详情", "具体内容", "事件", "说明", "管理建议", "临床管理"}:
            rest.append(value)
        else:
            rest.append(f"{key}：{value}")
    if not rest:
        return label
    return f"- {label}：" + "；".join(rest)


def _clean_table_cell(cell: str) -> str:
    cell = _clean_display_line(cell)
    cell = re.sub(r"\s+", " ", cell).strip()
    return cell


def _clean_display_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\ufe0f\u20e3]", "", line)
    line = re.sub(rf"[{re.escape(STATUS_SYMBOLS)}]", "", line)
    line = line.replace("**", "")
    line = line.replace("__", "")
    line = line.replace("`", "")
    if "|" in line:
        parts = [_clean_table_cell(part) for part in line.split("|")]
        parts = [part for part in parts if part and not set(part) <= {"-", ":"}]
        line = "；".join(parts)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _is_ascii_chart_line(line: str) -> bool:
    if not line:
        return False
    chart_chars = set("┤┊╱━─╭╮╰╯│┌┐└┘├┬┴┼█▇▆▅▄▃▂▁")
    count = sum(1 for ch in line if ch in chart_chars)
    if count >= 2:
        return True
    if re.search(r"^\s*(?:\d+%?|\d+(?:\.\d+)?)\s*[┤┊]", line):
        return True
    return False
