"""Personal Knowledge Engine —— 配置。

集中管理路径、模型、参数，避免散落各处的魔法值。
"""
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent

# 数据目录
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"      # 原始资料（不可变）
WIKI_DIR = DATA_DIR / "wiki"    # 沉淀的知识

# 模型配置（Step 7 问答时用，先占位）
MODEL_PROVIDER = "deepseek"     # 可选: deepseek / openai / ollama
MODEL_NAME = "deepseek-chat"
API_KEY = ""                    # 用环境变量注入，不要硬编码

# 摄取参数
PDF_OCR_THRESHOLD = 50          # 页面文本 < 50 字符时，判定为扫描件，需 OCR
