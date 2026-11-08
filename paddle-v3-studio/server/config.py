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
        "match_single_line": True,
        "match_multi_line": True,
        "cross_page_check": True,
        "min_no_confidence": 0.6,
        "no_format_regex": "",
        "prefer_first_page": True,
        "normalize_confusables": False,
    },
}

_lock = threading.RLock()


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
    ct = merged["contract"]
    if not (0 <= ct["min_no_confidence"] <= 1):
        errs.append("min_no_confidence 必须在 0~1")
    fmt = (ct.get("no_format_regex") or "").strip()
    if fmt:
        import re
        try:
            re.compile(fmt)
        except re.error as e:
            errs.append(f"no_format_regex 不是合法正则：{e}")
    return errs


def save_config(patch: dict) -> dict:
    """纯文件存储：校验后把合并结果写回 data/config.json。
    锁内直接读文件而非再调 load_config，避免嵌套抢锁；不触发任何运行时重建。"""
    errs = validate_config(patch)
    if errs:
        raise ValueError("; ".join(errs))
    with _lock:
        saved = {}
        if CONFIG_PATH.exists():
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = _merge(_merge(DEFAULTS, saved), patch)
        DATA.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return merged


SCHEMA = {
    "groups": [
        {
            "key": "parse", "label": "解析",
            "fields": [
                {"key": "use_table_recognition", "label": "启用表格识别（SLANeXt）", "type": "bool",
                 "help": {"作用": "把表格区域识别成 HTML 并提取明细行（合同明细校验依赖它）。",
                          "生效": "保存后下次解析时 get_pipeline 按开关重建流水线；关闭则 tables 为空。",
                          "选项": "开=识别表格（合同/明细场景）；关=只做版面+OCR，速度更快。"}},
                {"key": "review_confidence", "label": "高置信阈值（≥ 为高）", "type": "number", "min": 0, "max": 1, "step": 0.01,
                 "help": {"作用": "OCR 置信度 ≥ 此值判为「高置信」（绿）。",
                          "生效": "结果归一化时实时读取，决定三档分色与统计；须大于 min_confidence。",
                          "选项": "0~1，默认 0.9；调高则高置信门槛更严。"}},
                {"key": "min_confidence", "label": "复核下限（< 为低置信）", "type": "number", "min": 0, "max": 1, "step": 0.01,
                 "help": {"作用": "置信度 < 此值判「低置信」（红），介于两阈值之间判「需复核」（黄）。",
                          "生效": "与 review_confidence 一同实时生效；须小于 review_confidence。",
                          "选项": "0~1，默认 0.7；调高则更多行落入需复核/低置信。"}},
                {"key": "show_layout_boxes", "label": "显示版面区域框", "type": "bool",
                 "help": {"作用": "左栏是否叠加版面区域框（类别+score）。",
                          "生效": "纯前端显示开关，实时读取，不改变解析结果。", "选项": "开/关。"}},
                {"key": "show_ocr_boxes", "label": "显示 OCR 文本框", "type": "bool",
                 "help": {"作用": "左栏是否叠加 OCR 文本框（按置信度三档着色）。",
                          "生效": "纯前端显示开关，实时读取。", "选项": "开/关。"}},
            ],
        },
        {
            "key": "model", "label": "模型与设备",
            "fields": [
                {"key": "device", "label": "计算设备", "type": "enum", "options": ["auto", "gpu", "cpu"],
                 "help": {"作用": "选择推理计算设备。",
                          "生效": "保存后懒生效：下次读状态/解析时按新值重探；GPU 做真实张量自检，失败降级 CPU 并在设置页留痕。",
                          "选项": "auto=GPU 优先自动降级；gpu=强制 GPU（不可用仍降级）；cpu=强制 CPU。"}},
                {"key": "layout_model", "label": "版面检测模型", "type": "text",
                 "help": {"作用": "版面检测所用模型名。",
                          "生效": "下次解析按名重建流水线；目录须存在于 MODEL-V3/official_models，否则报 MODEL_MISSING。",
                          "选项": "默认 PP-DocLayoutV3；可改其他已离线就位的版面模型。"}},
                {"key": "det_model", "label": "文本检测模型", "type": "text",
                 "help": {"作用": "文本行检测（定位四点框）模型名。",
                          "生效": "下次解析按名重建；须离线就位。",
                          "选项": "默认 PP-OCRv5_server_det（server 版更准）。"}},
                {"key": "rec_model", "label": "文本识别模型", "type": "text",
                 "help": {"作用": "文本行识别（图像→文字+置信度）模型名。",
                          "生效": "下次解析按名重建；须离线就位。",
                          "选项": "默认 PP-OCRv5_server_rec。"}},
                {"key": "table_model", "label": "表格识别模型", "type": "text",
                 "help": {"作用": "有线表格结构识别模型名。",
                          "生效": "启用表格识别时下次解析按名重建；须离线就位。",
                          "选项": "默认 SLANeXt_wired（针对有线表）。"}},
                {"key": "max_side", "label": "送入模型的最长边像素", "type": "number", "min": 640, "max": 4096, "step": 1,
                 "help": {"作用": "送模型前图像最长边上限，超出按比例缩小，坐标再还原回原图像素系。",
                          "生效": "每次解析实时读取。",
                          "选项": "640~4096，默认 2000；调大保细节但更慢，调小更快但可能丢小字。"}},
            ],
        },
        {
            "key": "contract", "label": "合同校验",
            "fields": [
                {"key": "source_url", "label": "合同数据源地址（Spring Boot）", "type": "text",
                 "help": {"作用": "合同校验对照的数据源地址。",
                          "生效": "校验/重新校验时实时使用；GET /api/health 探连通性。",
                          "选项": "默认 http://127.0.0.1:8081（contract-source）。"}},
                {"key": "page_dpi", "label": "合同逐页转图 DPI", "type": "number", "min": 72, "max": 400, "step": 1,
                 "help": {"作用": "合同 PDF/DOCX 逐页渲染成图片的分辨率。",
                          "生效": "下次合同解析的转图阶段读取；DPI 越高图越清、识别越准，但更大更慢。",
                          "选项": "72~400，默认 150（A4 约 1275×1651）。"}},
                {"key": "amount_tolerance", "label": "金额比对容差", "type": "number", "min": 0, "max": 1, "step": 0.001,
                 "help": {"作用": "数量/单价/金额与数据源比对的绝对容差。",
                          "生效": "校验时实时读取；|源值-文件值| ≤ 容差判一致。",
                          "选项": "0~1，默认 0.01（精确到分）。"}},
                {"key": "match_single_line", "label": "合同号单行匹配（标签与编号同行）", "type": "bool",
                 "help": {"作用": "匹配「合同编号：HT-2026-001」这类标签与编号同行的写法。",
                          "生效": "下次合同解析读取，独立于多行匹配。",
                          "选项": "开/关，默认开。"}},
                {"key": "match_multi_line", "label": "合同号多行匹配（标签/编号分行或编号折行）", "type": "bool",
                 "help": {"作用": "匹配标签独占一行、编号在下一行；编号被折成两行也会拼接。",
                          "生效": "下次合同解析读取。",
                          "选项": "开/关，默认开。"}},
                {"key": "cross_page_check", "label": "跨页合同号准确性校验（一致性+多数投票）", "type": "bool",
                 "help": {"作用": "统计合同号在各页出现、判定一致性，并按多数投票选定最终编号。",
                          "生效": "下次合同解析读取；不一致会在校验报告记一条不符。",
                          "选项": "开=多数投票选定；关=取首个命中。"}},
                {"key": "min_no_confidence", "label": "合同号 OCR 置信度下限（低于则丢弃）", "type": "number", "min": 0, "max": 1, "step": 0.01,
                 "help": {"作用": "候选行 OCR 置信度低于此值则丢弃，挡低质量误读。",
                          "生效": "下次合同解析读取，过滤候选；过滤计数见跨页区块。",
                          "选项": "0~1，默认 0.6；调高更少误检，但可能漏低质扫描。"}},
                {"key": "no_format_regex", "label": "合同号格式白名单正则（fullmatch，空=不启用）", "type": "text",
                 "help": {"作用": "编号须完整匹配（fullmatch）该正则才采纳，挡发票号/附件号误命中。",
                          "生效": "下次合同解析读取；空=不启用；非法正则在保存时被拒。",
                          "选项": "空（禁用）或如 ^HT-\\d{4}-\\d{3}$（按实际编号格式填）。"}},
                {"key": "prefer_first_page", "label": "首页优先（选定/平票优先最早页）", "type": "bool",
                 "help": {"作用": "选定编号或投票平票时优先最早页命中（合同号通常在首页）。",
                          "生效": "下次合同解析读取，作用于多数投票的平票裁决。",
                          "选项": "开/关，默认开。"}},
                {"key": "normalize_confusables", "label": "易混字符归一化（O→0、I/l→1）", "type": "bool",
                 "help": {"作用": "跨页比对与输出编号做 O→0、I/l→1 归一化，减少形近字导致的假不一致。",
                          "生效": "下次合同解析读取；开启后输出编号可能纠正 OCR 形近误读。",
                          "选项": "开/关，默认关（可能掩盖真实差异，按需开启）。"}},
            ],
        },
    ]
}