"""PP-StructureV3 流水线封装：离线模型目录、GPU/CPU、结果归一化。

运行时纪律：models/ 下缺模型直接报 MODEL_MISSING，绝不联网下载。
模型由 scripts/setup_models.py 在安装阶段一次性预下载。
"""
import os
import threading
from pathlib import Path

import config as cfgmod  # noqa: E402  （不 import paddle，可先加载以取 ASCII 模型路径）

ROOT = Path(__file__).resolve().parent.parent
MODELS = cfgmod.MODELS_HOME

# 必须在 import paddlex/paddleocr 之前设置；缓存指向 ASCII 路径（见 config.MODELS_HOME）
os.environ.setdefault("PADDLE_PDX_DISABLE_UPDATE_CHECK", "True")
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(MODELS))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import device as devmod  # noqa: E402

_pipeline = None
_pipeline_key = None
_predict_lock = threading.Lock()


class PipelineError(RuntimeError):
    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        self.hint = hint


def model_dir(name: str):
    for p in (MODELS / "official_models" / name, MODELS / name):
        if p.exists():
            return str(p)
    raise PipelineError(
        "MODEL_MISSING", f"本地模型目录缺失：{name}",
        "先运行 scripts\\setup.cmd 预下载模型（安装阶段联网，运行时离线）")


def get_pipeline():
    global _pipeline, _pipeline_key
    cfg = cfgmod.load_config()
    m = cfg["model"]
    dev = devmod.detect_device(m["device"])
    device = "gpu:0" if dev["device"] == "gpu" else "cpu"
    key = (device, m["layout_model"], m["det_model"], m["rec_model"],
           m["table_model"], cfg["parse"]["use_table_recognition"])
    if _pipeline is not None and _pipeline_key == key:
        return _pipeline
    with _predict_lock:
        if _pipeline is not None and _pipeline_key == key:
            return _pipeline
        try:
            from paddleocr import PPStructureV3
        except Exception as e:
            raise PipelineError("PADDLEOCR_IMPORT_FAILED", f"paddleocr 导入失败：{str(e)[:300]}",
                                "检查 .venv 是否已安装 paddleocr（scripts\\setup.cmd）")
        kwargs = dict(
            layout_detection_model_name=m["layout_model"],
            layout_detection_model_dir=model_dir(m["layout_model"]),
            text_detection_model_name=m["det_model"],
            text_detection_model_dir=model_dir(m["det_model"]),
            text_recognition_model_name=m["rec_model"],
            text_recognition_model_dir=model_dir(m["rec_model"]),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_table_recognition=bool(cfg["parse"]["use_table_recognition"]),
            device=device,
        )
        if cfg["parse"]["use_table_recognition"]:
            kwargs["wired_table_structure_recognition_model_name"] = m["table_model"]
            kwargs["wired_table_structure_recognition_model_dir"] = model_dir(m["table_model"])
        kwargs.update(use_seal_recognition=False, use_formula_recognition=False,
                      use_chart_recognition=False, use_region_detection=False)
        try:
            _pipeline = PPStructureV3(**kwargs)
        except TypeError:
            # 个别版本不接受 model_dir 关键字时退回模型名（缓存已在项目内）
            for k in list(kwargs):
                if k.endswith("_model_dir"):
                    kwargs.pop(k)
            _pipeline = PPStructureV3(**kwargs)
        except Exception as e:
            raise PipelineError("PIPELINE_INIT_FAILED", f"流水线初始化失败：{str(e)[:400]}")
        _pipeline_key = key
        return _pipeline


def invalidate():
    # 非阻塞：置空引用即可（GIL 下原子）。正在跑的 predict 已持有自己的 pipe
    # 局部引用，会安全跑完；下一次 get_pipeline 见空重建。若在此抢 _predict_lock，
    # 会被长推理占锁堵死，连带 config 保存/探活全部卡住（实测撞过）。
    global _pipeline, _pipeline_key
    _pipeline = None
    _pipeline_key = None


def confidence_tier(score, cfg):
    if score is None:
        return "none"
    p = cfg["parse"]
    if score >= p["review_confidence"]:
        return "high"
    if score >= p["min_confidence"]:
        return "review"
    return "low"


def _bbox_from_poly(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def _norm(bbox, w, h):
    x0, y0, x1, y1 = bbox
    return [round(x0 / w * 1000, 2), round(y0 / h * 1000, 2),
            round(x1 / w * 1000, 2), round(y1 / h * 1000, 2)]


def normalize(raw: dict, width: int, height: int, scale: float, cfg: dict) -> dict:
    """把 PP-StructureV3 的 res.json 归一化成前端形状。坐标还原到原图像素系。"""
    inv = 1.0 / scale

    def fix_box(b):
        return [round(float(v) * inv, 1) for v in b]

    layout = []
    for box in (raw.get("layout_det_res") or {}).get("boxes", []):
        coord = fix_box(box.get("coordinate", [0, 0, 0, 0]))
        layout.append({
            "label": box.get("label", "unknown"),
            "cls_id": box.get("cls_id"),
            "score": round(float(box.get("score", 0)), 4),
            "bbox": coord,
            "bboxNorm": _norm(coord, width, height),
        })

    ocr_src = raw.get("overall_ocr_res") or {}
    texts = ocr_src.get("rec_texts", [])
    scores = ocr_src.get("rec_scores", [])
    polys = ocr_src.get("rec_polys", [])
    ocr = []
    for i, text in enumerate(texts):
        score = float(scores[i]) if i < len(scores) else None
        poly = [[round(float(p[0]) * inv, 1), round(float(p[1]) * inv, 1)]
                for p in polys[i]] if i < len(polys) else None
        bbox = fix_box(_bbox_from_poly(polys[i])) if poly else None
        ocr.append({
            "text": text,
            "confidence": round(score, 4) if score is not None else None,
            "tier": confidence_tier(score, cfg),
            "poly": poly,
            "bbox": bbox,
            "bboxNorm": _norm(bbox, width, height) if bbox else None,
        })

    tables = []
    table_boxes = [b for b in layout if b["label"] in ("table", "table_title")]
    for i, t in enumerate(raw.get("table_res_list") or []):
        region = table_boxes[i]["bbox"] if i < len(table_boxes) else None
        tables.append({
            "bbox": region,
            "bboxNorm": _norm(region, width, height) if region else None,
            "html": t.get("pred_html", ""),
        })

    blocks = []
    for b in raw.get("parsing_res_list") or []:
        bbox = b.get("block_bbox") or b.get("bbox")
        bbox = fix_box(bbox) if bbox else None
        blocks.append({
            "label": b.get("block_label", "text"),
            "content": b.get("block_content", ""),
            "bbox": bbox,
            "bboxNorm": _norm(bbox, width, height) if bbox else None,
        })

    return {
        "engine": "PP-StructureV3",
        "width": width, "height": height, "scale": scale,
        "layout": layout, "ocr": ocr, "tables": tables, "blocks": blocks,
        "counts": {"layout": len(layout), "ocr": len(ocr), "tables": len(tables)},
    }


def predict_image(img_path: Path) -> dict:
    """对单张图片真跑 V3 流水线，返回归一化结果 + 原始 JSON。"""
    import cv2
    import numpy as np

    cfg = cfgmod.load_config()
    pipe = get_pipeline()
    img = cv2.imdecode(np.fromfile(str(img_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise PipelineError("BAD_IMAGE", f"无法读取图片：{img_path.name}")
    h, w = img.shape[:2]
    max_side = int(cfg["model"]["max_side"])
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    with _predict_lock:
        try:
            results = list(pipe.predict(input=img))
        except Exception as e:
            raise PipelineError("PREDICT_FAILED", f"模型推理失败：{str(e)[:400]}")
    if not results:
        raise PipelineError("EMPTY_RESULT", "流水线未返回任何结果")
    raw = results[0].json
    if isinstance(raw, str):
        import json as _json
        raw = _json.loads(raw)
    if "res" in raw and isinstance(raw["res"], dict):
        raw = raw["res"]
    out = normalize(raw, w, h, scale, cfg)
    out["raw"] = raw
    out["device"] = devmod.detect_device()["device"]
    return out