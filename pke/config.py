"""Personal Knowledge Engine —— 配置。

集中管理路径、模型、参数，避免散落各处的魔法值。

敏感配置（如 LLM 大语言模型的密钥）一律从环境变量或项目根目录的 .env 读取，
绝不硬编码进代码；.env 已被 .gitignore 忽略，不会进版本库。
优先级：真实环境变量 > .env 文件 > 代码默认值。
"""
from __future__ import annotations

import os
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载器（零依赖）。

    只解析 KEY=VALUE 行，忽略空行与 # 注释。
    不覆盖已存在的环境变量，保证命令行 / CI 的临时覆盖优先。
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    """读取环境变量，缺省时回落到 default。"""
    return os.environ.get(key, default).strip()

# 数据目录
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"      # 原始资料（不可变）
WIKI_DIR = DATA_DIR / "wiki"    # 沉淀的知识

# ---- LLM（大语言模型）配置 ----
# provider（提供方）只是「换 base_url + 换 model」的区别，协议统一走 OpenAI 兼容的
# /chat/completions，因此切换 knot / deepseek / openai / ollama 不需要改业务代码。
# 提供方标识：knot / deepseek / openai / ollama
LLM_PROVIDER = _env("LLM_PROVIDER", "knot")
# OpenAI 兼容地址（不含 /chat/completions）
LLM_BASE_URL = _env("LLM_BASE_URL", "https://knot.woa.com/v1")
LLM_API_KEY = _env("LLM_API_KEY", "")                        # 密钥，从环境变量注入
LLM_MODEL = _env("LLM_MODEL", "gpt-4o-mini")                 # 模型名
LLM_TIMEOUT = int(_env("LLM_TIMEOUT", "60") or 60)           # 单次请求超时（秒）
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.2") or 0.2)  # 采样温度，测试生成场景要稳定就调低
LLM_MAX_RETRIES = int(_env("LLM_MAX_RETRIES", "2") or 2)     # 网络/5xx 重试次数

# 旧占位配置：保留仅为向后兼容，新代码一律用上面的 LLM_*。
MODEL_PROVIDER = LLM_PROVIDER
MODEL_NAME = LLM_MODEL
API_KEY = LLM_API_KEY

# 摄取参数
PDF_OCR_THRESHOLD = 50          # 页面文本 < 50 字符时，判定为扫描件，需 OCR

# 知识路由参数（冷热分层）
COLD_TIER_MIN_CHUNKS = 30       # chunk 数超过此阈值，视为长尾文档，只进 RAG 不编译进 Wiki
