# -*- coding: utf-8 -*-
"""模拟 3 个不同合同 PDF 的真实调用案例：varied 中文表头 → LLM 映射 → 后端查询接口匹配。

三份 PDF 内容分别对齐后端 contract-source 的 HT-2026-001/002/003（data.sql），但表头刻意用
三套不同写法，证明 LLM 能把不同合同明细表头自动识别并转换为后端响应参数名
（sortOrder/itemName/spec/unit/quantity/unitPrice/amount），再在查询后端接口前完成转换、正常匹配。

用法（venv）：
  .venv\\Scripts\\python.exe scripts\\make_llm_demo.py                 # 仅生成 3 份 PDF
  .venv\\Scripts\\python.exe scripts\\make_llm_demo.py --run           # 生成并真上传解析+映射+校验
  .venv\\Scripts\\python.exe scripts\\make_llm_demo.py --run --base http://127.0.0.1:8390
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

# 每例：文件名 / 合同号 / 标题 / 乙方 / 表头(7列 varied) / 明细(对齐后端) / 合计
CASES = [
    {
        "file": "demo-A-standard-001", "no": "HT-2026-001", "title": "办公设备采购合同",
        "party_b": "上海立达办公设备有限公司",
        "headers": ["序号", "品名", "规格型号", "单位", "数量", "单价(元)", "金额(元)"],
        "items": [
            ["联想 ThinkPad T14 笔记本", "i7/16G/512G", "台", "10", "6999.00", "69990.00"],
            ["惠普 LaserJet 打印机", "M405dn", "台", "4", "2899.00", "11596.00"],
            ["得力 A4 复印纸", "70g 500张", "箱", "50", "128.00", "6400.00"],
        ], "total": "87986.00",
    },
    {
        "file": "demo-B-material-002", "no": "HT-2026-002", "title": "IT 耗材采购合同",
        "party_b": "南京汇川商贸有限公司",
        "headers": ["项次", "物料名称", "规格", "计量单位", "采购数量", "含税单价", "含税金额"],
        "items": [
            ["硒鼓", "CF258A", "支", "20", "480.00", "9600.00"],
            ["网线", "CAT6 305米", "箱", "10", "600.00", "6000.00"],
        ], "total": "15600.00",
    },
    {
        "file": "demo-C-goods-003", "no": "HT-2026-003", "title": "年度维保服务合同",
        "party_b": "上海立达办公设备有限公司",
        "headers": ["行号", "货物名称", "型号", "单位", "数目", "单价", "总价"],
        "items": [
            ["办公设备年度维保", "全年驻场", "项", "1", "36000.00", "36000.00"],
        ], "total": "36000.00",
    },
]


def _font(doc):
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def make_pdf(case: dict) -> Path:
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
    doc.add_paragraph("一、产品明细").runs[0].bold = True
    table = doc.add_table(rows=1, cols=7)
    table.style = "Table Grid"
    for i, htxt in enumerate(case["headers"]):
        cell = table.rows[0].cells[i]
        cell.text = htxt
        for p in cell.paragraphs:
            for rr in p.runs:
                rr.bold = True
    for idx, it in enumerate(case["items"], 1):
        row = table.add_row().cells
        for c, v in zip(row, [str(idx)] + it):
            c.text = v
    row = table.add_row().cells
    row[1].text = "合计"
    row[6].text = case["total"]
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


def run_cases(base: str):
    import requests
    print(f"\n===== 真实调用案例（后端 {base}）=====")
    # 确保自动解析关闭也手动起任务；先探活
    h = requests.get(base + "/api/health", timeout=5).json()
    print("studio:", h)
    results = []
    for case in CASES:
        pdf = OUT / (case["file"] + ".pdf")
        if not pdf.exists():
            pdf = make_pdf(case)
        print(f"\n----- {case['file']} ({case['no']}) 表头={case['headers']} -----")
        with open(pdf, "rb") as f:
            up = requests.post(base + "/api/contracts/upload",
                               files={"file": (pdf.name, f, "application/pdf")}, timeout=60).json()
        cid = up["id"]
        requests.post(base + f"/api/contracts/{cid}/parse", json={}, timeout=10)
        # 轮询任务完成
        job = None
        for _ in range(180):
            items = requests.get(base + "/api/jobs", params={"refId": cid}, timeout=10).json()["items"]
            if items and items[0]["status"] in ("done", "failed"):
                job = items[0]
                break
            time.sleep(2)
        if not job or job["status"] != "done":
            print("  解析失败/超时:", (job or {}).get("error"))
            results.append((case["no"], "PARSE_FAIL"))
            continue
        print("  阶段路径:", job["stagePath"])
        res = requests.get(base + f"/api/contracts/{cid}/result", timeout=10).json()
        ex_headers = [t.get("headers") for t in res.get("extracted", {}).get("tables", [])]
        mapped = res.get("mapped", {})
        report = res.get("report", {})
        print("  OCR 表头:", ex_headers)
        print("  LLM headerMap:", mapped.get("headerMap"))
        print("  映射字段:", [f["field"] for f in mapped.get("fields", [])], "device:", mapped.get("device"))
        if mapped.get("entries"):
            print("  映射首条:", mapped["entries"][0])
        print("  校验 matchSource:", report.get("matchSource"), "status:", report.get("status"))
        results.append((case["no"], report.get("status")))
        # 清理演示条目，避免污染文件列表
        requests.delete(base + f"/api/contracts/{cid}", timeout=10)
    print("\n===== 汇总 =====")
    for no, st in results:
        print(f"  {no}: {st}")
    ok = all(st == "matched" for _, st in results)
    print("ALL_MATCHED" if ok else "SOME_NOT_MATCHED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="生成后真上传解析+映射+校验")
    ap.add_argument("--base", default="http://127.0.0.1:8390")
    args = ap.parse_args()
    for case in CASES:
        p = make_pdf(case)
        print(f"[demo] {p.name} ({p.stat().st_size} bytes) 表头={case['headers']}")
    if args.run:
        ok = run_cases(args.base)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()