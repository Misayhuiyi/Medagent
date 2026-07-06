#!/usr/bin/env python3
"""
医学知识库 Agent — 通过 Tool 调用知识库 + DeepSeek LLM 推理

用法:
  python agent.py "IV期肺腺癌，EGFR 19del，一线方案？"
  python agent.py --interactive    # 交互模式
"""
import sys
import os
import json
import re
import logging
from pathlib import Path

# 加载 .env 或直接设置 API key
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-abc9e9ffc2b34b269062de2fd9aeeff9")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# 导入 Tool 层
sys.path.insert(0, str(Path(__file__).parent))
from tool import TOOLS, run_agent_tool

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agent")


SYSTEM_PROMPT = """你是一位肿瘤科临床决策助手，基于循证医学指南回答医生的问题。

## 核心规则
1. **一次性检索**：只调用一次 search_medical_guidelines（最多补一次不同方向的检索），不要反复检索同一问题
2. **多学会对比**：如果用户要求NCCN/CSCO/ASCO/ESMO等多家学会的推荐，**必须传 source_orgs 参数**列出所有学会
3. **直接回答**：检索结果拿到后立刻回答，不要再做二次、三次补充检索
4. **诚实说明**：检索结果不足以回答时，明确说明来源有限，不要编造
5. 引用时注明指南来源、年份和 PDF 页码
6. 使用中文回答"""


# ══════════════════════════════════════════════════════
#  LLM 调用
# ══════════════════════════════════════════════════════

def call_llm(messages: list[dict], tools: list = None, stream: bool = False,
             retries: int = 3) -> dict:
    """调用 DeepSeek API，带重试"""
    import httpx, time

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4000,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    last_error = None
    for attempt in range(retries):
        try:
            resp = httpx.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120.0,
            )
            if resp.status_code == 400:
                # 400可能是临时限流，等待后重试
                wait = 2 ** attempt
                logger.warning(f"  [API 400] 重试 {attempt+1}/{retries}, 等待 {wait}s...")
                time.sleep(wait)
                last_error = f"HTTP 400 (attempt {attempt+1})"
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"  [API error] {e}, 重试 {attempt+1}/{retries}, 等待 {wait}s...")
            time.sleep(wait)
            last_error = str(e)

    raise RuntimeError(f"API调用失败(重试{retries}次): {last_error}")


# ══════════════════════════════════════════════════════
#  Agent 主循环
# ══════════════════════════════════════════════════════

def run_tool(tool_name: str, args: dict) -> str:
    """执行 Tool 调用"""
    return run_agent_tool(tool_name, args)


def chat(question: str, max_turns: int = 3) -> str:
    """单轮对话"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    for turn in range(max_turns):
        logger.info(f"[Agent Turn {turn+1}]")
        response = call_llm(messages, tools=TOOLS)

        choice = response["choices"][0]
        msg = choice["message"]

        # 检查是否需要调用 Tool
        if msg.get("tool_calls"):
            assistant_msg = {"role": "assistant", "tool_calls": msg["tool_calls"]}
            if msg.get("content"):
                assistant_msg["content"] = msg["content"]
            messages.append(assistant_msg)

            for tc in msg["tool_calls"]:
                func = tc["function"]
                tool_result = run_tool(func["name"], json.loads(func["arguments"]))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result[:6000],
                })

            # 继续下一轮，让 LLM 处理 Tool 结果
            continue

        # 没有 Tool 调用 → 最终回答
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        if reasoning and not content:
            content = _extract_from_reasoning(reasoning)
        return content

    return "抱歉，未能在限定轮次内完成检索。"


def _extract_from_reasoning(text: str) -> str:
    """从 reasoning_content 提取可读内容"""
    lines = text.strip().split("\n")
    meaningful = [l for l in lines if len(l) > 20 and not l.startswith("好的") and not l.startswith("用户")]
    return "\n".join(meaningful[:20]) if meaningful else text[:500]


# ══════════════════════════════════════════════════════
#  交互模式
# ══════════════════════════════════════════════════════

def interactive():
    """交互式对话"""
    print("=" * 60)
    print("  医学知识库 Agent — 基于 279 篇肿瘤临床指南")
    print("  LLM: DeepSeek-v4-flash | 输入 'quit' 退出")
    print("=" * 60)

    while True:
        try:
            q = input("\n🔬 临床问题: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not q:
            continue
        if q.lower() in ("quit", "exit", "q"):
            break

        print(f"\n📋 检索中...")
        answer = chat(q)
        print(f"\n📝 回答:\n{answer}")
        print("-" * 60)


# ══════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-i", "--interactive"):
        interactive()
    else:
        question = " ".join(sys.argv[1:])
        print(f"🔬 {question}\n")
        answer = chat(question)
        print(f"📝 {answer}")


if __name__ == "__main__":
    main()
