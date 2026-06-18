"""统一的后端日志配置。

输出:
  - 控制台 (INFO 级别，简洁格式)
  - Result/logs/backend.log     (DEBUG 级别，全量后端日志)
  - Result/logs/llm.log         (DEBUG 级别，LLM 调用专用)

仅在进程启动时调用一次 setup_logging(project_root)。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_LLM_LOGGER_NAME = "medagent.llm"

_initialized = False


def setup_logging(project_root: str) -> None:
    """配置 root logger 和 llm logger。多次调用幂等。"""
    global _initialized
    if _initialized:
        return

    log_dir = Path(project_root) / "Result" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT)

    # ── 控制台 handler ──
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    # ── 后端全量日志 ──
    backend_handler = logging.handlers.RotatingFileHandler(
        log_dir / "backend.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    backend_handler.setLevel(logging.DEBUG)
    backend_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # 避免重复添加 handler（reload 模式下可能多次执行）
    for handler in list(root.handlers):
        if isinstance(handler, (logging.StreamHandler, logging.handlers.RotatingFileHandler)):
            root.removeHandler(handler)
    root.addHandler(console)
    root.addHandler(backend_handler)

    # ── LLM 专用 logger ──
    llm_logger = logging.getLogger(_LLM_LOGGER_NAME)
    llm_logger.setLevel(logging.DEBUG)
    llm_logger.propagate = True  # 同时进入 backend.log

    llm_handler = logging.handlers.RotatingFileHandler(
        log_dir / "llm.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    llm_handler.setLevel(logging.DEBUG)
    llm_handler.setFormatter(formatter)
    for handler in list(llm_logger.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            llm_logger.removeHandler(handler)
    llm_logger.addHandler(llm_handler)

    # ── 静音第三方过于啰嗦的 logger ──
    for noisy in ("httpx", "httpcore", "openai", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _initialized = True
    logging.getLogger(__name__).info("Logging initialized at %s", log_dir)


def get_llm_logger() -> logging.Logger:
    return logging.getLogger(_LLM_LOGGER_NAME)
