"""Longitudinal report context helpers.

Generated reports are archived here so a later selected visit can use earlier
reports as longitudinal context.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PRIOR_REPORT_DIR_NAME = "既往报告"
_INTERNAL_CACHE_DIR_NAME = "internal"

_DATE_PATTERNS = (
    re.compile(r"((?:19|20)\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?"),
    re.compile(r"((?:19|20)\d{2})(\d{2})(\d{2})"),
    re.compile(r"(?<!\d)([2-3]\d)(\d{2})(\d{2})(?!\d)"),
)
_DISCHARGE_KEYWORDS = ("出院", "出院小结", "出院记录", "出院诊断")
_ADMISSION_KEYWORDS = ("入院记录", "入出院记录")
_OUTPATIENT_KEYWORDS = ("门诊记录", "急诊记录")
_FAILED_REPORT_MARKERS = (
    "本页签未能成功生成结构化报告",
    "LLM 调用失败",
    "LLM 网络连接失败",
)


@dataclass(frozen=True)
class PatientDocument:
    name: str
    content: str
    date: str
    category: str
    path: Path
    is_prior_bucket: bool
    is_discharge: bool


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


def detect_patient_timepoints(patient_dir: Path) -> list[dict[str, Any]]:
    """Detect all mentioned/document dates without merging by arbitrary windows."""
    counts: dict[str, int] = {}
    mention_counts: dict[str, int] = {}
    prior_counts: dict[str, int] = {}
    discharge_dates: set[str] = set()
    for doc in iter_patient_ocr_documents(patient_dir):
        mentioned_dates = _content_dates(doc.content)
        if doc.date:
            counts[doc.date] = counts.get(doc.date, 0) + 1
            if doc.is_prior_bucket:
                prior_counts[doc.date] = prior_counts.get(doc.date, 0) + 1
            if doc.is_discharge:
                discharge_dates.add(doc.date)
        for mentioned_date in mentioned_dates:
            mention_counts[mentioned_date] = mention_counts.get(mentioned_date, 0) + 1

    for entry in iter_prior_markdown_entries(patient_dir):
        date = str(entry.get("date", ""))
        if not date:
            continue
        counts.setdefault(date, 0)
        prior_counts[date] = prior_counts.get(date, 0) + 1

    all_dates = sorted(set(counts) | set(mention_counts))
    return [
        {
            "admission": date,
            "discharge": "",
            "type": "timepoint",
            "label": _timepoint_label(
                date,
                counts.get(date, 0),
                mention_counts.get(date, 0),
                date in discharge_dates,
            ),
            "file_count": counts.get(date, 0),
            "mention_count": mention_counts.get(date, 0),
            "prior_report_count": prior_counts.get(date, 0),
        }
        for date in all_dates
    ]


def detect_patient_encounters(patient_dir: Path) -> list[dict[str, Any]]:
    """Detect reportable outpatient/admission/discharge nodes.

    Priority mirrors old_MedAgent:
    - outpatient records use visit/document date;
    - admission records use labeled 入院时间/入院日期 first;
    - discharge date is attached to the admission stage for sorting and archive buckets.
    """
    encounters: dict[str, dict[str, Any]] = {}
    docs = [doc for doc in iter_patient_ocr_documents(patient_dir) if not doc.is_prior_bucket]

    for doc in docs:
        encounter_type = _document_encounter_type(doc)
        if not encounter_type:
            continue
        encounter_date = _document_encounter_date(doc)
        if not encounter_date:
            continue
        item = encounters.setdefault(encounter_date, {
            "admission": encounter_date,
            "discharge": "",
            "type": encounter_type,
            "file_count": 0,
            "prior_report_count": 0,
        })
        if encounter_type == "admission":
            item["type"] = "admission"
            discharge = _labeled_date(doc.content, ("出院时间", "出院日期"))
            if discharge:
                item["discharge"] = max(str(item.get("discharge", "")), discharge)

    if not encounters:
        return _fallback_encounters_from_document_dates(docs)

    result: list[dict[str, Any]] = []
    for date, item in encounters.items():
        admission = str(item["admission"])
        discharge = str(item.get("discharge", "") or "")
        item["file_count"] = sum(1 for doc in docs if _belongs_to_encounter(doc, admission, discharge))
        item["prior_report_count"] = _prior_markdown_count(patient_dir, date)
        item["label"] = f"入院时间 {admission}" if item.get("type") == "admission" else f"门诊时间 {admission}"
        result.append(item)

        if item.get("type") == "admission" and discharge and discharge != admission and discharge not in encounters:
            result.append({
                "admission": discharge,
                "discharge": "",
                "type": "discharge",
                "source_admission": admission,
                "file_count": sum(1 for doc in docs if doc.date == discharge),
                "prior_report_count": _prior_markdown_count(patient_dir, discharge),
                "label": f"出院时间 {discharge}",
            })

    return sorted(result, key=lambda item: (item.get("admission", ""), item.get("type", "")))


def iter_patient_ocr_documents(patient_dir: Path) -> list[PatientDocument]:
    if not patient_dir.exists():
        return []

    docs: list[PatientDocument] = []
    for md_file in sorted(patient_dir.rglob("*/ocr/*.md")):
        if md_file.parent.parent.name != md_file.stem:
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _is_failed_prior_report_content(content):
            continue
        rel = md_file.relative_to(patient_dir)
        stem_dir = md_file.parent.parent
        category = stem_dir.parent.name
        display_name = _source_display_name(patient_dir, md_file)
        path_text = str(rel).replace("\\", "/")
        is_prior_bucket = PRIOR_REPORT_DIR_NAME in rel.parts
        is_discharge = any(keyword in path_text for keyword in _DISCHARGE_KEYWORDS)
        date = _detect_document_date(rel, content)
        if is_discharge:
            date = _labeled_date(content, ("出院时间", "出院日期")) or date
        docs.append(PatientDocument(
            name=display_name,
            content=content,
            date=date,
            category=category,
            path=rel,
            is_prior_bucket=is_prior_bucket,
            is_discharge=is_discharge,
        ))
    return docs


def load_timepoint_patient_files(patient_dir: Path, visit_date: str = "") -> list[dict[str, str]]:
    """Load original OCR files that belong to the selected timepoint only."""
    docs = [doc for doc in iter_patient_ocr_documents(patient_dir) if not doc.is_prior_bucket]
    selected = docs
    if visit_date:
        encounter = next((item for item in detect_patient_encounters(patient_dir) if item.get("admission") == visit_date), None)
        if encounter:
            source_date = str(encounter.get("source_admission") or visit_date)
            selected = [
                doc for doc in docs
                if _belongs_to_encounter(doc, source_date, str(encounter.get("discharge", "")))
                or (encounter.get("type") == "discharge" and doc.date == visit_date)
            ]
        else:
            selected = [doc for doc in docs if doc.date == visit_date]

    fallback_by_mention = False
    if visit_date and not selected:
        mentioned = [doc for doc in docs if visit_date in _content_dates(doc.content)]
        if mentioned:
            earliest = min((doc.date or "9999-99-99") for doc in mentioned)
            selected = [doc for doc in mentioned if (doc.date or "9999-99-99") == earliest]
            fallback_by_mention = True

    files: list[dict[str, str]] = []
    for doc in selected:
        if fallback_by_mention:
            name = f"[提及 {visit_date}；文件日期 {doc.date or '未识别日期'}] {doc.name}"
        else:
            name = f"[{doc.date or '未识别日期'}] {doc.name}"
        files.append({"name": name, "content": doc.content})
    return files


def load_cumulative_patient_files(patient_dir: Path, visit_date: str = "") -> list[dict[str, str]]:
    """Load original OCR evidence up to the selected stage.

    Generated reports are intentionally supplied by collect_prior_context_entries()
    so the model can distinguish raw evidence from previous structured reports.
    """
    docs = [doc for doc in iter_patient_ocr_documents(patient_dir) if not doc.is_prior_bucket]
    if not visit_date:
        selected = docs
        discharge = ""
        cutoff = ""
        source_date = ""
    else:
        encounter = next((item for item in detect_patient_encounters(patient_dir) if item.get("admission") == visit_date), None)
        source_date = str((encounter or {}).get("source_admission") or visit_date)
        discharge = str((encounter or {}).get("discharge", "") or "")
        cutoff = discharge or generated_report_bucket_date(patient_dir, source_date) or visit_date
        if encounter and encounter.get("type") == "discharge":
            cutoff = visit_date
        selected = [doc for doc in docs if not doc.date or doc.date <= cutoff]
        if not selected:
            return load_timepoint_patient_files(patient_dir, visit_date)

    files: list[dict[str, str]] = []
    for doc in sorted(selected, key=lambda item: (item.date or "9999-99-99", item.path.as_posix())):
        if visit_date and _belongs_to_encounter(doc, source_date or visit_date, discharge):
            prefix = "当前阶段资料"
        elif visit_date and doc.date and doc.date < (source_date or visit_date):
            prefix = "既往原始资料"
        elif visit_date and doc.date and cutoff and (source_date or visit_date) < doc.date <= cutoff:
            prefix = "当前阶段出院/阶段总结资料"
        else:
            prefix = "原始资料"
        files.append({
            "name": f"[{prefix}；文件日期 {doc.date or '未识别日期'}] {doc.name}",
            "content": doc.content,
        })
    return files


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
            if _is_failed_prior_report_content(content):
                continue
            seen_dates.add(date)
            entries.append({
                "date": date,
                "title": f"{date} AI门诊报告（缓存）",
                "content": content,
                "kind": "markdown",
            })

    return sorted(entries, key=lambda item: (item.get("date", ""), item.get("title", "")))


def _document_encounter_type(doc: PatientDocument) -> str:
    text = f"{doc.path.as_posix()}\n{doc.content[:800]}"
    if any(keyword in text for keyword in _ADMISSION_KEYWORDS) or "入院时间" in text or "入院日期" in text:
        return "admission"
    if any(keyword in text for keyword in _OUTPATIENT_KEYWORDS):
        return "outpatient"
    return ""


def _document_encounter_date(doc: PatientDocument) -> str:
    encounter_type = _document_encounter_type(doc)
    if encounter_type == "admission":
        return _labeled_date(doc.content, ("入院时间", "入院日期")) or doc.date
    if encounter_type == "outpatient":
        content_dates = _content_dates(doc.content)
        return doc.date or (content_dates[0] if content_dates else "")
    return ""


def _belongs_to_encounter(doc: PatientDocument, admission: str, discharge: str = "") -> bool:
    if not admission:
        return False
    if _document_encounter_date(doc) == admission:
        return True
    if doc.date == admission:
        return True
    if discharge and doc.date and admission < doc.date <= discharge:
        return True
    return False


def _labeled_date(content: str, labels: tuple[str, ...]) -> str:
    text = content or ""
    for label in labels:
        index = text.find(label)
        if index < 0:
            continue
        dates = extract_dates(text[index:index + 120])
        if dates:
            return dates[0]
    return ""


def _prior_markdown_count(patient_dir: Path, visit_date: str) -> int:
    return sum(1 for entry in iter_prior_markdown_entries(patient_dir) if entry.get("date") == visit_date)


def _fallback_encounters_from_document_dates(docs: list[PatientDocument]) -> list[dict[str, Any]]:
    dates = sorted({doc.date for doc in docs if doc.date})
    return [
        {
            "admission": date,
            "discharge": "",
            "type": "outpatient",
            "label": f"门诊时间 {date}",
            "file_count": sum(1 for doc in docs if doc.date == date),
            "prior_report_count": 0,
        }
        for date in dates
    ]


def collect_prior_context_entries(patient_dir: Path, visit_date: str) -> list[dict[str, str]]:
    if not _is_valid_date(visit_date):
        return []
    entries: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for entry in iter_prior_markdown_entries(patient_dir):
        if _is_before(entry.get("date", ""), visit_date):
            entries.append(entry)
            seen_titles.add(entry["title"])

    for doc in iter_patient_ocr_documents(patient_dir):
        if not doc.is_discharge or doc.is_prior_bucket:
            continue
        if not _is_before(doc.date, visit_date):
            continue
        title = f"{doc.date} 出院文件/{doc.name}"
        if title in seen_titles:
            continue
        entries.append({"date": doc.date, "title": title, "content": doc.content, "kind": "discharge"})
        seen_titles.add(title)

    return sorted(entries, key=lambda item: (item.get("date", ""), item.get("title", "")))


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
    for encounter in detect_patient_encounters(patient_dir):
        if encounter.get("type") == "admission" and encounter.get("admission") == visit_date:
            discharge = str(encounter.get("discharge", "") or "")
            if discharge and discharge != visit_date:
                return discharge
            break
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
        if _is_failed_prior_report_json(data):
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


_report_to_prior_json = report_to_prior_json


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _is_failed_prior_report_content(content: str) -> bool:
    text = content or ""
    return bool(text) and any(marker in text for marker in _FAILED_REPORT_MARKERS)


def _is_failed_prior_report_json(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    text = json.dumps(data, ensure_ascii=False)
    if any(marker in text for marker in _FAILED_REPORT_MARKERS):
        return True
    summary = _to_text(data.get("summary")).strip()
    tumor = _dict(data.get("tumor_burden"))
    treatment = _dict(data.get("treatment_and_response"))
    has_measurements = bool(tumor.get("measurements"))
    has_treatments = bool(treatment.get("treatments"))
    has_stage = bool(_to_text(tumor.get("clinical_stage")).strip() or _to_text(data.get("diagnosis_stage")).strip())
    return not summary and not has_measurements and not has_treatments and not has_stage


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


def _detect_document_date(rel: Path, content: str) -> str:
    path_dates = extract_dates(str(rel).replace("\\", "/"))
    if path_dates:
        return path_dates[0]
    content_dates = extract_dates((content or "")[:4000])
    return content_dates[0] if content_dates else ""


def _content_dates(content: str) -> list[str]:
    return extract_dates((content or "")[:4000])


def _source_display_name(patient_dir: Path, md_file: Path) -> str:
    stem_dir = md_file.parent.parent
    stem = md_file.stem
    source_pdf = stem_dir / f"{stem}.pdf"
    if source_pdf.exists():
        return str(source_pdf.relative_to(patient_dir)).replace("\\", "/")
    return str(md_file.relative_to(patient_dir)).replace("\\", "/")


def _normalize_date(year: str, month: str, day: str) -> str:
    try:
        y, m, d = int(year), int(month), int(day)
        if y < 100:
            y += 2000
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


def _timepoint_label(date: str, file_count: int, mention_count: int, is_discharge: bool) -> str:
    if file_count:
        suffix = "出院时间点" if is_discharge else "资料时间点"
        return f"{suffix} {date}（{file_count}份资料）"
    return f"提及时间点 {date}（{mention_count}份资料提及）"
