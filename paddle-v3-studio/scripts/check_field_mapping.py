# -*- coding: utf-8 -*-
"""字段映射广度黑箱测试：10 份不同真实场景合同 PDF，匹配不同字段映射（不同表头别名/扩展字段/规则与不规则形态）。

黑箱：只给输入（PDF）看输出（解析条目+映射字段+校验结局），不碰内部。合同号均后端存在、核心明细对齐 data.sql；
扩展列（税率/税额/品牌/产地/制造商/交货期/质保/备注）考验扩展字段映射，核心字段参与后端比对。
断言：条目数正确 + 期望业务字段被映射 + 校验 matched。退出码=失败数。结果落 doc/field-mapping-test-results.json。

用法（venv，后端 8390 + 数据源 8081 + 4B 端点 9931 在线）：
  .venv\\Scripts\\python.exe scripts\\check_field_mapping.py            # 仅生成 PDF
  .venv\\Scripts\\python.exe scripts\\check_field_mapping.py --run      # 生成并黑箱测试
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "fixtures" / "field-mapping"

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

ITEMS = {
    "HT-2026-001": [["联想 ThinkPad T14 笔记本", "i7/16G/512G", "台", "10", "6999.00", "69990.00"],
                    ["惠普 LaserJet 打印机", "M405dn", "台", "4", "2899.00", "11596.00"],
                    ["得力 A4 复印纸", "70g 500张", "箱", "50", "128.00", "6400.00"]],
    "HT-2026-002": [["硒鼓", "CF258A", "支", "20", "480.00", "9600.00"],
                    ["网线", "CAT6 305米", "箱", "10", "600.00", "6000.00"]],
    "HT-2026-003": [["办公设备年度维保", "全年驻场", "项", "1", "36000.00", "36000.00"]],
}
TOTAL = {"HT-2026-001": "87986.00", "HT-2026-002": "15600.00", "HT-2026-003": "36000.00"}
CORE = ["itemName", "spec", "unit", "quantity", "unitPrice", "amount"]

# 规则案例：coreHeaders(7列别名) + extraHeaders + extraVals(每行) + expectFields
# 不规则案例：layout + items（用 make_irregular_demo 的构造器）
CASES = [
    {"file": "m01-standard-001", "no": "HT-2026-001", "layout": "regular",
     "coreHeaders": ["序号", "品名", "规格型号", "单位", "数量", "单价(元)", "金额(元)"],
     "extraHeaders": [], "extraVals": [], "expectFields": CORE},
    {"file": "m02-material-002", "no": "HT-2026-002", "layout": "regular",
     "coreHeaders": ["项次", "物料名称", "规格", "计量单位", "采购数量", "含税单价", "含税金额"],
     "extraHeaders": [], "extraVals": [], "expectFields": CORE},
    {"file": "m03-goods-003", "no": "HT-2026-003", "layout": "regular",
     "coreHeaders": ["行号", "货物名称", "型号", "单位", "数目", "单价", "总价"],
     "extraHeaders": [], "extraVals": [], "expectFields": CORE},
    {"file": "m04-tax-001", "no": "HT-2026-001", "layout": "regular",
     "coreHeaders": ["序号", "设备名称", "技术规格", "单位", "订购数量", "不含税单价", "不含税金额"],
     "extraHeaders": ["税率", "税额"], "extraVals": [["13%", "9098.70"], ["13%", "1507.48"], ["13%", "832.00"]],
     "expectFields": CORE + ["taxRate", "taxAmount"]},
    {"file": "m05-brand-002", "no": "HT-2026-002", "layout": "regular",
     "coreHeaders": ["序号", "商品名称", "型号规格", "单位", "需求数量", "净价", "净价金额"],
     "extraHeaders": ["品牌", "产地"], "extraVals": [["惠普", "中国"], ["山泽", "中国"]],
     "expectFields": CORE + ["brand", "origin"]},
    {"file": "m06-mfr-001", "no": "HT-2026-001", "layout": "regular",
     "coreHeaders": ["序号", "产品名称", "规格描述", "计量单位", "数量", "单价（含税）", "金额（含税）"],
     "extraHeaders": ["生产厂家", "质保期"], "extraVals": [["联想", "3年"], ["惠普", "1年"], ["得力", "1年"]],
     "expectFields": CORE + ["manufacturer", "warranty"]},
    {"file": "m07-delivery-002", "no": "HT-2026-002", "layout": "regular",
     "coreHeaders": ["项号", "物料描述", "规格尺寸", "单位名称", "订单数量", "单价(含税)", "金额(含税)"],
     "extraHeaders": ["交货期", "备注"], "extraVals": [["15天", "原装"], ["15天", "国标"]],
     "expectFields": CORE + ["deliveryDate", "remark"]},
    {"file": "m08-kv-003", "no": "HT-2026-003", "layout": "kv", "expectFields": CORE},
    {"file": "m09-transposed-002", "no": "HT-2026-002", "layout": "transposed", "expectFields": CORE},
    {"file": "m10-merged-001", "no": "HT-2026-001", "layout": "merged", "expectFields": CORE},
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


def _regular_rows(case):
    items = ITEMS[case["no"]]
    rows = []
    for i, it in enumerate(items):
        extra = case["extraVals"][i] if case["extraVals"] else []
        rows.append([str(i + 1), it[0], it[1], it[2], it[3], it[4], it[5]] + extra)
    return rows


def build_table(doc, case):
    layout = case["layout"]
    items = ITEMS[case["no"]]
    total = TOTAL[case["no"]]
    if layout == "regular":
        headers = case["coreHeaders"] + case["extraHeaders"]
        rows = _regular_rows(case)
        table = doc.add_table(rows=1 + len(rows), cols=len(headers))
        table.style = "Table Grid"
        for c, h in enumerate(headers):
            _fill(table.cell(0, c), h, True)
        for r, row in enumerate(rows, 1):
            for c, v in enumerate(row):
                _fill(table.cell(r, c), v)
    else:
        from make_irregular_demo import build_table as irregular_builder
        irregular_builder(doc, layout, items, total, case["no"])


def make_pdf(case):
    from contract import docx_to_pdf
    OUT.mkdir(parents=True, exist_ok=True)
    doc = Document()
    _font(doc)
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run("采购合同")
    r.bold = True
    r.font.size = Pt(18)
    doc.add_paragraph(f"合同编号：{case['no']}")
    doc.add_paragraph("甲方（采购方）：杭州云帆科技有限公司")
    doc.add_paragraph("乙方（供应方）：示例供应商有限公司")
    doc.add_paragraph("签订日期：2026 年 10 月 15 日    签订地点：杭州")
    doc.add_paragraph("甲乙双方经友好协商，就甲方向乙方采购下述货物事宜达成如下协议：")
    doc.add_paragraph("一、产品明细").runs[0].bold = True
    build_table(doc, case)
    doc.add_paragraph(f"二、合同总金额：人民币 {TOTAL[case['no']]} 元（含税）。")
    doc.add_paragraph("三、质量要求：乙方保证所供货物为原厂全新正品，符合国家质量标准。")
    doc.add_paragraph("四、交货时间：合同签订后 15 个工作日内交货至甲方指定地点。")
    doc.add_paragraph("五、付款方式：验收合格并收到等额增值税专用发票后 30 日内支付全部货款。")
    doc.add_paragraph("")
    doc.add_paragraph("甲方（盖章）：杭州云帆科技有限公司        乙方（盖章）：示例供应商有限公司")
    docx_path = OUT / (case["file"] + ".docx")
    doc.save(docx_path)
    pdf_path = docx_path.with_suffix(".pdf")
    docx_to_pdf(docx_path, pdf_path)
    return pdf_path


def run_blackbox(base):
    import requests
    print(f"\n===== 字段映射广度黑箱测试（后端 {base}，10 案例）=====")
    fail = 0
    results = []
    for case in CASES:
        pdf = OUT / (case["file"] + ".pdf")
        if not pdf.exists():
            pdf = make_pdf(case)
        n_exp = len(ITEMS[case["no"]])
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
            results.append({"file": case["file"], "pass": False, "reason": "parse_failed"})
            requests.delete(base + f"/api/contracts/{cid}", timeout=10)
            continue
        res = requests.get(base + f"/api/contracts/{cid}/result", timeout=10).json()
        ex = res.get("extracted", {})
        entries = [e for t in ex.get("tables", []) for e in t.get("entries", [])]
        mapped = res.get("mapped", {})
        m_entries = mapped.get("entries", [])
        report = res.get("report", {})
        no = (ex.get("contractNo") or {}).get("number")
        routes = [{"layout": t.get("layout"), "method": t.get("method")} for t in ex.get("tables", [])]
        # 期望字段是否被映射（ mapped 条目中该字段非空）
        mapped_keys = set()
        for me in m_entries:
            mapped_keys.update(k for k, v in me.items() if v not in (None, "") and not k.startswith("_")
                               and k not in ("page", "rowBoxNorm"))
        missing = [f for f in case["expectFields"] if f not in mapped_keys]
        print(f"  合同号={no} 路由={routes}")
        print(f"  提取={len(entries)} 映射条目={len(m_entries)} 映射字段={sorted(mapped_keys)}")
        print(f"  期望字段缺失={missing} 校验={report.get('status')}/{report.get('matchSource')}")
        ok = (no == case["no"] and len(entries) == n_exp and not missing
              and report.get("status") == "matched")
        print(f"  [{'PASS' if ok else 'FAIL'}] 期望合同号={case['no']} 条目={n_exp} 字段={case['expectFields']} matched")
        if not ok:
            fail += 1
        results.append({"file": case["file"], "no": case["no"], "layout": case["layout"],
                        "expectedEntries": n_exp, "extractedEntries": len(entries),
                        "routes": routes, "mappedFields": sorted(mapped_keys),
                        "missingFields": missing, "verifyStatus": report.get("status"),
                        "matchSource": report.get("matchSource"), "pass": ok})
        requests.delete(base + f"/api/contracts/{cid}", timeout=10)
    print(f"\n===== 黑箱测试 {'全部通过' if fail == 0 else f'{fail} 项失败'}（{len(results) - fail}/{len(results)}）=====")
    doc = ROOT / "doc"
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "field-mapping-test-results.json").write_text(
        json.dumps({"cases": results, "passed": len(results) - fail, "total": len(results)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--base", default="http://127.0.0.1:8390")
    args = ap.parse_args()
    for case in CASES:
        p = make_pdf(case)
        print(f"[mapping] {p.name} ({p.stat().st_size} bytes) layout={case['layout']} no={case['no']}")
    if args.run:
        sys.exit(run_blackbox(args.base))


if __name__ == "__main__":
    main()