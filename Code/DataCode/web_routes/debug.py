"""调试路由：LLM 状态、最近调用、连通性自检、日志 tail。

GET /api/debug/llm           — 当前候选 LLM、被禁用的供应商、最近 N 条调用记录
GET /api/debug/llm/health    — 对每个候选执行一次 ping，返回是否可用
GET /api/debug/logs?lines=N  — 读取 backend.log 末尾 N 行
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, Query

from DataCode.llm_callback import LLMCallTracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/debug", tags=["debug"])


def _get_state(key: str):
    from DataCode.web_server import _app_state
    return _app_state.get(key)


@router.get("/llm")
async def llm_status(limit: int = Query(default=30, ge=1, le=200)):
    executor = _get_state("skill_executor")
    status = executor.llm_status() if executor else {"candidates": [], "disabled": []}
    return {
        "status": status,
        "recent_calls": LLMCallTracker.instance().recent(limit),
    }


@router.get("/llm/health")
async def llm_health():
    """对当前候选 LLM 做一次小流量 ping。"""
    executor = _get_state("skill_executor")
    if executor is None:
        return {"ok": False, "reason": "skill_executor not initialized", "results": []}

    candidates = executor._llm_candidates  # noqa: SLF001 — 调试接口允许
    results = []
    for cand in candidates or []:
        results.append(await _ping_candidate(cand))

    return {
        "ok": any(r["ok"] for r in results),
        "results": results,
        "candidates": executor.llm_status()["candidates"],
    }


async def _ping_candidate(candidate: dict) -> dict:
    import asyncio
    import json as _json
    import urllib.request
    import urllib.error

    name = candidate.get("name", "")
    base_url = (candidate.get("base_url") or "").rstrip("/")
    model = candidate.get("model", "")
    api_key = candidate.get("api_key", "")
    if not (base_url and model and api_key):
        return {"name": name, "ok": False, "error": "missing base_url/model/api_key"}

    body = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "stream": False,
    }).encode("utf-8")

    started = time.time()

    def _send():
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "curl/8.17.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                return {"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")[:600]}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "body": e.read().decode("utf-8", errors="replace")[:600]}
        except Exception as e:
            return {"status": 0, "error": f"{type(e).__name__}: {e}"[:300]}

    try:
        result = await asyncio.to_thread(_send)
    except Exception as e:
        result = {"status": 0, "error": f"{type(e).__name__}: {e}"[:300]}

    latency = round(time.time() - started, 3)
    status_code = int(result.get("status", 0))
    return {
        "name": name,
        "model": model,
        "base_url": base_url,
        "api_key_tail": "****" + api_key[-4:],
        "ok": status_code == 200,
        "status": status_code,
        "latency_s": latency,
        "snippet": result.get("body", result.get("error", "")),
    }


@router.get("/logs")
async def tail_logs(lines: int = Query(default=200, ge=1, le=2000), name: str = "backend"):
    project_root = _get_state("project_root") or "."
    log_path = Path(project_root) / "Result" / "logs" / f"{name}.log"
    if not log_path.exists():
        return {"path": str(log_path), "lines": []}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    tail = text.splitlines()[-lines:]
    return {"path": str(log_path), "lines": tail}


@router.get("/llm/recent")
async def recent_calls(limit: int = Query(default=30, ge=1, le=200)):
    return {"calls": LLMCallTracker.instance().recent(limit)}


@router.get("/pipeline/{patient_id}")
async def pipeline_history(patient_id: str, limit: int = Query(default=10, ge=1, le=50)):
    """返回该患者的最近 pipeline 运行摘要。"""
    import json as _json
    from glob import glob
    project_root = _get_state("project_root") or "."
    pattern = str(Path(project_root) / "Result" / "logs" / f"pipeline_{patient_id}_*.json")
    files = sorted(glob(pattern), reverse=True)[:limit]
    results = []
    for f in files:
        try:
            results.append(_json.loads(Path(f).read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"patient_id": patient_id, "runs": results}


@router.get("/pipeline")
async def all_pipeline_runs(limit: int = Query(default=20, ge=1, le=100)):
    """返回所有患者的最新 pipeline 运行摘要（按时间倒序）。"""
    import json as _json
    from glob import glob
    project_root = _get_state("project_root") or "."
    pattern = str(Path(project_root) / "Result" / "logs" / "pipeline_*.json")
    files = sorted(glob(pattern), reverse=True)[:limit]
    results = []
    for f in files:
        try:
            results.append(_json.loads(Path(f).read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"runs": results}
