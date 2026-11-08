"""对照 Spring Boot 合同数据源校验 OCR 提取结果。

数据源契约（contract-source 工程）：
  GET {source_url}/api/contracts/{contractNo}
    → 200 {contract:{contractNo,title,partyA,partyB,totalAmount,...}, items:[{itemName,spec,unit,quantity,unitPrice,amount}]}
    → 404 合同号不存在
"""
import re
import urllib.error
import urllib.request
import json

import config as cfgmod


class SourceError(RuntimeError):
    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        self.hint = hint


def probe_source(base_url: str, timeout: float = 5.0) -> dict:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/health", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
            return {"reachable": True, "status": r.status, "body": body}
    except Exception as e:
        return {"reachable": False, "error": str(e)[:200],
                "hint": "先启动 contract-source（run.cmd，端口 8081）"}


def fetch_contract(base_url: str, contract_no: str, timeout: float = 10.0):
    url = f"{base_url.rstrip('/')}/api/contracts/{urllib.parse.quote(contract_no)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "not_found"
        raise SourceError("SOURCE_HTTP_ERROR", f"数据源返回 HTTP {e.code}")
    except Exception as e:
        raise SourceError("SOURCE_UNREACHABLE", f"合同数据源不可达：{str(e)[:200]}",
                          "先启动 contract-source（run.cmd，端口 8081）")


import urllib.parse  # noqa: E402


def _norm_text(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def _name_sim(a, b):
    """粗相似度：包含关系给足权重，其余按字符集合 Jaccard。只用于提示，不替代人工复核。"""
    a, b = _norm_text(a), _norm_text(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / max(1, len(sa | sb))


def verify(extracted: dict, source_url: str) -> dict:
    """extracted: {contractNo:{number,...}|None, tables:[{entries,totalRow}], pages...}"""
    cfg = cfgmod.load_config()
    tol = float(cfg["contract"]["amount_tolerance"])
    no_info = extracted.get("contractNo") or {}
    number = no_info.get("number")
    report = {"sourceUrl": source_url, "checks": [], "status": "pending",
              "contractNo": number, "itemComparison": []}

    def check(key, label, ok, detail):
        report["checks"].append({"key": key, "label": label, "ok": bool(ok), "detail": detail})

    if not number:
        report["status"] = "no_number"
        check("contract_no", "合同号提取", False, "未在任何页面识别到合同编号，无法对照数据源")
        return report

    data, err = fetch_contract(source_url, number)
    if err == "not_found":
        report["status"] = "not_found"
        check("contract_no", "合同号存在于数据源", False, f"数据源中不存在合同号 {number}")
        return report
    check("contract_no", "合同号存在于数据源", True, f"数据源命中合同 {number}")
    contract = data.get("contract") or {}
    items = data.get("items") or []
    report["sourceContract"] = contract

    ocr_entries = []
    for t in extracted.get("tables", []):
        for e in t.get("entries", []):
            e = dict(e)
            e["page"] = t.get("page")
            ocr_entries.append(e)

    if not ocr_entries:
        check("items_found", "明细条目提取", False, "未从表格区域提取到明细条目")
    else:
        check("items_found", "明细条目提取", True, f"提取到 {len(ocr_entries)} 条明细")

    check("item_count", "明细行数一致", len(ocr_entries) == len(items),
          f"文件 {len(ocr_entries)} 行 / 数据源 {len(items)} 行")

    used = set()
    mismatch = 0
    for src in items:
        best, best_sim = None, 0.0
        for i, e in enumerate(ocr_entries):
            if i in used:
                continue
            sim = _name_sim(src.get("itemName"), e.get("name"))
            if sim > best_sim:
                best, best_sim = i, sim
        row = {"source": src, "matched": False, "fields": []}
        if best is None or best_sim < 0.5:
            row["fields"].append({"field": "name", "ok": False,
                                  "source": src.get("itemName"), "ocr": None,
                                  "detail": "文件中未找到对应品名"})
            mismatch += 1
            report["itemComparison"].append(row)
            continue
        used.add(best)
        e = ocr_entries[best]
        row.update(matched=True, ocr=e, nameSim=round(best_sim, 3))
        row["fields"].append({"field": "name", "ok": best_sim >= 0.8,
                              "source": src.get("itemName"), "ocr": e.get("name"),
                              "detail": f"品名相似度 {best_sim:.2f}"})
        for fld, skey, okey in [("quantity", "quantity", "qty"),
                                ("unitPrice", "unitPrice", "price"),
                                ("amount", "amount", "amount")]:
            sv, ov = src.get(skey), e.get(okey)
            if sv is None and ov is None:
                continue
            ok = sv is not None and ov is not None and abs(float(sv) - float(ov)) <= tol
            row["fields"].append({"field": fld, "ok": ok, "source": sv, "ocr": ov,
                                  "detail": "一致" if ok else f"不一致（容差 {tol}）"})
            if not ok:
                mismatch += 1
        if not all(f["ok"] for f in row["fields"]):
            mismatch += 0
        report["itemComparison"].append(row)

    for i, e in enumerate(ocr_entries):
        if i not in used:
            report["itemComparison"].append({
                "source": None, "ocr": e, "matched": False,
                "fields": [{"field": "name", "ok": False, "source": None,
                            "ocr": e.get("name"), "detail": "数据源无此明细行"}]})
            mismatch += 1

    total_src = contract.get("totalAmount")
    ocr_total = None
    for t in extracted.get("tables", []):
        if t.get("totalRow") and t["totalRow"].get("amount") is not None:
            ocr_total = t["totalRow"]["amount"]
    if total_src is not None:
        ok = ocr_total is not None and abs(float(total_src) - ocr_total) <= tol
        check("total_amount", "合同总金额一致", ok,
              f"文件 {ocr_total} / 数据源 {total_src}")
        if not ok:
            mismatch += 1

    failed = [c for c in report["checks"] if not c["ok"]]
    field_bad = any(not f["ok"] for r in report["itemComparison"] for f in r["fields"])
    if not failed and not field_bad:
        report["status"] = "matched"
    else:
        report["status"] = "mismatch"
    report["mismatchCount"] = mismatch + len(failed)
    return report