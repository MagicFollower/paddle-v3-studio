"""字段映射配置：中文表头 → 真实业务字段英文缩写。

独立存储于 data/field_mapping.json（与 config.json 分开），支持界面逐条编辑与导入导出。
映射本身只声明「目标业务字段 + 其中文表头别名」；把一份合同里 varied 的实际表头识别到
这些字段由 llm.py 用本地大模型完成，识别结果再交给本模块的 transform 做确定性键名重写
（值原样保留，不改数、不丢行），保证 200+ 明细可复现。
"""
import json
import re
import threading

from config import DATA

MAPPING_PATH = DATA / "field_mapping.json"
_lock = threading.RLock()

# 默认业务字段：与后端合同查询接口（contract-source GET /api/contracts/{contractNo}）的
# 响应参数 items[] 字段名逐字对齐（sortOrder/itemName/spec/unit/quantity/unitPrice/amount），
# 查询参数为 contractNo（映射产物的 contractNo 即用它）。这样 LLM 转换出的新 json 能直接
# 匹配后端查询/响应参数。别名供 LLM 识别 varied 中文表头参考，也作无 LLM 时的确定性兜底。
DEFAULT_MAPPING = {
    "version": 1,
    "fields": [
        {"field": "sortOrder", "label": "序号", "aliases": ["序号", "编号", "项次", "行号", "序列号", "排序"]},
        {"field": "itemName", "label": "品名", "aliases": ["名称", "品名", "产品", "货物", "商品", "项目", "物料", "物料名称", "货物名称", "产品名称", "品名规格"]},
        {"field": "spec", "label": "规格", "aliases": ["规格", "型号", "规格型号", "规格/型号"]},
        {"field": "unit", "label": "单位", "aliases": ["单位", "计量单位"]},
        {"field": "quantity", "label": "数量", "aliases": ["数量", "数目", "采购数量", "订单数量"]},
        {"field": "unitPrice", "label": "单价", "aliases": ["单价", "含税单价", "不含税单价", "单价(元)", "单价（元）"]},
        {"field": "amount", "label": "金额", "aliases": ["金额", "总价", "小计", "合计金额", "含税金额", "金额(元)", "金额（元）"]},
    ],
}

_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _clean_aliases(aliases) -> list:
    out, seen = [], set()
    for a in aliases or []:
        s = str(a).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def normalize_mapping(raw: dict) -> dict:
    """规整成 {version, fields:[{field,label,aliases}]}。支持两种输入：
    ①字段中心 fields:[{field,label,aliases}]；②扁平多对一配对 mappings:[{from:中文,to:英文,label}]。
    多个中文字段（from/别名）指向同一英文字段（to/field）时自动归并别名——即多对一，
    重复的 field 行不再报错而是合并，增强不同合同表头的识别覆盖。"""
    merged = {}

    def add(key, label, aliases):
        key = str(key or "").strip()
        if not key:
            return
        slot = merged.setdefault(key, {"field": key, "label": "", "aliases": []})
        if label and not slot["label"]:
            slot["label"] = str(label).strip()
        for a in _clean_aliases(aliases):
            if a not in slot["aliases"]:
                slot["aliases"].append(a)

    for f in (raw or {}).get("fields", []):
        if isinstance(f, dict):
            add(f.get("field"), f.get("label"), f.get("aliases"))
    for p in (raw or {}).get("mappings", []):
        if isinstance(p, dict):
            to = p.get("to") or p.get("english") or p.get("field")
            frm = p.get("from") or p.get("chinese") or p.get("alias")
            add(to, p.get("label"), [frm] if frm else [])
    fields = []
    for slot in merged.values():
        slot["label"] = slot["label"] or slot["field"]
        fields.append(slot)
    return {"version": 1, "fields": fields}


def validate_mapping(raw: dict) -> list:
    if not isinstance(raw, dict) or not (isinstance(raw.get("fields"), list) or isinstance(raw.get("mappings"), list)):
        return ["映射配置需为对象且含 fields 数组或 mappings 配对数组"]
    norm = normalize_mapping(raw)   # 多对一归并后再校验：重复 field 已合并，不报重复
    errs = []
    if not norm["fields"]:
        errs.append("至少配置一个业务字段")
    for f in norm["fields"]:
        key = f["field"]
        if not _FIELD_RE.match(key):
            errs.append(f"字段缩写 {key} 只能以字母开头、含字母数字下划线")
        if not str(f.get("label") or "").strip():
            errs.append(f"字段 {key} 缺少中文标签 label")
    return errs


def load_mapping() -> dict:
    with _lock:
        if MAPPING_PATH.exists():
            try:
                return normalize_mapping(json.loads(MAPPING_PATH.read_text(encoding="utf-8")))
            except Exception:
                pass
        return json.loads(json.dumps(DEFAULT_MAPPING))


def save_mapping(raw: dict) -> dict:
    errs = validate_mapping(raw)
    if errs:
        raise ValueError("; ".join(errs))
    norm = normalize_mapping(raw)
    with _lock:
        DATA.mkdir(parents=True, exist_ok=True)
        MAPPING_PATH.write_text(json.dumps(norm, ensure_ascii=False, indent=2), encoding="utf-8")
    return norm


def reset_mapping() -> dict:
    with _lock:
        MAPPING_PATH.unlink(missing_ok=True)
    return load_mapping()


# ---------- 确定性转换 ----------

def _norm_header(h: str) -> str:
    return re.sub(r"\s+", "", str(h or "")).lower()


def alias_match(headers: list, mapping: dict) -> dict:
    """无 LLM 时的兜底：把实际表头匹配到业务字段，返回 {header: field}。
    精确相等优先；其次包含关系，取命中别名最长者（避免「品名规格」抢走「规格」这类短表头）。"""
    out = {}
    norms = [(f["field"], [_norm_header(a) for a in f["aliases"] if _norm_header(a)])
             for f in mapping["fields"]]
    for h in headers:
        hn = _norm_header(h)
        if not hn:
            continue
        best, best_score = None, (0, 0)
        for field, aliases in norms:
            for a in aliases:
                if a == hn:
                    score = (2, len(a))
                elif a in hn or hn in a:
                    score = (1, len(a))
                else:
                    continue
                if score > best_score:
                    best, best_score = field, score
        if best:
            out[h] = best
    return out


def entry_cells(entry: dict, headers: list) -> dict:
    """取一条明细的「表头→原值」字典。优先用提取阶段保留的 cells（覆盖全部列）；
    旧产物无 cells 时由内部键合成 canonical 中文标签，保证已解析合同也能手动重跑映射。"""
    cells = entry.get("cells")
    if isinstance(cells, dict) and cells:
        return {str(k): ("" if v is None else str(v)) for k, v in cells.items()}
    synth = {
        "序号": entry.get("no"), "品名": entry.get("name"), "规格": entry.get("spec"),
        "单位": entry.get("unit"), "数量": entry.get("qtyText", entry.get("qty")),
        "单价": entry.get("priceText", entry.get("price")), "金额": entry.get("amountText", entry.get("amount")),
    }
    return {k: ("" if v is None else str(v)) for k, v in synth.items() if v not in (None, "")}


def transform(extracted: dict, header_map: dict, mapping: dict, contract_id=None) -> dict:
    """按 LLM 识别出的 {表头: 业务字段} 把明细键名重写为业务英文缩写。值原样 trim 保留。
    保留 page/rowBoxNorm 以便前端可视化与跳转；未识别表头归入 _unmapped 不丢信息。
    旧产物无 cells 时条目键是 canonical 中文标签（品名/规格/单价…），与实际表头文本不同，
    故对单元格键再做一次别名兜底匹配，保证已解析合同手动重跑也能命中业务字段。"""
    fields = mapping["fields"]
    valid_fields = {f["field"] for f in fields}
    tables = (extracted or {}).get("tables", [])
    all_headers, all_keys = [], set()
    for t in tables:
        for h in t.get("headers") or []:
            all_headers.append(h)
        for e in t.get("entries", []):
            all_keys.update(entry_cells(e, t.get("headers") or []).keys())
    alias_fb = alias_match(list(all_keys) + all_headers, mapping)

    def field_for(h):
        f = header_map.get(h) or alias_fb.get(h)
        return f if f in valid_fields else None

    entries, used_fields = [], []
    for t in tables:
        for e in t.get("entries", []):
            cells = entry_cells(e, t.get("headers") or [])
            row, unmapped, conflicts = {}, {}, {}
            for h, val in cells.items():
                fld = field_for(h)
                text = val.strip()
                if fld:
                    # 多对一：多个中文表头命中同一字段时非空优先合并；若出现不同的非空值，
                    # 保留首个非空值并把冲突留痕（_conflicts），避免静默覆盖丢值。
                    if fld not in row or not row[fld]:
                        row[fld] = text
                    elif text and text != row[fld]:
                        conflicts.setdefault(fld, [row[fld]])
                        if text not in conflicts[fld]:
                            conflicts[fld].append(text)
                    if fld not in used_fields:
                        used_fields.append(fld)
                elif h.strip():
                    unmapped[h] = text
            row["page"] = t.get("page")
            row["rowBoxNorm"] = e.get("rowBoxNorm")
            if unmapped:
                row["_unmapped"] = unmapped
            if conflicts:
                row["_conflicts"] = conflicts
            entries.append(row)
    no = (extracted or {}).get("contractNo") or {}
    ordered = [f for f in fields if f["field"] in used_fields] or fields
    return {
        "contractId": contract_id,
        "contractNo": (no.get("number") or "").strip() or None,
        "fields": [{"field": f["field"], "label": f["label"]} for f in ordered],
        "headerMap": header_map,
        "entries": entries,
        "entryCount": len(entries),
    }