"""LLM（大语言模型）接入自检脚本。

两种用法：

1. 常规自检——按 .env 的配置真实调用一次，验证密钥与地址是否正确：

       python scripts/llm_check.py

2. 探测模式——还不确定 base_url（接口地址）时，批量试候选地址，
   找出那个「真能返回 JSON」的：

       python scripts/llm_check.py --probe
       python scripts/llm_check.py --probe --model gpt-4o-mini

退出码：0 成功，1 失败。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pke import config  # noqa: E402
from pke.llm import ChatMessage, LLMClient, LLMError  # noqa: E402

# base_url 候选：knot 平台网关地址未公开，这里把常见形态都列上逐个试
CANDIDATE_BASE_URLS = [
    "https://knot.woa.com/v1",
    "https://knot.woa.com/api/v1",
    "https://knot.woa.com/openapi/v1",
    "https://knot.woa.com/llm/v1",
    "https://knot.woa.com/v1/openai",
    "https://knot.woa.com/gateway/v1",
]

PROBE_PROMPT = "只回复两个字：OK"


def mask(secret: str) -> str:
    """密钥脱敏：只留前 4 位与后 4 位，避免日志泄露。"""
    if not secret:
        return "(空)"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


def print_config(base_url: str, model: str) -> None:
    print("=== 当前配置 ===")
    print(f"  provider（提供方） : {config.LLM_PROVIDER}")
    print(f"  base_url（接口地址）: {base_url}")
    print(f"  model（模型）      : {model}")
    print(f"  api_key（密钥）    : {mask(config.LLM_API_KEY)}")
    print(f"  timeout（超时）    : {config.LLM_TIMEOUT}s")
    print()


def run_check(model: str | None = None) -> int:
    client = LLMClient(model=model)
    print_config(client.base_url, client.model)

    if not client.is_configured():
        print("[FAIL] 未配置 api_key（密钥）。请复制 .env.example 为 .env 并填入 LLM_API_KEY。")
        return 1

    print(f"=== 发起测试调用 → {client.endpoint()} ===")
    try:
        response = client.chat([ChatMessage(role="user", content=PROBE_PROMPT)], max_tokens=16)
    except LLMError as exc:
        print(f"[FAIL] 调用失败：{exc}")
        print()
        print("排查建议：")
        print("  1. 地址不对（返回 HTML 登录页）→ 用 --probe 探测，或复制正确的网关地址")
        print("  2. 401/403 → 密钥无效或已过期，重新生成")
        print("  3. 404 → 路径不对，确认地址是否以 /v1 结尾（客户端会自动拼 /chat/completions）")
        print("  4. 模型名不对 → 用 --model 换一个再试")
        return 1

    print(f"[OK] 调用成功，模型回传：{response.model or '(未回传)'}")
    print(f"     回复内容：{response.content!r}")
    print(f"     finish_reason（结束原因）：{response.finish_reason}")
    if response.usage:
        print(f"     token（词元）用量：{response.usage}")
    return 0


def run_probe(model: str) -> int:
    print(f"=== 探测模式：逐个尝试候选 base_url（模型 {model}）===")
    print(f"密钥：{mask(config.LLM_API_KEY)}\n")
    if not config.LLM_API_KEY:
        print("[FAIL] 未配置 api_key，无法探测。")
        return 1

    for base_url in CANDIDATE_BASE_URLS:
        client = LLMClient(base_url=base_url, model=model, max_retries=0, timeout=15)
        try:
            response = client.chat([ChatMessage(role="user", content=PROBE_PROMPT)], max_tokens=16)
        except LLMError as exc:
            reason = str(exc).split("：")[-1][:90]
            print(f"[--] {base_url:<40} 失败：{reason}")
            continue
        print(f"[OK] {base_url:<40} 成功！回复={response.content[:40]!r}")
        print()
        print("把这个地址填进 .env：")
        print(f"  LLM_BASE_URL={base_url}")
        return 0

    print("\n[FAIL] 所有候选地址都失败。")
    print("请到 knot 平台找「API 接入 / 开发者设置」页面，复制真实的网关地址与模型名，")
    print("填进 .env 后重跑：python scripts/llm_check.py")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM 接入自检")
    parser.add_argument("--probe", action="store_true", help="批量探测候选 base_url")
    parser.add_argument("--model", default=None, help="覆盖 .env 里的模型名")
    args = parser.parse_args()

    model = args.model or config.LLM_MODEL
    return run_probe(model) if args.probe else run_check(model)


if __name__ == "__main__":
    raise SystemExit(main())
