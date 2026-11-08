"""生成 3 份 10+ 页压力测试模拟合同（docx → WPS COM → pdf），并核实页数。

覆盖三类边界：
  * 合同号非首页（放在第 2/3 页）
  * 合同号标签与值分行（多行匹配：标签独占一行、编号在下一行）
  * 超长明细 200+ 条且跨页

用法：.venv\\Scripts\\python.exe scripts\\make_stress_contracts.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
FIX = ROOT / "fixtures"

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn


def set_font(doc):
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def page_break(doc):
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def add_items_table(doc, n):
    table = doc.add_table(rows=1, cols=7)
    table.style = "Table Grid"
    headers = ["序号", "品名", "规格型号", "单位", "数量", "单价(元)", "金额(元)"]
    for i, h in enumerate(headers):
        c = table.rows[0].cells[i]
        c.text = h
        for p in c.paragraphs:
            for r in p.runs:
                r.bold = True
    total = 0.0
    for i in range(1, n + 1):
        qty = (i % 9) + 1
        price = round(50 + (i * 13) % 900 + 0.5, 2)
        amount = round(qty * price, 2)
        total += amount
        row = table.add_row().cells
        vals = [str(i), f"办公耗材批次{i:03d}", f"型号 SPEC-{i:04d}", "件",
                str(qty), f"{price:.2f}", f"{amount:.2f}"]
        for c, v in zip(row, vals):
            c.text = v
    row = table.add_row().cells
    row[1].text = "合计"
    row[6].text = f"{total:.2f}"
    return total


CLAUSES = [
    "质量要求：乙方保证所供货物为原厂全新正品，符合国家质量标准及本合同约定的规格型号，并提供合格证明。",
    "交货时间：合同签订后分批交货，每批次于甲方发出订单后 15 个工作日内送达指定地点。",
    "交货地点：甲方指定仓库，运输费用及运输途中的损耗由乙方承担。",
    "验收标准：甲方按本合同明细逐项验收，数量与外观当场确认，质量异议期为收货后 7 个工作日。",
    "付款方式：验收合格并收到乙方开具的等额增值税专用发票后 30 日内支付相应批次货款。",
    "违约责任：乙方逾期交货的，每逾期一日按该批次货款千分之三向甲方支付违约金。",
    "知识产权：乙方保证所供货物不侵犯任何第三方知识产权，否则承担全部责任。",
    "保密条款：双方对在履行本合同过程中知悉的对方商业秘密负有保密义务。",
    "不可抗力：因不可抗力不能履行合同的，根据影响部分或全部免除责任，但应及时通知对方。",
    "争议解决：双方协商解决；协商不成的，向甲方所在地人民法院提起诉讼。",
]


def make_contract(no, number_page, n_items, path, repeat_last=False):
    doc = Document()
    set_font(doc)
    # ---- 第 1 页：封面（不含合同号）----
    for _ in range(3):
        doc.add_paragraph()
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run("大型物资采购合同")
    r.bold = True
    r.font.size = Pt(26)
    doc.add_paragraph()
    for txt in ["甲方（采购方）：杭州云帆科技有限公司",
                "乙方（供应方）：上海立达办公设备有限公司",
                "签订地点：浙江省杭州市",
                "签订日期：2026 年 11 月 01 日"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run(txt)
    doc.add_paragraph()
    doc.add_paragraph("本合同封面仅载明双方主体信息，合同编号及明细详见后续页。")
    page_break(doc)

    # ---- 第 2 页起：合同号（非首页 + 标签/值分行）----
    if number_page >= 3:
        doc.add_paragraph("第一节 合同基本信息")
        doc.add_paragraph("本节载明合同编号与基本约定，编号以本页下方单独列示者为准。")
        page_break(doc)
    doc.add_paragraph("合同编号：")          # 标签独占一行
    doc.add_paragraph(no)                     # 编号在下一行（多行模式）
    doc.add_paragraph("（上述编号为本合同唯一标识，贯穿全部明细与结算单据。）")
    doc.add_paragraph("甲乙双方经友好协商，就甲方向乙方采购下述货物事宜达成如下协议，共同遵守。")
    page_break(doc)

    # ---- 条款页 ----
    doc.add_paragraph("第二节 通用条款").runs[0].bold = True
    for i, c in enumerate(CLAUSES, 1):
        doc.add_paragraph(f"{i}. {c}")
    page_break(doc)

    # ---- 明细表（200+ 条，跨页）----
    doc.add_paragraph("第三节 采购明细清单").runs[0].bold = True
    doc.add_paragraph(f"本合同采购明细共计 {n_items} 项，清单如下（跨页连续）：")
    total = add_items_table(doc, n_items)
    doc.add_paragraph(f"合同总金额：人民币 {total:.2f} 元（含税）。")

    if repeat_last:
        page_break(doc)
        doc.add_paragraph("第四节 附则")
        doc.add_paragraph("本合同一式肆份，甲乙双方各执贰份，自双方签章之日起生效。")
        doc.add_paragraph("合同编号：")
        doc.add_paragraph(no)                 # 末页再次出现（跨页一致性）
        doc.add_paragraph("（本页编号与第 2 页编号一致，用于跨页核验。）")

    doc.save(path)


def main():
    FIX.mkdir(parents=True, exist_ok=True)
    import pypdfium2 as pdfium
    from contract import docx_to_pdf

    specs = [
        ("stress-STRESS-2026-001.docx", "STRESS-2026-001", 2, 240, False),
        ("stress-STRESS-2026-002.docx", "STRESS-2026-002", 3, 260, False),
        ("stress-STRESS-2026-003.docx", "STRESS-2026-003", 2, 220, True),
    ]
    for fname, no, npage, nitems, repeat in specs:
        docx_path = FIX / fname
        make_contract(no, npage, nitems, docx_path, repeat)
        pdf_path = docx_path.with_suffix(".pdf")
        docx_to_pdf(docx_path, pdf_path)
        pdf = pdfium.PdfDocument(str(pdf_path))
        pages = len(pdf)
        pdf.close()
        flag = "OK" if pages >= 10 else "TOO_SHORT"
        print(f"[stress] {fname}: items={nitems} number_page={npage} repeat_last={repeat} -> PDF {pages} pages [{flag}]")
        if pages < 10:
            print(f"[stress][WARN] {fname} 不足 10 页，需增加明细行")
    print("[stress] DONE")


if __name__ == "__main__":
    main()