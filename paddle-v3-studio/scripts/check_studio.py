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
    try:
        if not wait_health(BASE):
            print("FATAL: backend did not come up")
            sys.exit(99)

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
        return finish()
    finally:
        try:
            req("POST", "/api/config", {"parse": {"auto_parse_on_upload": False}}, timeout=5)
        except Exception:
            pass
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