# -*- coding: utf-8 -*-
"""真起本地离线 LLM，实测「表头→业务字段」识别转换的准确率与耗时，并端到端真解析
跨页+部分存在合同 PDF。结果落盘 doc/llm-benchmark-results.json 供分析报告引用。

Part A：表头识别准确率/耗时电池（标准/物料/货物/多对一/部分缺失/OCR空格噪声 6 组），
        真起 llama serve（GPU 优先），逐组测 latency 与 header→field 命中率，并采样 token 用量。
Part B：真上传跨页+部分存在 PDF（HT-2026-001，后端存在）→ OCR → LLM 映射 → 后端查询校验，
        测端到端耗时、跨页提取行数、映射字段、部分匹配（matched vs 数据源无此行）。

用法（venv，后端 8390 + 数据源 8081 需在线）：
  .venv\\Scripts\\python.exe scripts\\llm_benchmark.py --base http://127.0.0.1:8390
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "scripts"))
import config as cfgmod
import fieldmap
import llm

DOC = ROOT / "doc"

# 每组：name / 实际表头 / 期望 header→field（多对一：品名与产品名称都→itemName）
CASES = [
    ("标准表头", ["序号", "品名", "规格型号", "单位", "数量", "单价(元)", "金额(元)"],
     {"序号": "sortOrder", "品名": "itemName", "规格型号": "spec", "单位": "unit", "数量": "quantity", "单价(元)": "unitPrice", "金额(元)": "amount"}),
    ("物料表头", ["项次", "物料名称", "规格", "计量单位", "采购数量", "含税单价", "含税金额"],
     {"项次": "sortOrder", "物料名称": "itemName", "规格": "spec", "计量单位": "unit", "采购数量": "quantity", "含税单价": "unitPrice", "含税金额": "amount"}),
    ("货物表头", ["行号", "货物名称", "型号", "单位", "数目", "单价", "总价"],
     {"行号": "sortOrder", "货物名称": "itemName", "型号": "spec", "单位": "unit", "数目": "quantity", "单价": "unitPrice", "总价": "amount"}),
    ("多对一同义列", ["序号", "品名", "产品名称", "数量"],
     {"序号": "sortOrder", "品名": "itemName", "产品名称": "itemName", "数量": "quantity"}),
    ("部分缺失表头", ["品名", "数量", "金额"],
     {"品名": "itemName", "数量": "quantity", "金额": "amount"}),
    ("OCR空格噪声", ["品 名", "数 量", "单 价", "金 额"],
     {"品 名": "itemName", "数 量": "quantity", "单 价": "unitPrice", "金 额": "amount"}),
]


def part_a(base, startup):
    m = fieldmap.load_mapping()
    av = llm.availability()
    rows = []
    total_headers = total_correct = 0
    for name, headers, expected in CASES:
        t0 = time.time()
        hm = llm.recognize_headers(headers, m)
        dt = time.time() - t0
        correct = sum(1 for h in headers if hm.get(h) == expected[h])
        total_headers += len(headers)
        total_correct += correct
        rows.append({"case": name, "headers": headers, "expected": expected, "got": hm,
                     "correct": correct, "total": len(headers),
                     "accuracy": round(correct / len(headers), 4), "latencyMs": round(dt * 1000, 1)})
    # 采样一次原始 token 用量
    import requests
    usage = None
    try:
        r = requests.post(base + "/v1/chat/completions", timeout=60, json={
            "model": "spark-x2.6", "temperature": 0, "max_tokens": 300,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": llm._build_prompt(CASES[0][1], m)})
        usage = r.json().get("usage")
    except Exception as e:
        usage = {"error": str(e)[:120]}
    return {"availability": av, "endpoint": base, "serverStartupMs": round(startup * 1000, 1),
            "overallAccuracy": round(total_correct / total_headers, 4),
            "correctHeaders": total_correct, "totalHeaders": total_headers,
            "sampleUsage": usage, "cases": rows}


def part_b(base_url):
    import requests
    import make_crosspage_demo as cp
    pdf = cp.make_pdf()
    t0 = time.time()
    with open(pdf, "rb") as f:
        up = requests.post(base_url + "/api/contracts/upload",
                           files={"file": (pdf.name, f, "application/pdf")}, timeout=60).json()
    cid = up["id"]
    requests.post(base_url + f"/api/contracts/{cid}/parse", json={}, timeout=10)
    job = None
    for _ in range(240):
        items = requests.get(base_url + "/api/jobs", params={"refId": cid}, timeout=10).json()["items"]
        if items and items[0]["status"] in ("done", "failed"):
            job = items[0]
            break
        time.sleep(2)
    e2e = time.time() - t0
    if not job or job["status"] != "done":
        return {"contractId": cid, "error": (job or {}).get("error"), "stagePath": (job or {}).get("stagePath")}
    res = requests.get(base_url + f"/api/contracts/{cid}/result", timeout=10).json()
    ex = res.get("extracted", {})
    mapped = res.get("mapped", {})
    report = res.get("report", {})
    tables = ex.get("tables", [])
    entries = [e for t in tables for e in t.get("entries", [])]
    pages_with_table = sorted({t.get("page") for t in tables})
    cmp_rows = report.get("itemComparison", [])
    matched = sum(1 for r in cmp_rows if r.get("matched"))
    unmatched_ocr = sum(1 for r in cmp_rows if r.get("source") is None and r.get("ocr"))
    # 阶段耗时（从 job logs 的 t 秒推算 llm_map 与总耗时）
    logs = job.get("logs", [])
    llm_logs = [l["t"] for l in logs if l.get("stage") == "llm_map"]
    llm_stage_s = round(max(llm_logs) - min(llm_logs), 3) if len(llm_logs) >= 2 else None
    return {
        "contractId": cid, "contractNo": (ex.get("contractNo") or {}).get("number"),
        "pdf": pdf.name, "pdfBytes": pdf.stat().st_size,
        "pageCount": len(res.get("pages", [])), "stagePath": job.get("stagePath"),
        "crossPage": {"pagesWithTable": pages_with_table, "tableBlocks": len(tables),
                      "totalEntries": len(entries),
                      "entriesPerPage": {str(p): sum(1 for t in tables if t.get("page") == p for _ in t.get("entries", [])) for p in pages_with_table}},
        "mapped": {"status": mapped.get("status"), "device": mapped.get("device"),
                   "method": mapped.get("method"), "entryCount": mapped.get("entryCount"),
                   "fields": [f["field"] for f in mapped.get("fields", [])],
                   "headerMap": mapped.get("headerMap"),
                   "firstEntry": (mapped.get("entries") or [None])[0]},
        "verify": {"status": report.get("status"), "matchSource": report.get("matchSource"),
                   "itemComparisonRows": len(cmp_rows), "matchedRows": matched,
                   "ocrOnlyRows_notInSource": unmatched_ocr,
                   "checks": [{"key": c["key"], "ok": c["ok"], "detail": c["detail"]} for c in report.get("checks", [])]},
        "timing": {"endToEndMs": round(e2e * 1000, 1), "llmMapStageSeconds": llm_stage_s,
                   "jobTotalSeconds": round((job.get("finishedAt") or 0) - (job.get("createdAt") or 0), 3)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8390")
    ap.add_argument("--skip-b", action="store_true")
    args = ap.parse_args()
    DOC.mkdir(parents=True, exist_ok=True)
    from llm_local import LocalLLM, MODEL
    local = LocalLLM(port=9931)
    t_start = time.time()
    base = local.start(timeout=90)
    startup = time.time() - t_start
    try:
        print("== Part A: 真起 LLM 表头识别准确率/耗时 ==")
        a = part_a(base, startup)
        print(f"  endpoint={a['endpoint']} startup={a['serverStartupMs']}ms overallAccuracy={a['overallAccuracy']} ({a['correctHeaders']}/{a['totalHeaders']})")
        for c in a["cases"]:
            print(f"  [{c['case']}] acc={c['accuracy']} latency={c['latencyMs']}ms got={c['got']}")
        b = None
        if not args.skip_b:
            print("== Part B: 跨页+部分存在 PDF 端到端真解析 ==")
            b = part_b(args.base)
            print(json.dumps(b, ensure_ascii=False, indent=2))
        out = {"generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
               "model": str(MODEL), "config": cfgmod.load_config().get("llm"),
               "partA": a, "partB": b}
        (DOC / "llm-benchmark-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[bench] 结果落盘 {DOC / 'llm-benchmark-results.json'}")
    finally:
        local.stop()


if __name__ == "__main__":
    main()