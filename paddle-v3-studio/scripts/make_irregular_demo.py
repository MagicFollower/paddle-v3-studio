# -*- coding: utf-8 -*-
"""真实不规则表格合同 PDF 生成 + 4B 端到端评测验收。

三份真实 PDF（docx→WPS COM→pdf），合同号均为后端 contract-source 已存在，明细内容逐字对齐 data.sql，
但表格行列极不规范，覆盖：键值对（HT-2026-003）、转置（HT-2026-002）、多行合并表头+分类+小计（HT-2026-001）。
真上传→OCR→表格识别→启发式/LLM 结构理解→映射→后端查询校验，验收断言 matched + 条目正确。

用法（venv，后端 8390 + 数据源 8081 + 4B 模型端点 9931 需在线）：
  .venv\\Scripts\\python.exe scripts\\make_irregular_demo.py            # 仅生成 PDF
  .venv\\Scripts\\python.exe scripts\\make_irregular_demo.py --run      # 生成并真跑验收（退出码=失败数）
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
OUT = ROOT / "fixtures" / "llm-demo"

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

# items: [name, spec, unit, qty, price, amount]
CASES = [
    {"file": "demo-irregular-kv-003", "no": "HT-2026-003", "title": "年度维保服务合同",
     "party_b": "上海立达办公设备有限公司", "layout": "kv",
     "items": [["办公设备年度维保", "全年驻场", "项", "1", "36000.00", "36000.00"]], "total": "36000.00"},
    {"file": "demo-irregular-transposed-002", "no": "HT-2026-002", "title": "IT 耗材采购合同",
     "party_b": "南京汇川商贸有限公司", "layout": "transposed",
     "items": [["硒鼓", "CF258A", "支", "20", "480.00", "9600.00"],
               ["网线", "CAT6 305米", "箱", "10", "600.00", "6000.00"]], "total": "15600.00"},
    {"file": "demo-irregular-merged-001", "no": "HT-2026-001", "title": "办公设备采购合同",
     "party_b": "上海立达办公设备有限公司", "layout": "merged",
     "items": [["联想 ThinkPad T14 笔记本", "i7/16G/512G", "台", "10", "6999.00", "69990.00"],
               ["惠普 LaserJet 打印机", "M405dn", "台", "4", "2899.00", "11596.00"],
               ["得力 A4 复印纸", "70g 500张", "箱", "50", "128.00", "6400.00"]], "total": "87986.00"},
    {"file": "demo-irregular-kvmulti-002", "no": "HT-2026-002", "title": "IT 耗材采购合同",
     "party_b": "南京汇川商贸有限公司", "layout": "kv-multi",
     "items": [["硒鼓", "CF258A", "支", "20", "480.00", "9600.00"],
               ["网线", "CAT6 305米", "箱", "10", "600.00", "6000.00"]], "total": "15600.00"},
    {"file": "demo-irregular-transposed-001", "no": "HT-2026-001", "title": "办公设备采购合同",
     "party_b": "上海立达办公设备有限公司", "layout": "transposed",
     "items": [["联想 ThinkPad T14 笔记本", "i7/16G/512G", "台", "10", "6999.00", "69990.00"],
               ["惠普 LaserJet 打印机", "M405dn", "台", "4", "2899.00", "11596.00"],
               ["得力 A4 复印纸", "70g 500张", "箱", "50", "128.00", "6400.00"]], "total": "87986.00"},
    {"file": "demo-irregular-rowspan-001", "no": "HT-2026-001", "title": "办公设备采购合同",
     "party_b": "上海立达办公设备有限公司", "layout": "rowspan-category",
     "items": [["联想 ThinkPad T14 笔记本", "i7/16G/512G", "台", "10", "6999.00", "69990.00"],
               ["惠普 LaserJet 打印机", "M405dn", "台", "4", "2899.00", "11596.00"],
               ["得力 A4 复印纸", "70g 500张", "箱", "50", "128.00", "6400.00"]], "total": "87986.00"},
    {"file": "demo-irregular-nohtable-003", "no": "HT-2026-003", "title": "年度维保服务合同",
     "party_b": "上海立达办公设备有限公司", "layout": "contractno-table",
     "items": [["办公设备年度维保", "全年驻场", "项", "1", "36000.00", "36000.00"]], "total": "36000.00"},
    {"file": "demo-irregular-sectioned-002", "no": "HT-2026-002", "title": "IT 耗材采购合同",
     "party_b": "南京汇川商贸有限公司", "layout": "sectioned",
     "items": [["硒鼓", "CF258A", "支", "20", "480.00", "9600.00"],
               ["网线", "CAT6 305米", "箱", "10", "600.00", "6000.00"]], "total": "15600.00"},
]


def _font(doc):
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def _fill(cell, text, bold=False):
    cell.text = str(text)
    for p in cell.paragraphs:
        for r in p.runs:
            r.bold = bold


def build_table(doc, layout, items, total, no=""):
    if layout == "kv":
        it = items[0]
        rows = [["品名", it[0]], ["规格", it[1]], ["单位", it[2]],
                ["数量", it[3]], ["单价", it[4]], ["金额", it[5]]]
        table = doc.add_table(rows=len(rows), cols=2)
        table.style = "Table Grid"
        for i, (k, v) in enumerate(rows):
            _fill(table.cell(i, 0), k, True)
            _fill(table.cell(i, 1), v)
    elif layout == "transposed":
        labels = ["品名", "规格", "单位", "数量", "单价", "金额"]
        table = doc.add_table(rows=6, cols=1 + len(items))
        table.style = "Table Grid"
        for r, label in enumerate(labels):
            _fill(table.cell(r, 0), label, True)
            for c, it in enumerate(items, 1):
                _fill(table.cell(r, c), it[r])
    elif layout == "merged":
        # 多行合并表头：序号/品名/规格型号/单价/金额 直列，数量信息(colspan2)下分 数量|单位；
        # 穿插分类行 + 明细 + 小计 + 合计。
        table = doc.add_table(rows=2 + 1 + len(items) + 2, cols=7)
        table.style = "Table Grid"
        h0 = ["序号", "品名", "规格型号", "数量信息", "", "单价", "金额"]
        for c, t in enumerate(h0):
            _fill(table.cell(0, c), t, True)
        table.cell(0, 3).merge(table.cell(0, 4))
        _fill(table.cell(0, 3), "数量信息", True)
        _fill(table.cell(1, 3), "数量", True)
        _fill(table.cell(1, 4), "单位", True)
        # 分类行（全宽合并）
        cat = table.cell(2, 0).merge(table.cell(2, 6))
        _fill(cat, "一、办公设备类", True)
        # 明细行
        for i, it in enumerate(items):
            r = 3 + i
            vals = [str(i + 1), it[0], it[1], it[3], it[2], it[4], it[5]]
            for c, v in enumerate(vals):
                _fill(table.cell(r, c), v)
        # 小计行（前两列合并）
        sub_r = 3 + len(items)
        table.cell(sub_r, 0).merge(table.cell(sub_r, 1))
        _fill(table.cell(sub_r, 0), "小计", True)
        _fill(table.cell(sub_r, 6), total)
        # 合计行
        tot_r = sub_r + 1
        table.cell(tot_r, 0).merge(table.cell(tot_r, 5))
        _fill(table.cell(tot_r, 0), "合计", True)
        _fill(table.cell(tot_r, 6), total)
    elif layout == "kv-multi":
        labels = ["品名", "规格", "单位", "数量", "单价", "金额"]
        n = len(items)
        table = doc.add_table(rows=6, cols=2 * n)
        table.style = "Table Grid"
        for r, label in enumerate(labels):
            for c, it in enumerate(items):
                _fill(table.cell(r, 2 * c), label, True)
                _fill(table.cell(r, 2 * c + 1), it[r])
    elif layout == "rowspan-category":
        n = len(items)
        table = doc.add_table(rows=1 + n, cols=8)
        table.style = "Table Grid"
        for c, h in enumerate(["类别", "序号", "品名", "规格", "单位", "数量", "单价", "金额"]):
            _fill(table.cell(0, c), h, True)
        cat = table.cell(1, 0).merge(table.cell(n, 0))
        _fill(cat, "办公设备类", True)
        for i, it in enumerate(items):
            for c, v in enumerate([str(i + 1), it[0], it[1], it[2], it[3], it[4], it[5]], 1):
                _fill(table.cell(1 + i, c), v)
    elif layout == "contractno-table":
        it = items[0]
        rows = [["品名", it[0]], ["规格", it[1]], ["单位", it[2]],
                ["数量", it[3]], ["单价", it[4]], ["金额", it[5]]]
        table = doc.add_table(rows=1 + len(rows), cols=2)
        table.style = "Table Grid"
        top = table.cell(0, 0).merge(table.cell(0, 1))
        _fill(top, f"合同编号：{no}", True)
        for i, (k, v) in enumerate(rows, 1):
            _fill(table.cell(i, 0), k, True)
            _fill(table.cell(i, 1), v)
    elif layout == "sectioned":
        n = len(items)
        table = doc.add_table(rows=1 + n * 3 + 1, cols=7)
        table.style = "Table Grid"
        for c, h in enumerate(["序号", "品名", "规格", "单位", "数量", "单价", "金额"]):
            _fill(table.cell(0, c), h, True)
        r = 1
        for i, it in enumerate(items):
            cat = table.cell(r, 0).merge(table.cell(r, 6))
            _fill(cat, f"分类{i + 1}", True)
            r += 1
            for c, v in enumerate([str(i + 1), it[0], it[1], it[2], it[3], it[4], it[5]]):
                _fill(table.cell(r, c), v)
            r += 1
            table.cell(r, 0).merge(table.cell(r, 1))
            _fill(table.cell(r, 0), "小计", True)
            _fill(table.cell(r, 6), it[5])
            r += 1
        table.cell(r, 0).merge(table.cell(r, 5))
        _fill(table.cell(r, 0), "合计", True)
        _fill(table.cell(r, 6), total)


def make_pdf(case):
    from contract import docx_to_pdf
    OUT.mkdir(parents=True, exist_ok=True)
    doc = Document()
    _font(doc)
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run(case["title"])
    r.bold = True
    r.font.size = Pt(18)
    doc.add_paragraph(f"合同编号：{case['no']}")
    doc.add_paragraph("甲方（采购方）：杭州云帆科技有限公司")
    doc.add_paragraph(f"乙方（供应方）：{case['party_b']}")
    doc.add_paragraph("签订日期：2026 年 10 月 15 日    签订地点：杭州")
    doc.add_paragraph("甲乙双方经友好协商，就甲方向乙方采购下述货物事宜达成如下协议：")
    doc.add_paragraph("一、产品明细（表格格式不规范）").runs[0].bold = True
    build_table(doc, case["layout"], case["items"], case["total"], case["no"])
    doc.add_paragraph(f"二、合同总金额：人民币 {case['total']} 元（含税）。")
    doc.add_paragraph("三、质量要求：乙方保证所供货物为原厂全新正品，符合国家质量标准。")
    doc.add_paragraph("四、交货时间：合同签订后 15 个工作日内交货至甲方指定地点。")
    doc.add_paragraph("五、付款方式：验收合格并收到等额增值税专用发票后 30 日内支付全部货款。")
    doc.add_paragraph("六、违约责任：乙方逾期交货的，每逾期一日按合同总额的千分之三支付违约金。")
    doc.add_paragraph("")
    doc.add_paragraph("甲方（盖章）：杭州云帆科技有限公司        乙方（盖章）：" + case["party_b"])
    docx_path = OUT / (case["file"] + ".docx")
    doc.save(docx_path)
    pdf_path = docx_path.with_suffix(".pdf")
    docx_to_pdf(docx_path, pdf_path)
    return pdf_path


def run_cases(base):
    import requests
    print(f"\n===== 真实不规则 PDF 验收（后端 {base}）=====")
    fail = 0
    results = []
    for case in CASES:
        pdf = OUT / (case["file"] + ".pdf")
        if not pdf.exists():
            pdf = make_pdf(case)
        n_exp = len(case["items"])
        print(f"\n----- {case['file']} ({case['no']}, {case['layout']}, 期望 {n_exp} 条) -----")
        with open(pdf, "rb") as f:
            up = requests.post(base + "/api/contracts/upload",
                               files={"file": (pdf.name, f, "application/pdf")}, timeout=60).json()
        cid = up["id"]
        requests.post(base + f"/api/contracts/{cid}/parse", json={}, timeout=10)
        job = None
        for _ in range(240):
            items = requests.get(base + "/api/jobs", params={"refId": cid}, timeout=10).json()["items"]
            if items and items[0]["status"] in ("done", "failed"):
                job = items[0]
                break
            time.sleep(2)
        if not job or job["status"] != "done":
            print("  FAIL 解析失败/超时:", (job or {}).get("error"))
            fail += 1
            continue
        res = requests.get(base + f"/api/contracts/{cid}/result", timeout=10).json()
        ex = res.get("extracted", {})
        entries = [e for t in ex.get("tables", []) for e in t.get("entries", [])]
        report = res.get("report", {})
        mapped = res.get("mapped", {})
        no = (ex.get("contractNo") or {}).get("number")
        print(f"  合同号={no} 阶段={job['stagePath']}")
        for t in ex.get("tables", []):
            print(f"  表格路由：第{t.get('page')}页 layout={t.get('layout')} regular={t.get('regular')} "
                  f"method={t.get('method')} 条目={len(t.get('entries', []))}")
        print(f"  提取条目={len(entries)} 映射={mapped.get('status')}/{mapped.get('method')}")
        for e in entries:
            print(f"    -> {e.get('name')!r} qty={e.get('qty')} price={e.get('price')} amount={e.get('amount')}")
        print(f"  校验 status={report.get('status')} matchSource={report.get('matchSource')} "
              f"matched={sum(1 for r in report.get('itemComparison', []) if r.get('matched'))}")
        ok = (no == case["no"] and len(entries) == n_exp and report.get("status") == "matched")
        print(f"  [{'PASS' if ok else 'FAIL'}] 期望合同号={case['no']} 条目={n_exp} 结局=matched")
        if not ok:
            fail += 1
        results.append({"file": case["file"], "no": case["no"], "layout": case["layout"],
                        "expectedEntries": n_exp, "extractedEntries": len(entries),
                        "tableRoutes": [{"page": t.get("page"), "layout": t.get("layout"),
                                         "regular": t.get("regular"), "method": t.get("method"),
                                         "entries": len(t.get("entries", []))} for t in ex.get("tables", [])],
                        "verifyStatus": report.get("status"), "matchSource": report.get("matchSource"),
                        "pass": ok})
        requests.delete(base + f"/api/contracts/{cid}", timeout=10)
    print(f"\n===== 验收 {'全部通过' if fail == 0 else f'{fail} 项失败'}（{len(results) - fail}/{len(results)}）=====")
    doc = ROOT / "doc"
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "irregular-acceptance-results.json").write_text(
        __import__("json").dumps({"cases": results, "passed": len(results) - fail, "total": len(results)},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    return fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--base", default="http://127.0.0.1:8390")
    args = ap.parse_args()
    for case in CASES:
        p = make_pdf(case)
        print(f"[irregular] {p.name} ({p.stat().st_size} bytes) layout={case['layout']} no={case['no']}")
    if args.run:
        sys.exit(run_cases(args.base))


if __name__ == "__main__":
    main()