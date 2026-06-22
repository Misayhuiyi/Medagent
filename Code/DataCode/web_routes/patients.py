"""患者 CRUD 路由：列表、文件列表、文件内容读取、上传。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, UploadFile, File

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/patients", tags=["patients"])


def _get_patients_dir() -> Path:
    """从 app state 获取 patients 目录。"""
    from DataCode.web_server import _app_state
    return Path(_app_state["patients_dir"])


def _sanitize_path_segment(segment: str) -> str:
    """消毒路径参数，拒绝 .. 和绝对路径。"""
    segment = unquote(segment)
    if ".." in segment or "/" in segment or "\\" in segment:
        raise HTTPException(status_code=400, detail="Invalid path segment")
    return segment


@router.get("")
async def list_patients():
    """扫描 TempData/patients/，返回患者列表。"""
    patients_dir = _get_patients_dir()
    if not patients_dir.exists():
        return []
    patients = []
    for d in sorted(patients_dir.iterdir()):
        if not d.is_dir():
            continue
        parts = d.name.rsplit("-", 1)
        name = parts[0] if len(parts) == 2 else d.name
        # 单次 rglob：收集非 ocr/ 下的 PDF，同时计数和提取日期
        pdfs = [
            f for f in d.rglob("*.pdf")
            if not any(p == "ocr" for p in f.relative_to(d).parts)
        ]
        pdf_count = len(pdfs)
        import re
        date_pattern = re.compile(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})')
        # 收集每个OCR文件的最早日期, 按日期排序后分组为就诊记录
        file_dates: list[str] = []
        for md_file in sorted(d.rglob("ocr/*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")[:2000]
                earliest = None
                for m in date_pattern.finditer(content):
                    y, mo, dy = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
                    y_int = int(y)
                    if 2020 <= y_int <= 2030:
                        d_str = f"{y}-{mo}-{dy}"
                        if earliest is None or d_str < earliest:
                            earliest = d_str
                if earliest:
                    file_dates.append(earliest)
            except Exception:
                continue

        # 按日期分组: 间隔>45天视为不同次就诊
        encounters: list[dict] = []
        if file_dates:
            file_dates.sort()
            cur_enc = {"admission": file_dates[0], "discharge": file_dates[0]}
            for date_str in file_dates[1:]:
                prev = datetime.strptime(cur_enc["discharge"], "%Y-%m-%d")
                cur = datetime.strptime(date_str, "%Y-%m-%d")
                if (cur - prev).days <= 45:
                    cur_enc["discharge"] = date_str
                else:
                    encounters.append(cur_enc)
                    cur_enc = {"admission": date_str, "discharge": date_str}
            encounters.append(cur_enc)
            for enc in encounters:
                if enc["admission"] == enc["discharge"]:
                    enc["discharge"] = ""

        date = encounters[0]["admission"] if encounters else ""
        discharge_date = encounters[-1]["discharge"] if encounters and len(encounters) == 1 else ""

        patients.append({
            "id": d.name,
            "name": name,
            "date": date,
            "discharge_date": discharge_date,
            "encounters": encounters,
            "file_count": pdf_count,
        })
    return patients


@router.get("/{patient_id}/files")
async def get_patient_files(patient_id: str):
    """递归返回该患者的文件列表（排除 ocr/ 目录）。"""
    _sanitize_path_segment(patient_id)
    patient_dir = _get_patients_dir() / patient_id
    if not patient_dir.exists() or not patient_dir.is_dir():
        raise HTTPException(status_code=404, detail="Patient not found")
    files = []
    for f in sorted(patient_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(patient_dir)
        # 排除 ocr/ 目录下的所有内容
        if any(part == "ocr" for part in rel.parts):
            continue
        # 只展示 PDF
        if f.suffix.lower() != ".pdf":
            continue
        # 检查是否有对应 OCR md
        stem = f.stem
        ocr_md = f.parent / stem / "ocr" / f"{stem}.md"
        stat = f.stat()
        files.append({
            "name": str(rel).replace("\\", "/"),
            "size": stat.st_size,
            "type": "pdf",
            "modified_time": stat.st_mtime,
            "has_ocr": ocr_md.exists(),
        })
    return files


@router.get("/{patient_id}/files/{filename:path}")
async def read_patient_file(patient_id: str, filename: str):
    """读取患者文件内容。PDF 自动转发到 OCR Markdown。"""
    patient_id = _sanitize_path_segment(patient_id)
    filename = unquote(filename)
    if ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = _get_patients_dir() / patient_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    # 确保解析后的路径仍在患者目录内
    try:
        file_path.resolve().relative_to(_get_patients_dir().resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Path traversal denied")

    # PDF → 自动查找 OCR Markdown
    if file_path.suffix.lower() == ".pdf":
        stem = file_path.stem
        ocr_md = file_path.parent / stem / "ocr" / f"{stem}.md"
        if not ocr_md.exists():
            raise HTTPException(status_code=404, detail="OCR content not available for this file")
        content = ocr_md.read_text(encoding="utf-8")
        return {"name": filename, "content": content, "source": "ocr"}

    # 非 PDF 文件直接读取
    content = file_path.read_text(encoding="utf-8", errors="replace")
    return {"name": filename, "content": content}


@router.post("")
async def upload_patient(folder: UploadFile = File(...)):
    """上传患者文件夹（Demo 简化为单文件上传）。"""
    raise HTTPException(status_code=501, detail="Use direct file copy for demo")


@router.post("/upload")
async def upload_patient_files(
    patient_id: str = "",
    files: list[UploadFile] = File(...),
):
    """Upload patient files. Creates patient folder structure."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    patients_dir = _get_patients_dir()

    # Determine patient_id from first file's webkitRelativePath or use provided
    first_name = files[0].filename or ""
    if not patient_id:
        # Try to extract from path like "patient-001/category/file.pdf"
        parts = first_name.replace("\\", "/").split("/")
        patient_id = parts[0] if len(parts) > 1 else f"upload-{int(datetime.now().timestamp())}"

    patient_id = _sanitize_path_segment(patient_id)
    patient_dir = patients_dir / patient_id
    patient_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        fname = (f.filename or "").replace("\\", "/")
        # Strip the patient_id prefix if present
        parts = fname.split("/")
        if parts[0] == patient_id and len(parts) > 1:
            rel_path = "/".join(parts[1:])
        else:
            rel_path = fname

        target = patient_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        content = await f.read()
        target.write_bytes(content)
        saved.append(rel_path)

    return {"patient_id": patient_id, "files_saved": len(saved), "files": saved}
