"""LLM 字段映射：以 OpenAI 兼容 API 端点客户端方式接入（不自行拉起模型）。

接入方式：
- config.llm.base_url 指向任意 OpenAI 兼容端点，默认本地 http://127.0.0.1:9931。
- 项目启动**不**拉起模型服务；本地模型由用户双击 llm-server.cmd 手动启动（GPU/CPU 由该脚本探测），
  或在设置填写远程/第三方端点 + model + api_key。后端只负责调用与可用性检测。
- 解析前由 jobs.preflight_models 同步门控：LLM 启用时端点须可达且暴露所配模型，否则拒绝解析。

职责分离不变：LLM 只把 varied 中文表头识别到配置的业务字段（小输出，方向归一化 + 别名兜底）；
值的键名重写由 fieldmap.transform 确定性完成，跨页 200+ 明细不丢行不改值。
"""
import json
import re
import threading

import requests

import config as cfgmod
import fieldmap

_lock = threading.RLock()


class LLMError(RuntimeError):
    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        self.hint = hint


def _cfg() -> dict:
    return cfgmod.load_config().get("llm", {})


def _base() -> str:
    return (_cfg().get("base_url") or "").strip().rstrip("/")


def _model() -> str:
    return (_cfg().get("model") or "").strip()


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    key = (_cfg().get("api_key") or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def availability(timeout=None) -> dict:
    """检测端点可用性：可达 + 暴露所配模型。LLM 未启用时 required=False、available=True（不门控）。"""
    c = _cfg()
    enabled = bool(c.get("enabled", True))
    base, model = _base(), _model()
    to = float(timeout if timeout is not None else c.get("timeout", 90))
    probe_to = min(to, 10)
    info = {"required": enabled, "enabled": enabled, "endpoint": base, "model": model,
            "available": False, "reachable": False, "modelPresent": None, "models": [], "reason": None}
    if not enabled:
        info.update(available=True, reason="LLM 映射未启用（不纳入解析门控）")
        return info
    if not base:
        info.update(reason="未配置 llm.base_url")
        return info
    # 优先 /v1/models 核对模型名；不可用时退回 /health 判可达
    try:
        r = requests.get(base + "/v1/models", headers=_headers(), timeout=probe_to)
        if r.ok:
            j = r.json()
            ids = [m.get("id") for m in j.get("data", []) if isinstance(m, dict)]
            ids += [m.get("name") for m in j.get("models", []) if isinstance(m, dict)]
            ids = [i for i in ids if i]
            info.update(reachable=True, models=ids)
            if ids:
                present = model in ids
                info.update(modelPresent=present, available=present,
                            reason=None if present else f"端点未暴露模型 {model}（现有：{', '.join(ids[:8])}）")
            else:
                info.update(available=True, reason="端点可达（未提供模型列表，跳过模型名核对）")
            return info
    except Exception:
        pass
    try:
        r = requests.get(base + "/health", headers=_headers(), timeout=probe_to)
        if r.ok:
            info.update(reachable=True, available=True, reason="端点 /health 可达")
            return info
        info.update(reason=f"端点返回 HTTP {r.status_code}")
    except Exception as e:
        info.update(reason=f"端点不可达：{str(e)[:160]}（先双击 llm-server.cmd 启动本地模型，或检查 base_url）")
    return info


def chat(messages: list, max_tokens: int = 512, temperature: float = 0.0) -> str:
    """调用端点 /v1/chat/completions。带 enable_thinking=false 抑制本地模型思考输出；
    若端点不认识该参数（400），自动去掉重试，兼容通用 OpenAI 端点。"""
    base = _base()
    if not base:
        raise LLMError("LLM_UNREACHABLE", "未配置 llm.base_url", "在设置填写 LLM API 端点")
    body = {"model": _model(), "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False}}
    to = float(_cfg().get("timeout", 90))
    try:
        r = requests.post(base + "/v1/chat/completions", json=body, headers=_headers(), timeout=to)
        if r.status_code == 400 and "chat_template_kwargs" in body:
            body.pop("chat_template_kwargs", None)
            r = requests.post(base + "/v1/chat/completions", json=body, headers=_headers(), timeout=to)
    except Exception as e:
        raise LLMError("LLM_UNREACHABLE", f"调用 LLM 端点失败：{str(e)[:200]}",
                       "先双击 llm-server.cmd 启动本地模型，或在设置检查 base_url/model")
    if not r.ok:
        raise LLMError("LLM_REQUEST_FAILED", f"LLM 端点返回 {r.status_code}：{r.text[:200]}")
    j = r.json()
    return (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def _extract_json(text: str):
    """从模型输出里抠出第一个平衡的 JSON 对象（容忍代码块/前后解释）。"""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None


def _build_prompt(headers: list, mapping: dict) -> list:
    lines = [f"{f['field']}:{','.join(f['aliases']) or f['label']}" for f in mapping["fields"]]
    fields_block = "\n".join(lines)
    # 前置提示词取配置值，留空回退代码内最优默认；动态的目标字段别名块与实际表头追加在 user 消息
    system = (_cfg().get("system_prompt") or cfgmod.DEFAULT_SYSTEM_PROMPT).strip()
    user = (f"目标业务字段(缩写:别名):\n{fields_block}\n\n"
            f"实际表头:{json.dumps(headers, ensure_ascii=False)}\n输出JSON:")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def recognize_headers(headers: list, mapping: dict) -> dict:
    """LLM 识别 {表头: 字段}，做方向归一化 + 别名兜底。返回 header_map。"""
    headers = [h for h in headers if str(h).strip()]
    if not headers:
        return {}
    fields_set = {f["field"] for f in mapping["fields"]}
    headers_set = set(headers)
    obj = _extract_json(chat(_build_prompt(headers, mapping), max_tokens=600))
    hm = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v is None:
                continue
            k, v = str(k).strip(), str(v).strip()
            if k in headers_set and v in fields_set:
                hm[k] = v
            elif k in fields_set and v in headers_set:   # 模型输出了反方向
                hm[v] = k
    fallback = fieldmap.alias_match(headers, mapping)
    for h in headers:
        if h not in hm and h in fallback:
            hm[h] = fallback[h]
    return hm


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _to_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _NUM_RE.search(str(v).replace(",", "").replace("，", ""))
    return float(m.group()) if m else None


# 不规则表格结构理解输出的业务字段 → 内部键/canonical 中文表头（与 table_to_entries 形状一致，下游复用）
_TABLE_FIELDS = [
    ("sortOrder", "no", "序号"), ("itemName", "name", "品名"), ("spec", "spec", "规格"),
    ("unit", "unit", "单位"), ("quantity", "qty", "数量"), ("unitPrice", "price", "单价"),
    ("amount", "amount", "金额"),
]


def understand_table(html: str, cells=None, mapping: dict = None) -> dict:
    """LLM 表格结构理解兜底：启发式 table_to_entries 解析不出（键值对/转置/复杂合并）时，
    把表格 HTML 交端点（建议 4B）理解结构，抽取合同号与明细，返回与 table_to_entries 同形状的结果
    （headers/entries/totalRow），entries 带内部键 + canonical 中文 cells，供 llm_map/verify 链路复用。
    行坐标 rowBoxNorm 在 irregular 几何下难以可靠回映，置 None（前端跳转回退估算）。"""
    if not (html or "").strip():
        return {"headers": [], "entries": [], "totalRow": None, "method": "llm-table"}
    mapping = mapping or fieldmap.load_mapping()
    system = (_cfg().get("table_prompt") or cfgmod.DEFAULT_TABLE_EXTRACT_PROMPT).strip()
    fields_block = "\n".join(f"{f['field']}:{','.join(f['aliases']) or f['label']}" for f in mapping["fields"])
    user = (f"目标业务字段(缩写:别名):\n{fields_block}\n\n"
            f"表格HTML:\n{html}\n\n输出JSON:")
    obj = _extract_json(chat([{"role": "system", "content": system},
                              {"role": "user", "content": user}], max_tokens=2000))
    headers = [c[2] for c in _TABLE_FIELDS]
    if not isinstance(obj, dict):
        return {"headers": headers, "entries": [], "totalRow": None, "method": "llm-table"}
    entries = []
    for it in obj.get("items", []):
        if not isinstance(it, dict):
            continue
        name = it.get("itemName")
        if not name or not str(name).strip():
            continue
        row = {"rowBoxNorm": None}
        cells_dict = {}
        for biz, internal, label in _TABLE_FIELDS:
            raw = it.get(biz)
            text = "" if raw is None else str(raw).strip()
            cells_dict[label] = text
            if internal in ("qty", "price", "amount"):
                row[internal] = _to_num(raw)
                row[internal + "Text"] = text or None
            else:
                row[internal] = text or None
        row["name"] = str(name).strip()
        row["cells"] = {k: v for k, v in cells_dict.items() if v}
        entries.append(row)
    total_amt = _to_num(obj.get("totalAmount"))
    total_row = {"text": "合计", "amount": total_amt} if total_amt is not None else None
    return {"headers": headers, "entries": entries, "totalRow": total_row,
            "contractNo": obj.get("contractNo"), "method": "llm-table"}


def _all_headers(extracted: dict) -> list:
    seen, out = set(), []
    for t in (extracted or {}).get("tables", []):
        for h in t.get("headers") or []:
            h = str(h).strip()
            if h and h not in seen:
                seen.add(h)
                out.append(h)
    return out


def run_mapping(extracted: dict, contract_id=None) -> dict:
    """流水线节点：输入上一步 extracted json，输出业务字段名新 json（经 API 端点）。
    未启用/端点不可用时优雅跳过（status=skipped + 原因）。解析前门控已保证启用时端点可用。"""
    c = _cfg()
    mapping = fieldmap.load_mapping()
    headers = _all_headers(extracted)
    base = {"engine": _model(), "endpoint": _base(), "mappedAt": _now(), "fields": mapping["fields"]}
    if not c.get("enabled", True):
        return {**base, "status": "skipped", "reason": "LLM 映射未在设置中启用",
                "headerMap": {}, "entries": [], "entryCount": 0,
                "contractId": contract_id, "contractNo": _no(extracted)}
    if not headers:
        return {**base, "status": "ok", "method": "none",
                "headerMap": {}, "entries": [], "entryCount": 0,
                "contractId": contract_id, "contractNo": _no(extracted),
                "reason": "无明细表头可映射"}
    try:
        hm = recognize_headers(headers, mapping)
        result = fieldmap.transform(extracted, hm, mapping, contract_id)
        result.update({**base, "status": "ok", "method": "llm"})
        return result
    except LLMError as e:
        return {**base, "status": "skipped", "reason": f"{e.code}: {e}",
                "hint": e.hint, "headerMap": {}, "entries": [], "entryCount": 0,
                "contractId": contract_id, "contractNo": _no(extracted)}


def _no(extracted):
    return ((extracted or {}).get("contractNo") or {}).get("number")


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def status() -> dict:
    av = availability()
    return {
        "enabled": bool(_cfg().get("enabled", True)),
        "endpoint": _base(), "model": _model(),
        "apiKeySet": bool((_cfg().get("api_key") or "").strip()),
        "availability": av,
        "available": av["available"], "reachable": av["reachable"],
        "modelPresent": av["modelPresent"], "reason": av["reason"],
    }