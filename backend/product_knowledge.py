from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


PRODUCTS: Dict[str, dict] = {
    "MaTouch_ESP32S3": {
        "aliases": ["matouch", "esp32s3", "matouch_esp32s3", "ma touch", "esp32 s3"],
        "hint": "您可以让我生成一个笑脸的代码，或者帮您写触摸屏交互示例。",
        "knowledge_file": "matouch_esp32s3.md",
    },
    "ESP32-S3-WROOM-1": {
        "aliases": ["esp32-s3-wroom-1", "wroom-1", "wroom", "esp32 s3", "esp32s3 wroom", "esp32-s3"],
        "hint": "您也可以让我生成 MPU-6050 串口输出代码，或者给您 I2C 接线建议。",
        "knowledge_file": "esp32_s3_wroom_1.md",
    },
}

PRODUCT_MODEL_LIST = list(PRODUCTS.keys())


KNOWLEDGE_DIR = Path(__file__).resolve().parent / "product_knowledge"


def list_product_models() -> list[str]:
    return PRODUCT_MODEL_LIST[:]


def normalize_text(text: str) -> str:
    return "".join(ch.lower() for ch in text if ch.isalnum())


def get_product_hint(product_model: str) -> str:
    cfg = PRODUCTS.get(product_model) or {}
    return cfg.get("hint", "您可以继续告诉我您要实现什么功能。")


def get_product_knowledge(product_model: Optional[str]) -> str:
    if not product_model:
        return ""
    cfg = PRODUCTS.get(product_model)
    if not cfg:
        return ""
    fname = cfg.get("knowledge_file")
    if not fname:
        return ""
    p = KNOWLEDGE_DIR / fname
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()
