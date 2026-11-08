"""运行时配置：data/config.json，默认值在此唯一来源。"""
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG_PATH = DATA / "config.json"

# Paddle 的 C++ 推理引擎在 Windows 上无法从含中文的路径加载模型（实测报
# json.exception.parse_error.101 empty input）。本工程在「方案B：版面分析与OCR」
# 下，路径含中文，故模型库必须放 ASCII 路径。默认取 OCR-ALONE/MODEL-V3，
# 与另一工程引用 ../MODEL/offline 的惯例一致；可用 PADDLE_V3_MODEL_HOME 覆盖。
MODELS_HOME = Path(os.environ.get(
    "PADDLE_V3_MODEL_HOME", str(ROOT.parent.parent / "MODEL-V3"))).resolve()

DEFAULTS = {
    "parse": {
        "use_table_recognition": True,
        "review_confidence": 0.9,
        "min_confidence": 0.7,
        "show_layout_boxes": True,
        "show_ocr_boxes": True,
    },
    "model": {
        "device": "auto",
        "layout_model": "PP-DocLayoutV3",
        "det_model": "PP-OCRv5_server_det",
        "rec_model": "PP-OCRv5_server_rec",
        "table_model": "SLANeXt_wired",
        "max_side": 2000,
    },
    "contract": {
        "source_url": "http://127.0.0.1:8081",
        "page_dpi": 150,
        "amount_tolerance": 0.01,
    },
}

_lock = threading.Lock()


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    with _lock:
        saved = {}
        if CONFIG_PATH.exists():
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return _merge(DEFAULTS, saved)


def validate_config(patch: dict) -> list:
    merged = _merge(load_config(), patch)
    errs = []
    p = merged["parse"]
    if not (0 <= p["min_confidence"] <= 1):
        errs.append("min_confidence 必须在 0~1")
    if not (0 <= p["review_confidence"] <= 1):
        errs.append("review_confidence 必须在 0~1")
    if p["min_confidence"] >= p["review_confidence"]:
        errs.append("min_confidence 必须小于 review_confidence")
    if merged["model"]["device"] not in ("auto", "gpu", "cpu"):
        errs.append("device 只能是 auto/gpu/cpu")
    if merged["contract"]["page_dpi"] < 72 or merged["contract"]["page_dpi"] > 400:
        errs.append("page_dpi 必须在 72~400")
    return errs


def save_config(patch: dict) -> dict:
    errs = validate_config(patch)
    if errs:
        raise ValueError("; ".join(errs))
    with _lock:
        merged = _merge(load_config(), patch)
        DATA.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged


SCHEMA = {
    "groups": [
        {
            "key": "parse", "label": "解析",
            "fields": [
                {"key": "use_table_recognition", "label": "启用表格识别（SLANeXt）", "type": "bool"},
                {"key": "review_confidence", "label": "高置信阈值（≥ 为高）", "type": "number", "min": 0, "max": 1, "step": 0.01},
                {"key": "min_confidence", "label": "复核下限（< 为低置信）", "type": "number", "min": 0, "max": 1, "step": 0.01},
                {"key": "show_layout_boxes", "label": "显示版面区域框", "type": "bool"},
                {"key": "show_ocr_boxes", "label": "显示 OCR 文本框", "type": "bool"},
            ],
        },
        {
            "key": "model", "label": "模型与设备",
            "fields": [
                {"key": "device", "label": "计算设备", "type": "enum", "options": ["auto", "gpu", "cpu"]},
                {"key": "layout_model", "label": "版面检测模型", "type": "text"},
                {"key": "det_model", "label": "文本检测模型", "type": "text"},
                {"key": "rec_model", "label": "文本识别模型", "type": "text"},
                {"key": "table_model", "label": "表格识别模型", "type": "text"},
                {"key": "max_side", "label": "送入模型的最长边像素", "type": "number", "min": 640, "max": 4096, "step": 1},
            ],
        },
        {
            "key": "contract", "label": "合同校验",
            "fields": [
                {"key": "source_url", "label": "合同数据源地址（Spring Boot）", "type": "text"},
                {"key": "page_dpi", "label": "合同逐页转图 DPI", "type": "number", "min": 72, "max": 400, "step": 1},
                {"key": "amount_tolerance", "label": "金额比对容差", "type": "number", "min": 0, "max": 1, "step": 0.001},
            ],
        },
    ]
}