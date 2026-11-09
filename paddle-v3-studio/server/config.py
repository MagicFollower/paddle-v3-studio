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

# 区域框选与匹配情况的默认配色（与 theme.css 初始方案一致）
COLOR_FIELDS = [
    {"key": "contract_no", "label": "合同号区域", "default": "#dc2626"},
    {"key": "contract_table", "label": "合同明细表格", "default": "#7c3aed"},
    {"key": "layout", "label": "版面区域", "default": "#2563eb"},
    {"key": "ocr_high", "label": "OCR 高置信", "default": "#16a34a"},
    {"key": "ocr_review", "label": "OCR 需复核", "default": "#d97706"},
    {"key": "ocr_low", "label": "OCR 低置信", "default": "#dc2626"},
    {"key": "match_ok", "label": "校验一致", "default": "#16a34a"},
    {"key": "match_bad", "label": "校验不符", "default": "#dc2626"},
]
DEFAULT_COLORS = {c["key"]: c["default"] for c in COLOR_FIELDS}

# LLM 前置提示词（system prompt）最优默认值：基于本工程「合同明细表头→后端业务字段」映射流程固化。
# 用户可在系统设置覆盖（config.llm.system_prompt），空值回退此默认；设置页可一键还原。
# 设计要点：锁定任务边界（只做表头映射）、多对一、仅选给定字段、未知置 null、OCR 噪声归一化、
# 严格 JSON 输出（无解释/思考/代码块），与 llm._build_prompt 的动态字段别名块配合。
DEFAULT_SYSTEM_PROMPT = (
    "你是合同明细表格的「表头→业务字段」映射专家，服务于 OCR 解析后的合同明细自动标准化流水线。\n"
    "\n"
    "【任务】OCR 已从合同表格识别出一行中文表头（不同合同写法各异，可能含空格或轻微噪声）。"
    "你的唯一任务：把每个实际中文表头映射到给定的目标业务字段英文缩写。\n"
    "\n"
    "【规则】\n"
    "1. 只能从给定的目标业务字段中选择，严禁发明列表之外的字段名。\n"
    "2. 多对一：多个同义中文表头（如「品名」「物料名称」「货物名称」「产品名称」）可映射到同一个英文字段；"
    "逐个表头独立判断其语义最匹配的字段。\n"
    "3. 每个字段的中文别名仅作参考提示，以表头真实语义为准；表头含空格或 OCR 噪声（如「品 名」「数 量」）"
    "应先归一化再匹配。\n"
    "4. 语义不符或无法确定的表头，值用 null，不要强行映射。\n"
    "5. 常见对应：序号/编号/项次/行号→排序字段；名称类→品名字段；规格/型号→规格；单位/计量单位→单位；"
    "数量/数目→数量；单价/含税单价→单价；金额/总价/小计/含税金额→金额（最终以给定的目标字段为准）。\n"
    "\n"
    "【输出】只输出一个 JSON 对象：键为中文表头原文（保持原样，含空格），值为目标英文字段缩写或 null。"
    "不要输出任何解释、思考过程、Markdown 代码块标记或多余文字。\n"
    "示例：表头 [\"品名\",\"数量\"]、目标字段 itemName(品名)/quantity(数量) → 输出 {\"品名\":\"itemName\",\"数量\":\"quantity\"}"
)

DEFAULTS = {
    "parse": {
        "use_table_recognition": True,
        "review_confidence": 0.9,
        "min_confidence": 0.7,
        "auto_parse_on_upload": False,
    },
    "display": {
        "show_contract_no": True,
        "show_contract_table": True,
        "show_layout": False,
        "show_ocr": False,
        "default_zoom": 60,
        "colors": dict(DEFAULT_COLORS),
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
    "llm": {
        "enabled": True,
        "base_url": "http://127.0.0.1:9931",
        "model": "spark-x2.6",
        "api_key": "",
        "timeout": 90,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
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
    import re as _re
    hexcolor = _re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    for k, v in (merged["display"].get("colors") or {}).items():
        if not hexcolor.match(str(v)):
            errs.append(f"颜色 {k} 必须是 #RGB 或 #RRGGBB 格式")
    if not (20 <= merged["display"].get("default_zoom", 60) <= 400):
        errs.append("default_zoom 必须在 20~400")
    llm = merged.get("llm", {})
    import re as _llm_re
    base_url = (llm.get("base_url") or "").strip()
    if not base_url:
        errs.append("llm.base_url 不能为空（OpenAI 兼容端点，如 http://127.0.0.1:9931）")
    elif not _llm_re.match(r"^https?://", base_url):
        errs.append("llm.base_url 必须以 http:// 或 https:// 开头")
    if not (llm.get("model") or "").strip():
        errs.append("llm.model 不能为空（端点上的模型名/别名）")
    if float(llm.get("timeout", 90)) <= 0:
        errs.append("llm.timeout 必须大于 0")
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
                {"key": "auto_parse_on_upload", "label": "上传后自动开启解析流水线", "type": "bool",
                 "help": {"作用": "上传文件后是否立即自动跑解析流水线。",
                          "生效": "上传接口实时读取；关闭则只入库不解析，需在详情页手动点「解析」。",
                          "选项": "开=上传即解析；关（默认）=上传后手动解析。"}},
                {"key": "review_confidence", "label": "高置信阈值（≥ 为高）", "type": "number", "min": 0, "max": 1, "step": 0.01,
                 "help": {"作用": "OCR 置信度 ≥ 此值判为「高置信」（绿）。",
                          "生效": "结果归一化时实时读取，决定三档分色与统计；须大于 min_confidence。",
                          "选项": "0~1，默认 0.9；调高则高置信门槛更严。"}},
                {"key": "min_confidence", "label": "复核下限（< 为低置信）", "type": "number", "min": 0, "max": 1, "step": 0.01,
                 "help": {"作用": "置信度 < 此值判「低置信」（红），介于两阈值之间判「需复核」（黄）。",
                          "生效": "与 review_confidence 一同实时生效；须小于 review_confidence。",
                          "选项": "0~1，默认 0.7；调高则更多行落入需复核/低置信。"}},
            ],
        },
        {
            "key": "display", "label": "显示与配色",
            "fields": [
                {"key": "show_contract_no", "label": "合同号区域框", "type": "bool",
                 "help": {"作用": "合同页图上标出合同号所在区域。",
                          "生效": "前端实时读取，默认开。", "选项": "开/关。"}},
                {"key": "show_contract_table", "label": "合同明细表格框", "type": "bool",
                 "help": {"作用": "合同页图上标出明细表格区域。",
                          "生效": "前端实时读取，默认开。", "选项": "开/关。"}},
                {"key": "show_layout", "label": "版面区域框", "type": "bool",
                 "help": {"作用": "叠加版面检测区域框（类别+score）。",
                          "生效": "前端实时读取，默认关。", "选项": "开/关。"}},
                {"key": "show_ocr", "label": "OCR 文本框", "type": "bool",
                 "help": {"作用": "叠加 OCR 文本框（按置信度三档着色）。",
                          "生效": "前端实时读取，默认关。", "选项": "开/关。"}},
                {"key": "default_zoom", "label": "页面默认缩放级别（%）", "type": "number", "min": 20, "max": 400, "step": 5,
                 "help": {"作用": "页图区域打开时的初始缩放百分比。",
                          "生效": "下次打开页图时作为初始缩放；仍可用工具栏 +/- 与适应窗口调整。",
                          "选项": "20~400，默认 60（即 60%）。"}},
                {"key": "colors", "label": "区域与匹配配色", "type": "colors", "options": COLOR_FIELDS,
                 "help": {"作用": "自定义各区域框选与校验匹配的颜色。",
                          "生效": "保存后经 CSS 变量全局实时生效；每项可单独还原默认。",
                          "选项": "默认即当前配色方案；点各项「还原」恢复该项默认色。"}},
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
        {
            "key": "llm", "label": "LLM 字段映射（API 端点接入）",
            "fields": [
                {"key": "enabled", "label": "启用 LLM 表头→业务字段映射阶段", "type": "bool",
                 "help": {"作用": "合同解析流水线在提取后、校验前新增 llm_map 阶段，经 API 端点把 varied 中文表头识别为配置的业务英文字段。",
                          "生效": "开启时纳入解析前全模型可用性门控（端点须可达）；关闭则跳过该阶段且不门控 LLM。",
                          "选项": "开（默认）=自动映射并门控；关=不映射、解析不受 LLM 影响。"}},
                {"key": "base_url", "label": "API 端点地址（OpenAI 兼容）", "type": "text",
                 "help": {"作用": "LLM 服务的 OpenAI 兼容基址，后端以客户端方式调用，不自行拉起模型。",
                          "生效": "保存后实时生效；默认本地 http://127.0.0.1:9931（双击 llm-server.cmd 手动启动）。可填任意远程/本地端点。",
                          "选项": "默认 http://127.0.0.1:9931；远程如 https://host/v1 的基址（不含 /chat/completions）。"}},
                {"key": "model", "label": "模型名/别名（端点上）", "type": "text",
                 "help": {"作用": "调用端点时传入的 model 名称，须与端点暴露的模型一致。",
                          "生效": "保存后实时生效；可用性检测会核对该模型是否在端点 /v1/models 列表中。",
                          "选项": "默认 spark-x2.6（llm-server.cmd 的 --alias）；按所接端点实际模型名填写。"}},
                {"key": "api_key", "label": "API Key（可选，Bearer）", "type": "text",
                 "help": {"作用": "端点需要鉴权时填入，作为 Authorization: Bearer 头。",
                          "生效": "保存后实时生效；本地 llama serve 默认无需 key，留空即可。",
                          "选项": "空=不鉴权；远程服务按其所给 key 填写。"}},
                {"key": "timeout", "label": "请求超时（秒）", "type": "number", "min": 5, "max": 600, "step": 5,
                 "help": {"作用": "单次端点请求（可用性检测/推理）的超时上限。",
                          "生效": "下次调用读取；超时则该阶段优雅跳过并留痕。",
                          "选项": "5~600，默认 90。"}},
                {"key": "system_prompt", "label": "前置提示词（System Prompt）", "type": "textarea", "rows": 10,
                 "default": DEFAULT_SYSTEM_PROMPT,
                 "help": {"作用": "LLM 表头映射的前置系统提示词，锁定任务边界/多对一/严格 JSON 输出等规则。",
                          "生效": "保存后下次映射实时读取；留空则回退代码内最优默认。动态的目标字段别名与表头由流水线自动追加。",
                          "选项": "默认已固化一份最优提示词；可编辑覆盖，点「还原默认」恢复最优值。"}},
            ],
        },
    ]
}