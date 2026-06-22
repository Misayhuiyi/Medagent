"""LLM 文本清洗器：用 deepseek-v4-flash 清洗 MinerU OCR 产生的乱码。

逐条清洗，不依赖标记解析——LLM 输出即为清洗后文本。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

CLEANER_SYSTEM_PROMPT = """你是医学指南文本清洗器。把 MinerU OCR 提取的文本修复为干净、可读的医学中文。

清洗规则：
1. 修复 OCR 字符混淆：川→Ⅲ（罗马数字）、1级→Ⅰ级
2. 补全缺失字符："A期"→"ⅢA期"、"B期"→"ⅢB期"
3. 移除 HTML 标签残片（<table>、</td> 等）
4. 移除不可见控制字符和乱码
5. 保持 Markdown 结构：# 标题、| 表格 |、**加粗**、列表
6. **保留 LaTeX 数学公式不动**（$...$、$$...$$、\\mathbf{...} 等），它们会被渲染为数学符号
7. 保留领域专业术语和分类名称

只输出清洗后的纯文本，不要解释、评论或标记。"""

# 单个 chunk 最大字符数（超过则截断）
MAX_CHUNK_CHARS = 1200
# 单条清洗超时（部分 KB 文本较长，需要更长时间）
CLEAN_TIMEOUT_SECONDS = 60
# 最大并发清洗数（后台任务，控制 API 压力）
MAX_CONCURRENT = 3


class TextCleaner:
    """用 LLM 逐条清洗 OCR 损坏的医学指南文本。"""

    def __init__(self) -> None:
        self._client = None
        self._model: str = ""
        self._base_url: str = ""
        self._api_key: str = ""

    def _ensure_client(self) -> bool:
        """初始化 AsyncOpenAI 客户端。成功返回 True。"""
        if self._client is not None:
            return True

        from DataCode.web_server import _app_state

        config = _app_state.get("config")
        if config is None:
            logger.warning("TextCleaner: config not available")
            return False

        self._base_url = config.get("llm.base_url", "https://api.deepseek.com/v1")
        self._model = config.get("llm.default_model", "deepseek-v4-flash")
        self._api_key = config.get("llm.api_key", "") or "dummy"

        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key or "dummy",
                base_url=self._base_url or None,
                default_headers={"User-Agent": "curl/8.17.0"},
            )
        except Exception:
            logger.exception("TextCleaner: failed to create AsyncOpenAI client")
            return False

        return True

    async def clean_batch(self, texts: list[str]) -> list[str]:
        """逐条清洗多段文本（后台并发，限流 MAX_CONCURRENT）。失败返回原文。"""
        if not texts:
            return texts
        if not self._ensure_client():
            return texts

        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def _clean_one(idx: int, text: str) -> tuple[int, str]:
            async with sem:
                try:
                    cleaned = await self._clean_single(text)
                    return (idx, cleaned)
                except Exception:
                    return (idx, text)

        # 并发清洗
        tasks = [_clean_one(i, t) for i, t in enumerate(texts)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 按原始顺序组装
        cleaned_list = list(texts)  # 默认原文
        for result in results:
            if isinstance(result, tuple):
                idx, cleaned = result
                if cleaned:
                    cleaned_list[idx] = cleaned
            # 异常跳过（保留原文）

        cleaned_count = sum(1 for i, t in enumerate(texts) if cleaned_list[i] != texts[i])
        if cleaned_count > 0:
            logger.info("TextCleaner: cleaned %d/%d chunks", cleaned_count, len(texts))
        return cleaned_list

    async def _clean_single(self, text: str) -> str:
        """清洗单条文本。超时或失败返回原文。"""
        trimmed = text[:MAX_CHUNK_CHARS]

        from DataCode.llm_callback import LLMCallTracker

        tracker = LLMCallTracker.instance()
        call_id = tracker.start(
            agent="text_cleaner",
            model=self._model,
            base_url=self._base_url,
            api_key=self._api_key,
            prompt=CLEANER_SYSTEM_PROMPT + "\n" + trimmed,
            kind="chat",
        )

        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": CLEANER_SYSTEM_PROMPT},
                        {"role": "user", "content": f"请清洗以下医学指南文本：\n\n{trimmed}"},
                    ],
                    temperature=0.2,
                ),
                timeout=CLEAN_TIMEOUT_SECONDS,
            )

            result = response.choices[0].message.content or ""
            tracker.succeed(call_id, result)
            return result.strip()

        except asyncio.TimeoutError:
            logger.debug("TextCleaner: single clean timeout")
            tracker.fail(call_id, TimeoutError("text_cleaner timeout"))
            return text
        except Exception:
            logger.debug("TextCleaner: single clean failed")
            return text

