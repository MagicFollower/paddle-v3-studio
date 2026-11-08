"""生成样例合同 fixtures：docx（python-docx）→ pdf（WPS COM）。

三份样例对应三种校验结局：
  sample-HT-2026-001.docx      与数据源完全一致 → matched
  sample-HT-2026-002-bad.docx  数量/金额与数据源不符 → mismatch
  sample-HT-2026-999.docx      合同号不在数据源 → not_found
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
FIX = ROOT / "fixtures"

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn


def _set_font(doc):
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def make_contract(no: str, title: str, party_b: str, items: list, total: str, path: Path):
    doc = Document()
    _set_font(doc)
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run(title)
    r.bold = True
    r.font.size = Pt(18)

    doc.add_paragraph(f"合同编号：{no}")
    doc.add_paragraph("甲方（采购方）：杭州云帆科技有限公司")
    doc.add_paragraph(f"乙方（供应方）：{party_b}")
    doc.add_paragraph("签订日期：2026 年 10 月 15 日    签订地点：杭州")
    doc.add_paragraph("根据《中华人民共和国民法典》及有关法律法规，甲乙双方经友好协商，就甲方向乙方采购下述货物事宜达成如下协议：")

    doc.add_paragraph("一、产品明细").runs[0].bold = True
    table = doc.add_table(rows=1, cols=7)
    table.style = "Table Grid"
    headers = ["序号", "品名", "规格型号", "单位", "数量", "单价(元)", "金额(元)"]
    for i, htxt in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = htxt
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
    for idx, it in enumerate(items, 1):
        row = table.add_row().cells
        vals = [str(idx), it["name"], it["spec"], it["unit"], str(it["qty"]),
                f"{it['price']:.2f}", f"{it['amount']:.2f}"]
        for c, v in zip(row, vals):
            c.text = v
    row = table.add_row().cells
    row[1].text = "合计"
    row[6].text = total

    doc.add_paragraph(f"二、合同总金额：人民币 {total} 元（含税）。")
    doc.add_paragraph("三、质量要求：乙方保证所供货物为原厂全新正品，符合国家质量标准及本合同约定的规格型号。")
    doc.add_paragraph("四、交货时间：合同签订后 15 个工作日内交货至甲方指定地点。")
    doc.add_paragraph("五、交货地点：杭州市西湖区甲方办公区，运输费用由乙方承担。")
    doc.add_paragraph("六、验收标准：甲方按本合同明细逐项验收，数量与外观当场确认，质量异议期为收货后 7 个工作日。")
    doc.add_paragraph("七、付款方式：验收合格并收到乙方开具的等额增值税专用发票后 30 日内支付全部货款。")
    doc.add_paragraph("八、违约责任：乙方逾期交货的，每逾期一日按合同总额的千分之三向甲方支付违约金。")
    doc.add_paragraph("九、争议解决：双方协商解决；协商不成的，向甲方所在地人民法院提起诉讼。")
    doc.add_paragraph("十、其他约定：本合同一式两份，甲乙双方各执一份，自双方签章之日起生效。")
    doc.add_paragraph("十一、附件：乙方营业执照复印件、产品合格证明为本合同附件，与本合同具有同等效力。")
    doc.add_paragraph("十二、补充条款：未尽事宜由双方另行签订补充协议，补充协议与本合同具有同等法律效力。")
    doc.add_paragraph("")
    doc.add_paragraph("甲方（盖章）：杭州云帆科技有限公司        乙方（盖章）：" + party_b)
    doc.add_paragraph("授权代表：____________________            授权代表：____________________")
    doc.save(path)


def main():
    FIX.mkdir(parents=True, exist_ok=True)
    specs = [
        ("sample-HT-2026-001.docx", "HT-2026-001", "办公设备采购合同", "上海立达办公设备有限公司",
         [
             {"name": "联想 ThinkPad T14 笔记本", "spec": "i7/16G/512G", "unit": "台", "qty": 10, "price": 6999.00, "amount": 69990.00},
             {"name": "惠普 LaserJet 打印机", "spec": "M405dn", "unit": "台", "qty": 4, "price": 2899.00, "amount": 11596.00},
             {"name": "得力 A4 复印纸", "spec": "70g 500张", "unit": "箱", "qty": 50, "price": 128.00, "amount": 6400.00},
         ], "87986.00"),
        ("sample-HT-2026-002-bad.docx", "HT-2026-002", "IT 耗材采购合同", "南京汇川商贸有限公司",
         [
             {"name": "硒鼓", "spec": "CF258A", "unit": "支", "qty": 25, "price": 480.00, "amount": 12000.00},
             {"name": "网线", "spec": "CAT6 305米", "unit": "箱", "qty": 10, "price": 600.00, "amount": 6000.00},
         ], "18000.00"),
        ("sample-HT-2026-999.docx", "HT-2026-999", "临时采购合同", "苏州明道科技有限公司",
         [
             {"name": "会议平板", "spec": "86英寸", "unit": "台", "qty": 2, "price": 15800.00, "amount": 31600.00},
         ], "31600.00"),
    ]
    from contract import docx_to_pdf
    for fname, no, title, party_b, items, total in specs:
        docx_path = FIX / fname
        make_contract(no, title, party_b, items, total, docx_path)
        print(f"[fixture] {docx_path.name} written")
        pdf_path = docx_path.with_suffix(".pdf")
        docx_to_pdf(docx_path, pdf_path)
        print(f"[fixture] {pdf_path.name} via WPS COM ({pdf_path.stat().st_size} bytes)")

    # 复用 studio 的真图做任务1判据输入
    import shutil
    studio_fix = ROOT.parent.parent / "paddleocr-vl-studio" / "fixtures"
    for name in ("upload-sample.png", "dense-sample.png"):
        src = studio_fix / name
        if src.exists():
            shutil.copy(src, FIX / name)
            print(f"[fixture] copied {name}")
    print("[fixture] DONE")


if __name__ == "__main__":
    main()