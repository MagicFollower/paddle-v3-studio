"""安装阶段一次性预下载 V3 流水线全部模型到 ASCII 模型库（此后运行时零联网）。

用法：.venv\\Scripts\\python.exe scripts\\setup_models.py
模型库默认在 OCR-ALONE/MODEL-V3（ASCII 路径，Paddle C++ 引擎不能读中文路径）。
依赖安装阶段联网；下载完成后运行时不再触网（更新检查已禁用，模型目录显式传入）。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import config as cfgmod  # noqa: E402  （不 import paddle，安全）

MODELS = cfgmod.MODELS_HOME
os.environ["PADDLE_PDX_DISABLE_UPDATE_CHECK"] = "True"
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(MODELS))
# 国内网络走百度 BOS 官方源（huggingface 默认源在本机会挂起）
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")


def main():
    MODELS.mkdir(parents=True, exist_ok=True)
    cfg = cfgmod.load_config()
    m = cfg["model"]
    print(f"[setup] model home (ASCII): {MODELS}")

    # 先探设备（GPU 优先，失败降级 CPU 并记录原因）
    import device as devmod
    dev = devmod.detect_device(m["device"], force=True)
    print(f"[setup] device={dev['device']} fallback={dev['fallback']} reason={dev['reason']}")
    device = "gpu:0" if dev["device"] == "gpu" else "cpu"

    from paddleocr import PPStructureV3
    print("[setup] instantiating PP-StructureV3 (downloads models on first use)...")
    pipe = PPStructureV3(
        layout_detection_model_name=m["layout_model"],
        text_detection_model_name=m["det_model"],
        text_recognition_model_name=m["rec_model"],
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        use_table_recognition=True,
        wired_table_structure_recognition_model_name=m["table_model"],
        use_seal_recognition=False,
        use_formula_recognition=False,
        use_chart_recognition=False,
        use_region_detection=False,
        device=device,
    )
    print("[setup] pipeline ready, running one warm-up predict on a synthetic page...")
    import numpy as np
    img = np.full((320, 640, 3), 255, dtype=np.uint8)
    import cv2
    cv2.putText(img, "PADDLE V3 SETUP 12345", (40, 160),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    res = list(pipe.predict(input=img))
    print(f"[setup] warm-up results: {len(res)}")

    # 模型落在 models/official_models/<name>（paddlex 本地优先读取，运行时零联网）
    official = MODELS / "official_models"
    found = sorted(p.name for p in official.iterdir() if p.is_dir()) if official.exists() else []
    print(f"[setup] official_models entries: {found}")
    needed = [m["layout_model"], m["det_model"], m["rec_model"], m["table_model"],
              "PP-LCNet_x1_0_table_cls", "SLANet_plus",
              "RT-DETR-L_wired_table_cell_det", "RT-DETR-L_wireless_table_cell_det",
              "PP-LCNet_x1_0_doc_ori", "PP-LCNet_x1_0_textline_ori"]
    missing = [n for n in needed if not (official / n).exists() and not (MODELS / n).exists()]
    if missing:
        print(f"[setup][FAIL] models missing after download: {missing}")
        sys.exit(1)
    print("[setup] DONE. Runtime is offline from now on.")


if __name__ == "__main__":
    main()