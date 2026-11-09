"""端到端判据：自起后端（NO_PORT_FILE=1），真上传、真推理、真校验。

用法：
  .venv\\Scripts\\python.exe scripts\\check_studio.py            # 全套（需模型已就位）
  .venv\\Scripts\\python.exe scripts\\check_studio.py --skip-contract
退出码 = 失败条数（0 = 全绿）。合同段会按需自起 contract-source（8081）。
"""
import argparse
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
PORT = 18390
BASE = f"http://127.0.0.1:{PORT}"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def req(method, path, body=None, form=None, base=None, timeout=30):
    url = (base or BASE) + path
    data = None
    headers = {}
    if form is not None:
        boundary = "----checkboundary123"
        buf = io.BytesIO()
        for k, (fname, content, ctype) in form.items():
            buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
            buf.write(content)
            buf.write(b"\r\n")
        buf.write(f"--{boundary}--\r\n".encode())
        data = buf.getvalue()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            ct = resp.headers.get("content-type", "")
            raw = resp.read()
            return resp.status, ct, (json.loads(raw) if "json" in ct else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, e.headers.get("content-type", ""), json.loads(raw)
        except Exception:
            return e.code, "", raw


def wait_job(ref_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, _, j = req("GET", f"/api/jobs?refId={ref_id}")
        items = j.get("items", [])
        if items:
            job = items[0]
            if job["status"] in ("done", "failed"):
                return job
        time.sleep(2)
    return None


def wait_health(base, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s, _, _ = req("GET", "/api/health", base=base, timeout=3)
            if s == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-contract", action="store_true")
    args = ap.parse_args()

    env = dict(os.environ, PORT=str(PORT), NO_PORT_FILE="1")
    server = subprocess.Popen(
        [str(ROOT / ".venv/Scripts/python.exe"), str(ROOT / "server/app.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    source_proc = None
    local_llm = None
    try:
        if not wait_health(BASE):
            print("FATAL: backend did not come up")
            sys.exit(99)

        # 后端为纯 API 客户端，不自行拉起模型；判据脚本手动起本地 LLM 供预检门控与映射使用
        from llm_local import LocalLLM
        local_llm = LocalLLM(port=9931)
        try:
            local_llm.start(timeout=90)
            print("[llm] local model server up on 9931")
        except Exception as e:
            print(f"[llm] local model unavailable: {e}（LLM 相关判据将跳过/门控判据据此验证）")
            local_llm = None
        req("POST", "/api/config", {"llm": {"enabled": True, "base_url": "http://127.0.0.1:9931", "model": "spark-x2.6"}})

        # ---------- A 静态与契约 ----------
        check("A1 dist/index.html 存在", (ROOT / "dist/index.html").exists())
        s, _, j = req("GET", "/api/overview")
        check("A2 overview 字段齐", s == 200 and all(k in j for k in ("documents", "parsed", "contracts", "jobsRunning")))
        s, _, schema = req("GET", "/api/schema")
        s2, _, cfg = req("GET", "/api/config")
        keys_ok = all(f["key"] in cfg.get(g["key"], {}) for g in schema["groups"] for f in g["fields"])
        check("A3 schema 键与 config 一致", s == 200 and s2 == 200 and keys_ok)
        bad = {"parse": {"min_confidence": 0.95, "review_confidence": 0.9}}
        s, _, _ = req("POST", "/api/config/validate", bad)
        check("A4 非法阈值被 400 拒", s == 400)
        s, _, j = req("GET", "/api/model/status")
        models_present = all(v["present"] for v in j.get("models", {}).values())
        dev = j.get("device", {})
        check("A5 四个模型本地就位", s == 200 and models_present, json.dumps({k: v["present"] for k, v in j.get("models", {}).items()}))
        check("A6 设备信息如实（gpu/cpu+原因）", dev.get("device") in ("gpu", "cpu") and "paddle_version" in dev,
              f"device={dev.get('device')} fallback={dev.get('fallback')}")
        # A7/A8 自动解析开关：A7 查源码 DEFAULTS（免受运行时配置污染），A8 显式置关后验上传不起任务
        sys.path.insert(0, str(ROOT / "server"))
        import config as _cfgmod
        import contract as _ct
        check("A7 自动解析默认关闭", _cfgmod.DEFAULTS["parse"].get("auto_parse_on_upload") is False)
        req("POST", "/api/config", {"parse": {"auto_parse_on_upload": False}})
        img0 = (FIX / "upload-sample.png").read_bytes()
        s, _, j0 = req("POST", "/api/documents", form={"file": ("noauto.png", img0, "image/png")})
        check("A8 关闭时上传不起任务", s == 201 and j0.get("jobId") is None and j0.get("autoParsed") is False, str(j0)[:80])
        req("DELETE", f"/api/documents/{j0.get('id')}")
        # A9/A10 跨页续表沿用上一页列映射（纯单元，无需 GPU/推理）
        _hdr = ('<table><tr><td>序号</td><td>品名</td><td>数量</td><td>金额</td></tr>'
                '<tr><td>1</td><td>甲</td><td>2</td><td>20</td></tr></table>')
        _cont = '<table><tr><td>2</td><td>乙</td><td>3</td><td>30</td></tr></table>'
        _r1 = _ct.table_to_entries(_hdr)
        _carry = {"headers": _r1.get("headers"), "colmap": _r1.get("colmap")}
        _r2 = _ct.table_to_entries(_cont, fallback=_carry)
        _r2n = _ct.table_to_entries(_cont)
        check("A9 续表无表头沿用上一页列映射出明细",
              len(_r1.get("entries", [])) == 1 and len(_r2.get("entries", [])) == 1
              and (_r2.get("entries") or [{}])[0].get("name") == "乙",
              f"p1={len(_r1.get('entries', []))} p2={len(_r2.get('entries', []))}")
        check("A10 无 fallback 时续表 0 条（向后兼容）",
              len(_r2n.get("entries", [])) == 0, f"got={len(_r2n.get('entries', []))}")
        # 后续 B/C 段需要自动解析，临时开启
        req("POST", "/api/config", {"parse": {"auto_parse_on_upload": True}})

        # ---------- B 图片真解析 ----------
        s, _, _ = req("POST", "/api/documents", form={"file": ("evil.txt", b"not an image", "text/plain")})
        check("B1 非图片上传被 400 拒", s == 400)
        img = (FIX / "upload-sample.png").read_bytes()
        s, _, j = req("POST", "/api/documents", form={"file": ("upload-sample.png", img, "image/png")})
        check("B2 真图上传 201 且自动起任务", s == 201 and "jobId" in j, str(j)[:100])
        doc_id = j.get("id")
        s, _, early = req("GET", f"/api/documents/{doc_id}/result")
        check("B3 未解析完成不给结果(409)", s == 409)
        job = wait_job(doc_id)
        check("B4 任务完成且阶段路径真实", job and job["status"] == "done"
              and all(k in job["stagePath"] for k in ("prepare", "predict", "persist")),
              (job or {}).get("stagePath", ""))
        if job and job["status"] == "failed":
            print("JOB ERROR:", job.get("error"))
        s, _, res = req("GET", f"/api/documents/{doc_id}/result")
        layout, ocr = res.get("layout", []), res.get("ocr", [])
        check("B5 版面与 OCR 都有真结果", s == 200 and len(layout) > 0 and len(ocr) > 0,
              f"layout={len(layout)} ocr={len(ocr)}")
        conf_ok = all(o["confidence"] is None or 0 <= o["confidence"] <= 1 for o in ocr)
        tier_ok = True
        for o in ocr:
            c = o["confidence"]
            if c is None:
                tier_ok &= o["tier"] == "none"
            else:
                expect = "high" if c >= cfg["parse"]["review_confidence"] else (
                    "review" if c >= cfg["parse"]["min_confidence"] else "low")
                tier_ok &= o["tier"] == expect
        check("B6 置信度在 0~1 且三档与阈值自洽", conf_ok and tier_ok)
        w, h = res["width"], res["height"]
        geo_ok = True
        for b in layout + [o for o in ocr if o.get("bbox")]:
            x0, y0, x1, y1 = b["bbox"]
            geo_ok &= (0 <= x0 <= x1 <= w + 1 and 0 <= y0 <= y1 <= h + 1)
            nx0, ny0, nx1, ny1 = b["bboxNorm"]
            geo_ok &= abs(nx0 - x0 / w * 1000) < 2 and abs(ny1 - y1 / h * 1000) < 2
        check("B7 框在页内且 0-1000 与像素自洽", geo_ok)
        s, ct, _ = req("GET", f"/api/documents/{doc_id}/image")
        check("B8 解析后图片端点仍是 image/*", s == 200 and ct.startswith("image/"), ct)
        s, _, _ = req("DELETE", f"/api/documents/{doc_id}")
        s2, _, _ = req("GET", f"/api/documents/{doc_id}/result")
        check("B9 删除后产物不残留", s == 200 and s2 in (404, 409))

        if args.skip_contract:
            return finish()

        # ---------- C 合同校验 ----------
        source_base = cfg["contract"]["source_url"]
        try:
            s, _, _ = req("GET", "/api/health", base=source_base, timeout=3)
        except Exception:
            s = 0
        if s != 200:
            jar = ROOT.parent / "contract-source/target/contract-source.jar"
            if not jar.exists():
                check("C0 contract-source jar 存在", False, "先 mvn package")
                return finish()
            source_proc = subprocess.Popen(["java", "-jar", str(jar)],
                                           cwd=str(jar.parent.parent),
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            check("C0 数据源自起并健康", wait_health(source_base, 90))
        else:
            check("C0 数据源在线", True)

        expectations = [
            ("sample-HT-2026-001.docx", "HT-2026-001", "matched", 3),
            ("sample-HT-2026-002-bad.docx", "HT-2026-002", "mismatch", 2),
            ("sample-HT-2026-999.docx", "HT-2026-999", "not_found", 1),
        ]
        first_cid = None
        for fname, expect_no, expect_status, expect_rows in expectations:
            f = FIX / fname
            if not f.exists():
                check(f"C[{fname}] fixture 存在", False, "先跑 scripts/make_fixtures.py")
                continue
            s, _, j = req("POST", "/api/contracts/upload",
                          form={"file": (fname, f.read_bytes(), "application/octet-stream")})
            cid = j.get("id")
            check(f"C1[{fname}] 上传成条目", s == 201 and cid)
            job = wait_job(cid, 900)
            ok_done = job and job["status"] == "done"
            check(f"C2[{fname}] 逐页解析完成", ok_done,
                  str((job or {}).get("error") or (job or {}).get("stagePath")))
            if not ok_done:
                continue
            s, _, payload = req("GET", f"/api/contracts/{cid}/result")
            no = (payload.get("extracted", {}).get("contractNo") or {})
            check(f"C3[{fname}] 合同号提取正确", no.get("number") == expect_no,
                  f"got={no.get('number')} page={no.get('page')}")
            check(f"C4[{fname}] 合同号区域有坐标", bool(no.get("bbox") and no.get("bboxNorm")))
            entries = [e for t in payload["extracted"]["tables"] for e in t["entries"]]
            check(f"C5[{fname}] 明细行数={expect_rows}", len(entries) == expect_rows, f"got={len(entries)}")
            boxed = [e for e in entries if e.get("rowBoxNorm")]
            check(f"C5b[{fname}] 明细行定位坐标已生成", len(entries) > 0 and len(boxed) == len(entries),
                  f"boxed={len(boxed)}/{len(entries)}")
            check(f"C5c[{fname}] 明细保留表头→原值 cells（供 LLM 映射）",
                  len(entries) > 0 and all(isinstance(e.get("cells"), dict) and e["cells"] for e in entries),
                  f"withCells={sum(1 for e in entries if e.get('cells'))}/{len(entries)}")
            check(f"C6[{fname}] 表格区域有坐标", all(t.get("bbox") for t in payload["extracted"]["tables"]))
            rep = payload.get("report", {})
            check(f"C7[{fname}] 校验结局={expect_status}", rep.get("status") == expect_status,
                  f"got={rep.get('status')}")
            s, ct, _ = req("GET", f"/api/contracts/{cid}/pages/1/image")
            check(f"C8[{fname}] 页图端点 image/png", s == 200 and ct == "image/png")
            if first_cid is None:
                first_cid = cid

        if first_cid:
            s, _, rep = req("POST", f"/api/contracts/{first_cid}/reverify", {})
            check("C9 重新校验接口可用", s == 200 and rep.get("status") == "matched")
            pdf = FIX / "sample-HT-2026-001.pdf"
            if pdf.exists():
                s, _, j = req("POST", "/api/contracts/upload",
                              form={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
                cid = j.get("id")
                job = wait_job(cid, 900)
                ok = job and job["status"] == "done"
                rep2 = {}
                if ok:
                    _, _, p = req("GET", f"/api/contracts/{cid}/result")
                    rep2 = p.get("report", {})
                check("C10 PDF 合同同样走通并 matched", ok and rep2.get("status") == "matched",
                      f"status={rep2.get('status')}")

        # ---------- D 文件条目查询 ----------
        s, _, e = req("GET", "/api/entries?page=1&pageSize=15")
        check("D1 entries 默认分页", s == 200 and e["pageSize"] == 15 and len(e["items"]) <= 15 and "total" in e)
        total = e["total"]
        s, _, e2 = req("GET", "/api/entries?page=1&pageSize=10")
        check("D2 每页条数切换", e2["pageSize"] == 10 and len(e2["items"]) <= 10)
        s, _, em = req("GET", "/api/entries?verify=matched")
        check("D3 校验状态过滤", all(x["verifyStatus"] == "matched" for x in em["items"]) and em["total"] <= total)
        s, _, eq = req("GET", "/api/entries?q=HT-2026-001")
        check("D4 合同号模糊查询", bool(eq["items"]) and all("HT-2026-001" in (x["contractNo"] or "") for x in eq["items"]))
        s, _, ep = req("GET", "/api/entries?parsed=true")
        check("D5 已解析过滤", all(x["parsed"] for x in ep["items"]))
        s, _, big = req("GET", "/api/entries?page=1&pageSize=200")
        check("D6 大页返回全部", len(big["items"]) == big["total"])
        check("D7 条目字段齐全", all(all(k in x for k in ("id", "name", "size", "ext", "pageCount", "uploadedAt", "type")) for x in big["items"]))

        # ---------- E LLM 字段映射 ----------
        import fieldmap as _fm
        import llm as _llm
        s, _, fm = req("GET", "/api/field-mapping")
        check("E1 映射配置含 field/label/aliases", s == 200 and bool(fm.get("fields"))
              and all(all(k in f for k in ("field", "label", "aliases")) for f in fm["fields"]))
        s, _, _ = req("POST", "/api/field-mapping/validate", {"fields": [{"field": "1bad", "label": ""}]})
        check("E2 非法映射被 400 拒", s == 400)
        custom = {"fields": [{"field": "matName", "label": "品名", "aliases": ["名称", "品名"]},
                             {"field": "qty", "label": "数量", "aliases": ["数量"]}]}
        s, _, saved = req("POST", "/api/field-mapping", custom)
        s2, _, got = req("GET", "/api/field-mapping")
        check("E3 映射保存后读回一致", s == 200 and s2 == 200 and [f["field"] for f in got["fields"]] == ["matName", "qty"])
        s, _, dft = req("POST", "/api/field-mapping/reset", {})
        check("E4 恢复默认映射", s == 200 and len(dft["fields"]) >= 5)
        # 确定性转换：别名精确优先（「规格」不被 matName 的「品名规格」抢走），值原样不改
        _m = _fm.load_mapping()
        _hm = _fm.alias_match(["序号", "品名", "规格", "数量", "单价", "金额"], _m)
        check("E5 别名精确优先匹配（对齐后端字段名）", _hm.get("规格") == "spec" and _hm.get("品名") == "itemName" and _hm.get("金额") == "amount",
              json.dumps(_hm, ensure_ascii=False))
        _ex = {"contractNo": {"number": "HT-X"}, "tables": [{"page": 1, "headers": ["品名", "规格", "数量"],
               "entries": [{"name": "甲", "cells": {"品名": "甲", "规格": "Q235", "数量": " 10 "}, "rowBoxNorm": [1, 2, 3, 4]}]}]}
        _out = _fm.transform(_ex, _hm, _m, "ct-x")
        _e0 = (_out.get("entries") or [{}])[0]
        check("E6 转换重写为后端字段名且值 trim 不改数", _e0.get("itemName") == "甲" and _e0.get("spec") == "Q235"
              and _e0.get("quantity") == "10" and _e0.get("rowBoxNorm") == [1, 2, 3, 4], json.dumps(_e0, ensure_ascii=False))
        # 模型输出方向归一化（field→header 与 header→field 两种朝向都能抠出）
        _j1 = _llm._extract_json('前言 {"品名":"matName","数量":"qty"} 后语')
        _j2 = _llm._extract_json('```json\n{"matName":"品名"}\n```')
        check("E7 JSON 抽取容忍代码块/前后缀", _j1 == {"品名": "matName", "数量": "qty"} and _j2 == {"matName": "品名"})
        # 多对一：扁平配对归并 / 重复 field 行归并 / 多列同字段取值合并 / 冲突留痕
        _pair = _fm.normalize_mapping({"mappings": [{"from": "品名", "to": "itemName"}, {"from": "物料名称", "to": "itemName"}, {"from": "数量", "to": "quantity"}]})
        _itemName_f = next((f for f in _pair["fields"] if f["field"] == "itemName"), {})
        check("E13 扁平多对一配对归并别名", len(_pair["fields"]) == 2 and _itemName_f.get("aliases") == ["品名", "物料名称"],
              json.dumps(_pair, ensure_ascii=False))
        _dup = _fm.normalize_mapping({"fields": [{"field": "itemName", "label": "品名", "aliases": ["品名"]}, {"field": "itemName", "label": "品名", "aliases": ["物料名称"]}]})
        check("E14 重复 field 行归并（不报重复）", len(_dup["fields"]) == 1 and _dup["fields"][0]["aliases"] == ["品名", "物料名称"] and _fm.validate_mapping({"fields": [{"field": "itemName", "label": "品名"}, {"field": "itemName", "label": "品名"}]}) == [])
        _ex2 = {"tables": [{"page": 1, "headers": ["品名", "产品名称", "数量"], "entries": [{"cells": {"品名": "甲", "产品名称": "", "数量": "5"}}]}]}
        _o2 = _fm.transform(_ex2, {"品名": "itemName", "产品名称": "itemName", "数量": "quantity"}, _m, "ct-y")
        check("E15 多列同字段非空优先合并", _o2["entries"][0].get("itemName") == "甲" and _o2["entries"][0].get("quantity") == "5",
              json.dumps(_o2["entries"][0], ensure_ascii=False))
        _ex3 = {"tables": [{"page": 1, "headers": ["品名", "产品名称"], "entries": [{"cells": {"品名": "甲", "产品名称": "乙"}}]}]}
        _o3 = _fm.transform(_ex3, {"品名": "itemName", "产品名称": "itemName"}, _m, "ct-z")
        check("E16 多列同字段冲突留痕", _o3["entries"][0].get("itemName") == "甲" and _o3["entries"][0].get("_conflicts", {}).get("itemName") == ["甲", "乙"],
              json.dumps(_o3["entries"][0], ensure_ascii=False))
        s, _, ls = req("GET", "/api/llm/status")
        check("E8 LLM 端点状态如实（endpoint/model/available）", s == 200 and "endpoint" in ls and "model" in ls
              and "available" in ls and "reachable" in ls,
              f"endpoint={ls.get('endpoint')} model={ls.get('model')} available={ls.get('available')}")
        s, _, stg = req("GET", "/api/stages")
        check("E9 合同流水线含 llm_map 阶段", any(x["key"] == "llm_map" for x in stg.get("contract", [])))
        # 全模型可用性门控：LLM 起来时总览 ok；把端点指向死端口时解析被 409 拒
        s, _, ma = req("GET", "/api/models/availability")
        check("E17 全模型可用性总览（Paddle+LLM）", s == 200 and isinstance(ma.get("models"), list)
              and any(m["kind"] == "llm" for m in ma["models"]) and "ok" in ma,
              f"ok={ma.get('ok')} n={len(ma.get('models', []))}")
        if local_llm is not None:
            check("E17b LLM 在线时门控通过", ma.get("ok") is True, f"errors={ma.get('errors')}")
            req("POST", "/api/config", {"llm": {"base_url": "http://127.0.0.1:1"}})   # 死端口
            img_g = (FIX / "upload-sample.png").read_bytes()
            sg, _, jg = req("POST", "/api/documents", form={"file": ("gate.png", img_g, "image/png")})
            sg2, _, eg = req("POST", "/api/parse", {"docId": jg.get("id")})
            check("E18 LLM 端点不可达时解析被 409 拒", sg2 == 409 and "模型可用性未通过" in str(eg),
                  f"status={sg2} body={str(eg)[:80]}")
            req("DELETE", f"/api/documents/{jg.get('id')}")
            req("POST", "/api/config", {"llm": {"base_url": "http://127.0.0.1:9931"}})   # 恢复
        # 前置提示词：schema 字段 + 配置生效 + 留空回退默认 + 还原
        s, _, sch = req("GET", "/api/schema")
        _llm_grp = next((g for g in sch["groups"] if g["key"] == "llm"), {})
        _sp_f = next((f for f in _llm_grp.get("fields", []) if f["key"] == "system_prompt"), {})
        check("E19a schema 含前置提示词字段（textarea+默认）", _sp_f.get("type") == "textarea" and bool(_sp_f.get("default")))
        _default_prompt = _sp_f.get("default")
        req("POST", "/api/config", {"llm": {"system_prompt": "自定义前置提示词TEST"}})
        _msgs = _llm._build_prompt(["品名", "数量"], _fm.load_mapping())
        check("E19b 配置的前置提示词生效", _msgs[0]["content"] == "自定义前置提示词TEST", _msgs[0]["content"][:30])
        req("POST", "/api/config", {"llm": {"system_prompt": ""}})
        _msgs2 = _llm._build_prompt(["品名"], _fm.load_mapping())
        check("E19c 留空回退代码最优默认", _msgs2[0]["content"] == _cfgmod.DEFAULT_SYSTEM_PROMPT)
        req("POST", "/api/config", {"llm": {"system_prompt": _default_prompt}})   # 还原默认
        # 真起本地大模型跑映射（端点可用时）：输出业务英文字段名新 json
        if ls.get("available") and first_cid:
            s, _, mp = req("POST", f"/api/contracts/{first_cid}/llm-map", {}, timeout=180)
            biz_keys = {"sortOrder", "itemName", "spec", "unit", "quantity", "unitPrice", "amount"}
            entries_ok = bool(mp.get("entries")) and all(biz_keys & set(e.keys()) for e in mp["entries"])
            check("E10 真 LLM 映射输出业务字段 json", s == 200 and mp.get("status") == "ok" and entries_ok,
                  f"status={mp.get('status')} engine={mp.get('engine')} n={mp.get('entryCount')} reason={mp.get('reason')}")
            s, _, mp2 = req("GET", f"/api/contracts/{first_cid}/mapped")
            check("E11 mapped 产物可持久化读回", s == 200 and mp2.get("status") == "ok" and mp2.get("entryCount") == mp.get("entryCount"))
            _, _, fp = req("GET", f"/api/contracts/{first_cid}/result")
            frep = fp.get("report", {})
            flds = {f["field"] for r in frep.get("itemComparison", []) for f in r.get("fields", [])}
            check("E12 校验用映射业务字段匹配后端响应（matchSource=mapped）",
                  frep.get("matchSource") == "mapped" and frep.get("status") == "matched" and "itemName" in flds,
                  f"matchSource={frep.get('matchSource')} status={frep.get('status')} fields={sorted(flds)}")
        else:
            check("E10 端点不可用时映射优雅跳过", True, "LLM 端点不可用，跳过真 LLM 判据")
        return finish()
    finally:
        try:
            req("POST", "/api/config", {"parse": {"auto_parse_on_upload": False}}, timeout=5)
        except Exception:
            pass
        if local_llm is not None:
            local_llm.stop()
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
        if source_proc:
            source_proc.terminate()


def finish():
    failed = [r for r in RESULTS if not r[1]]
    print(f"\nRESULT {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.exit(len(failed))


if __name__ == "__main__":
    main()