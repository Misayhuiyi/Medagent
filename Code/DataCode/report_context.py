"""Longitudinal report context helpers.

Generated reports are archived here so a later selected visit can use earlier
reports as longitudinal context.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PRIOR_REPORT_DIR_NAME = "既往报告"
_INTERNAL_CACHE_DIR_NAME = "internal"

_DATE_PATTERNS = (
    re.compile(r"((?:19|20)\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?"),
    re.compile(r"((?:19|20)\d{2})(\d{2})(\d{2})"),
)


def report_file_stem(patient_name: str, patient_id: str, source_date: str) -> str:
    def _clean(value: str) -> str:
        return "".join(c for c in str(value).strip() if c not in r'<>:"/\|?*').strip()

    name = _clean(patient_name) or _clean(patient_id) or "未知患者"
    pid = _clean(patient_id) or name
    return f"{name}_{pid}_{_clean(source_date)}"


def extract_dates(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text or ""):
            date = _normalize_date(match.group(1), match.group(2), match.group(3))
            if date:
                found.append((match.start(), date))

    dates: list[str] = []
    seen: set[str] = set()
    for _, date in sorted(found, key=lambda item: item[0]):
        if date not in seen:
            dates.append(date)
            seen.add(date)
    return dates


def iter_prior_markdown_entries(patient_dir: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen_dates: set[str] = set()
    if not patient_dir.exists():
        return entries

    for md_file in sorted(patient_dir.rglob(f"{PRIOR_REPORT_DIR_NAME}/*.md")):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = md_file.relative_to(patient_dir)
        filename_dates = extract_dates(md_file.name)
        rel_dates = extract_dates(str(rel).replace("\\", "/"))
        date = filename_dates[-1] if filename_dates else ""
        if not date and rel_dates:
            date = rel_dates[-1]
        if not date:
            content_dates = extract_dates((content or "")[:4000])
            date = content_dates[0] if content_dates else ""
        if not date or date in seen_dates:
            continue
        seen_dates.add(date)
        entries.append({
            "date": date,
            "title": f"{date} AI门诊报告",
            "content": content,
            "kind": "markdown",
        })

    internal_dir = patient_dir / f"_{_INTERNAL_CACHE_DIR_NAME}"
    if internal_dir.exists():
        for md_file in sorted(internal_dir.glob("*.md")):
            date = md_file.stem
            if not _is_valid_date(date) or date in seen_dates:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            seen_dates.add(date)
            entries.append({
                "date": date,
                "title": f"{date} AI门诊报告（缓存）",
                "content": content,
                "kind": "markdown",
            })

    return sorted(entries, key=lambda item: (item.get("date", ""), item.get("title", "")))


def collect_prior_context_entries(patient_dir: Path, visit_date: str) -> list[dict[str, str]]:
    if not _is_valid_date(visit_date):
        return []
    return [
        entry for entry in iter_prior_markdown_entries(patient_dir)
        if _is_before(entry.get("date", ""), visit_date)
    ]


def format_prior_context(
    entries: list[dict[str, str]],
    total_budget: int = 30_000,
    per_entry_budget: int = 6_000,
) -> str:
    if not entries:
        return ""

    parts: list[str] = []
    used = 0
    for entry in entries:
        content = str(entry.get("content", "")).strip()
        if len(content) > per_entry_budget:
            content = content[:per_entry_budget] + f"\n（既往报告过长，已截断；原长 {len(content)} 字）"
        block = f"## {entry.get('title', '既往报告')}\n{content}"
        if used + len(block) > total_budget:
            remaining = len(entries) - len(parts)
            parts.append(f"另有 {remaining} 份既往报告因长度限制未展开。")
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def generated_report_bucket_date(patient_dir: Path, visit_date: str) -> str:
    return visit_date


def generated_report_markdown_path(
    patient_dir: Path,
    visit_date: str,
    patient_name: str = "",
    patient_id: str = "",
) -> Path | None:
    if not _is_valid_date(visit_date):
        return None
    stem = report_file_stem(patient_name, patient_id, visit_date)
    return patient_dir / generated_report_bucket_date(patient_dir, visit_date) / PRIOR_REPORT_DIR_NAME / f"{stem}.md"


def generated_report_json_path(
    patient_dir: Path,
    visit_date: str,
    patient_name: str = "",
    patient_id: str = "",
) -> Path | None:
    if not _is_valid_date(visit_date):
        return None
    stem = report_file_stem(patient_name, patient_id, visit_date)
    return patient_dir / generated_report_bucket_date(patient_dir, visit_date) / PRIOR_REPORT_DIR_NAME / f"{stem}.json"


def write_generated_report_markdown(
    patient_dir: Path,
    visit_date: str,
    markdown: str,
    patient_name: str = "",
    patient_id: str = "",
) -> Path | None:
    path = generated_report_markdown_path(patient_dir, visit_date, patient_name, patient_id)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")

    internal_dir = patient_dir / f"_{_INTERNAL_CACHE_DIR_NAME}"
    internal_dir.mkdir(parents=True, exist_ok=True)
    (internal_dir / f"{visit_date}.md").write_text(markdown, encoding="utf-8")
    return path


def write_generated_report_json(
    patient_dir: Path,
    visit_date: str,
    json_data: dict,
    patient_name: str = "",
    patient_id: str = "",
) -> Path | None:
    path = generated_report_json_path(patient_dir, visit_date, patient_name, patient_id)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def iter_prior_json_entries(patient_dir: Path) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    if not patient_dir.exists():
        return entries
    for json_file in sorted(patient_dir.rglob(f"{PRIOR_REPORT_DIR_NAME}/*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        source_date = str(data.get("source_date", ""))
        if not _is_valid_date(source_date) or source_date in seen:
            continue
        seen.add(source_date)
        entries.append(data)
    return sorted(entries, key=lambda item: item.get("source_date", ""))


def report_to_prior_json(
    report: dict,
    source_date: str,
    bucket_date: str,
    encounter_type: str = "selected",
) -> dict:
    overview = _dict(report.get("patient-overview"))
    history = _dict(report.get("patient-history"))
    treatment = _dict(report.get("treatment-plan"))
    efficacy = _dict(report.get("efficacy-prediction"))
    suggestions = _dict(report.get("suggestions"))

    tumor = _dict(_pick(overview, "ai_tumor_burden", "AI 肿瘤负荷评估"))
    diagnosis = _pick_text(overview, "diagnosis", "AI 诊断")
    efficacy_text = _pick_text(overview, "ai_efficacy", "AI 抗肿瘤疗效评估")
    adverse_text = _pick_text(overview, "ai_adverse_events", "AI 不良反应评估")

    return {
        "source_date": source_date,
        "bucket_date": bucket_date,
        "encounter_type": encounter_type,
        "summary": _first_text(
            tumor.get("conclusion"),
            diagnosis,
            _pick_text(history, "present_illness", "现病史"),
        ),
        "tumor_burden": {
            "measurements": _pick(tumor, "lesions", "measurements") or [],
            "clinical_stage": _first_text(tumor.get("clinical_stage"), tumor.get("stage"), diagnosis),
            "trend": _first_text(tumor.get("trend"), tumor.get("变化"), efficacy_text),
            "key_evidence": [_first_text(tumor.get("conclusion"), _to_text(tumor))],
        },
        "treatment_and_response": {
            "treatments": _pick(treatment, "treatment_plans", "AI 治疗方案") or [],
            "response": _first_text(efficacy_text, _to_text(efficacy)),
            "key_evidence": [_first_text(_pick_text(treatment, "adverse_reaction_plan"), "")],
        },
        "adverse_reactions": [_first_text(adverse_text, _to_text(suggestions))],
        "diagnosis_stage": diagnosis,
        "open_questions": [],
        "next_focus": [],
    }


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _pick(data: dict, *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _pick_text(data: dict, *keys: str) -> str:
    return _to_text(_pick(data, *keys))


def _first_text(*values: Any) -> str:
    for value in values:
        text = _to_text(value).strip()
        if text:
            return text
    return ""


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "；".join(part for part in (_to_text(item) for item in value) if part)
    if isinstance(value, dict):
        if isinstance(value.get("summary"), str):
            return value["summary"].strip()
        if isinstance(value.get("conclusion"), str):
            return value["conclusion"].strip()
        parts = []
        for key, val in value.items():
            if str(key).startswith("_"):
                continue
            text = _to_text(val)
            if text:
                parts.append(f"{key}: {text}")
        return "；".join(parts)
    return str(value)


def _normalize_date(year: str, month: str, day: str) -> str:
    try:
        y, m, d = int(year), int(month), int(day)
        if not (2020 <= y <= 2035):
            return ""
        datetime(y, m, d)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (TypeError, ValueError):
        return ""


def _is_valid_date(value: str) -> bool:
    if not value or len(value) != 10:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _is_before(left: str, right: str) -> bool:
    return _is_valid_date(left) and _is_valid_date(right) and left < right
