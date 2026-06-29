"""main.py 与 web_server.py 的共享工具函数。

避免重复实现 _load_env 和 _build_llm_candidates。
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_env(project_root: str | Path) -> None:
    """加载 .env 环境变量。多次调用幂等。"""
    env_path = Path(project_root) / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        lower_value = value.lower()
        if not key or not value or "xxx" in lower_value or "your-api-key" in lower_value:
            continue
        os.environ.setdefault(key, value)


def build_llm_candidates(config) -> list[dict]:
    """构建 LLM 候选列表（从 .env + platform.yaml）。"""
    def valid_env(name: str) -> str:
        value = os.environ.get(name, "").strip()
        lower_value = value.lower()
        if not value or "xxx" in lower_value or "your-api-key" in lower_value:
            return ""
        return value

    llm = config._platform.setdefault("llm", {})
    platform_base_url = str(llm.get("base_url", "") or "").strip()
    platform_model = str(llm.get("default_model", "") or "").strip()
    candidates: list[dict] = []

    def add_candidate(name: str, api_key: str, base_url: str, model: str) -> None:
        if not api_key or not base_url or not model:
            return
        # 避免重复注册同一候选
        signature = (name, base_url, model)
        if any((c["name"], c["base_url"], c["model"]) == signature for c in candidates):
            return
        candidates.append({"name": name, "api_key": api_key, "base_url": base_url, "model": model})

    def add_provider(provider: str, api_key: str, public_host: str,
                     public_base_url: str, public_model: str) -> None:
        """为某供应商的 key 生成候选。

        关键约束：一个 key 只应指向它真正归属的 endpoint。
        - 若平台 base_url 已配置且不是该供应商的公网域名，则把该 key 作为
          “平台网关候选”(PLATFORM_*)，因为平台 base_url（如 opencode.ai 网关）
          可能就是这个 key 的真实归属地。
        - 仅当用户显式提供了该供应商的 *_BASE_URL（说明确实要直连公网 endpoint），
          或根本没有平台网关候选时，才追加公网 endpoint 候选。
        """
        explicit_base = valid_env(f"{provider}_BASE_URL")
        explicit_model = valid_env(f"{provider}_MODEL")
        platform_candidate_added = bool(platform_base_url and public_host not in platform_base_url)
        if platform_candidate_added:
            add_candidate(f"PLATFORM_{provider}_KEY", api_key, platform_base_url, platform_model)
        if explicit_base or not platform_candidate_added:
            add_candidate(provider, api_key,
                          explicit_base or public_base_url,
                          explicit_model or public_model)

    generic_key = valid_env("LLM_API_KEY")
    if generic_key:
        add_candidate("LLM_API_KEY", generic_key,
                      valid_env("LLM_BASE_URL") or platform_base_url,
                      valid_env("LLM_MODEL") or platform_model)
    openai_key = valid_env("OPENAI_API_KEY")
    if openai_key:
        add_provider("OPENAI", openai_key, "openai.com", "https://api.openai.com/v1", "gpt-4o-mini")
    dashscope_key = valid_env("DASHSCOPE_API_KEY")
    if dashscope_key:
        add_provider("DASHSCOPE", dashscope_key, "dashscope.aliyuncs.com",
                     "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus")
    deepseek_key = valid_env("DEEPSEEK_API_KEY")
    if deepseek_key:
        add_provider("DEEPSEEK", deepseek_key, "api.deepseek.com",
                     "https://api.deepseek.com/v1", "deepseek-v4-flash")

    preferred = valid_env("LLM_PROVIDER").upper()
    if preferred:
        candidates.sort(key=lambda item: 0 if item["name"].upper() == preferred else 1)
    return candidates
