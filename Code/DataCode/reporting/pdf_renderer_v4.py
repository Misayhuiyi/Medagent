"""Render V4 HTML reports to PDF using a local browser when available."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from DataCode.reporting.normalizer import normalize_report
from DataCode.reporting.template_v4 import render_v4_html

logger = logging.getLogger(__name__)


def report_to_v4_html(report: dict, title: str, patient_info: dict | None = None) -> str:
    model = normalize_report(report, title, patient_info)
    return render_v4_html(model)


def report_to_v4_pdf_bytes(report: dict, title: str, patient_info: dict | None = None) -> bytes:
    html = report_to_v4_html(report, title, patient_info)

    # 优先 Playwright Chromium（与 old_MedAgent 方案一致，高保真 HTML/CSS PDF）
    playwright_pdf = _html_to_pdf_with_playwright(html)
    if playwright_pdf is not None:
        return playwright_pdf

    # 回退 Edge/Chrome 无头打印
    browser = _find_browser()
    if browser:
        return _html_to_pdf_with_browser(html, browser)

    # 最后尝试 wkhtmltopdf
    wkhtmltopdf = _find_wkhtmltopdf()
    if wkhtmltopdf:
        return _html_to_pdf_with_wkhtmltopdf(html, wkhtmltopdf)

    raise RuntimeError("PDF 生成失败：未找到 Playwright/Edge/Chrome/wkhtmltopdf")


def _html_to_pdf_with_playwright(html: str) -> bytes | None:
    """使用 Playwright Chromium 生成高保真 PDF（与 old_MedAgent 方案一致）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("Playwright not installed, falling back to browser headless")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(html, timeout=30000)
            # 等待字体和图表渲染
            page.wait_for_timeout(500)
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
            )
            browser.close()
            if not pdf_bytes.startswith(b"%PDF-"):
                logger.warning("Playwright output is not valid PDF, falling back")
                return None
            logger.info("Rendering V4 PDF via Playwright Chromium: %d bytes", len(pdf_bytes))
            return pdf_bytes
    except Exception as e:
        logger.warning("Playwright PDF failed (%s), falling back to browser headless", e)
        return None


def _find_browser() -> str | None:
    configured = os.environ.get("MEDAGENT_CHROMIUM_PATH") or os.environ.get("CHROME_PATH")
    if configured and Path(configured).exists():
        return configured
    candidates = [
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Microsoft\Edge\Application\msedge.exe"),
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    # 从系统 PATH 查找浏览器
    for name in ("msedge", "msedge.exe", "chrome", "chrome.exe", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _find_wkhtmltopdf() -> str | None:
    configured = os.environ.get("MEDAGENT_WKHTMLTOPDF_PATH")
    if configured and Path(configured).exists():
        return configured
    # 从系统 PATH 查找
    for name in ("wkhtmltopdf", "wkhtmltopdf.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _html_to_pdf_with_browser(html: str, browser_path: str) -> bytes:
    tmp = _make_pdf_tmp_dir()
    try:
        tmp_path = Path(tmp)
        html_path = tmp_path / "report.html"
        pdf_path = tmp_path / "report.pdf"
        profile_dir = tmp_path / "profile"
        html_path.write_text(html, encoding="utf-8")

        args = [
            browser_path,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-breakpad",
            "--disable-crash-reporter",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-features=OptimizationHints,Translate,MediaRouter,CalculateNativeWinOcclusion,Crashpad",
            "--disable-crashpad-for-testing",
            "--disable-sync",
            "--disable-logging",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            f"--print-to-pdf={pdf_path}",
            "--print-to-pdf-no-header",
            html_path.as_uri(),
        ]
        logger.info("Rendering V4 PDF via browser: %s", browser_path)
        completed = subprocess.run(
            args,
            cwd=str(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "浏览器 PDF 渲染失败："
                f"exit={completed.returncode}; stderr={completed.stderr[-1000:]}"
            )
        if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
            raise RuntimeError("浏览器 PDF 渲染未生成有效文件")
        return pdf_path.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _html_to_pdf_with_wkhtmltopdf(html: str, executable: str) -> bytes:
    tmp = _make_pdf_tmp_dir()
    try:
        tmp_path = Path(tmp)
        html_path = tmp_path / "report.html"
        pdf_path = tmp_path / "report.pdf"
        html_path.write_text(html, encoding="utf-8")

        args = [
            executable,
            "--encoding",
            "utf-8",
            "--page-size",
            "A4",
            "--margin-top",
            "18mm",
            "--margin-right",
            "16mm",
            "--margin-bottom",
            "18mm",
            "--margin-left",
            "16mm",
            str(html_path),
            str(pdf_path),
        ]
        logger.info("Rendering V4 PDF via wkhtmltopdf: %s", executable)
        completed = subprocess.run(
            args,
            cwd=str(tmp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "wkhtmltopdf 渲染失败："
                f"exit={completed.returncode}; stderr={completed.stderr[-1000:]}"
            )
        if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
            raise RuntimeError("wkhtmltopdf 未生成有效 PDF")
        return pdf_path.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _pdf_tmp_parent() -> Path:
    configured = os.environ.get("MEDAGENT_PDF_TMP_DIR", "")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        Path.cwd() / "Result" / "tmp" / "pdf",
        Path(tempfile.gettempdir()) / "medagent_pdf",
    ])
    for parent in candidates:
        try:
            parent.mkdir(parents=True, exist_ok=True)
            probe = parent / f".write_test_{os.getpid()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return parent
        except OSError as exc:
            logger.warning("PDF temp dir unavailable, trying fallback: %s (%s)", parent, exc)
            continue
    raise RuntimeError("无法创建可写 PDF 临时目录")


def _make_pdf_tmp_dir() -> str:
    parent = _pdf_tmp_parent()
    for index in range(20):
        name = f"medagent_pdf_{os.getpid()}_{int(time.time() * 1000)}_{index}"
        path = parent / name
        try:
            path.mkdir(parents=True, exist_ok=False)
            return str(path)
        except FileExistsError:
            continue
    raise RuntimeError("无法创建 PDF 临时目录")
