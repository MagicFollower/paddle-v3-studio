# -*- coding: utf-8 -*-
"""构造「真实合同存在 + 跨页明细 + 明细部分存在部分不存在」的分析报告实测场景。

合同号用后端 contract-source 已存在的 HT-2026-001（data.sql 有 3 条明细）。PDF 刻意：
  - 明细表用 varied 中文表头（物料名称/计量单位/采购数量/含税单价/含税金额…），考验 LLM 多对一识别；
  - 明细行 = 后端真实 3 行（存在于数据源）+ 30 行数据源没有的多余行（部分存在部分不存在）；
  - 33 行 + 前言条款使表格自然跨 2 页（续页无表头，沿用上一页列映射）。
真上传解析后：跨页提取全量行、LLM 映射到后端字段、校验仅 3 行 matched 其余「数据源无此明细行」。

用法（venv）：.venv\\Scripts\\python.exe scripts\\make_crosspage_demo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
OUT = ROOT / "fixtures" / "llm-demo"
NO = "HT-2026-001"
HEADERS = ["序号", "物料名称", "规格型号", "计量单位", "采购数量", "含税单价", "含税金额"]

# 后端真实存在的 3 行（与 data.sql HT-2026-001 逐字对齐）
REAL_ITEMS = [
    ["联想 ThinkPad T14 笔记本", "i7/16G/512G", "台", "10", "6999.00", "69990.00"],
    ["惠普 LaserJet 打印机", "M405dn", "台", "4", "2899.00", "11596.00"],
    ["得力 A4 复印纸", "70g 500张", "箱", "50", "128.00", "6400.00"],
]
# 数据源没有的多余行（部分不存在）：品名各异，避免与后端 3 行相似度误匹配
EXTRA_NAMES = ["人体工学办公椅", "钢制文件柜", "会议桌", "无线鼠标", "机械键盘", "显示器支架",
               "桌面音箱", "网络交换机", "投影仪", "碎纸机", "饮水机", "微波炉", "冰箱",
               "空调挂机", "空气净化器", "加湿器", "电风扇", "取暖器", "吸尘器", "扫地机器人",
               "打印机墨盒", "硒鼓组件", "复印纸套餐", "标签打印机", "扫描枪", "条码阅读器",
               "ups 电源", "服务器机柜", "网线配线架", "路由器"]


def build_items():
    items = [list(r) for r in REAL_ITEMS]
    for i, name in enumerate(EXTRA_NAMES):
        qty = (i % 5) + 1
        price = 100.0 + i * 37
        items.append([name, f"型号-{i + 1:02d}", "台", str(qty), f"{price:.2f}", f"{qty * price:.2f}"])
    return items


def make_pdf() -> Path:
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from contract import docx_to_pdf
    OUT.mkdir(parents=True, exist_ok=True)
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = h.add_run("办公设备采购合同")
    r.bold = True
    r.font.size = Pt(18)
    doc.add_paragraph(f"合同编号：{NO}")
    doc.add_paragraph("甲方（采购方）：杭州云帆科技有限公司")
    doc.add_paragraph("乙方（供应方）：上海立达办公设备有限公司")
    doc.add_paragraph("签订日期：2026 年 10 月 15 日    签订地点：杭州")
    doc.add_paragraph("根据《中华人民共和国民法典》及有关法律法规，甲乙双方经友好协商，就甲方向乙方采购下述货物事宜达成如下协议：")
    doc.add_paragraph("一、产品明细").runs[0].bold = True
    items = build_items()
    table = doc.add_table(rows=1, cols=7)
    table.style = "Table Grid"
    for i, htxt in enumerate(HEADERS):
        cell = table.rows[0].cells[i]
        cell.text = htxt
        for p in cell.paragraphs:
            for rr in p.runs:
                rr.bold = True
    for idx, it in enumerate(items, 1):
        row = table.add_row().cells
        for c, v in zip(row, [str(idx)] + it):
            c.text = v
    total = sum(float(it[5]) for it in items)
    row = table.add_row().cells
    row[1].text = "合计"
    row[6].text = f"{total:.2f}"
    doc.add_paragraph(f"二、合同总金额：人民币 {total:.2f} 元（含税）。")
    for txt in [
        "三、质量要求：乙方保证所供货物为原厂全新正品，符合国家质量标准及本合同约定的规格型号。",
        "四、交货时间：合同签订后 15 个工作日内交货至甲方指定地点。",
        "五、交货地点：杭州市西湖区甲方办公区，运输费用由乙方承担。",
        "六、验收标准：甲方按本合同明细逐项验收，数量与外观当场确认，质量异议期为收货后 7 个工作日。",
        "七、付款方式：验收合格并收到乙方开具的等额增值税专用发票后 30 日内支付全部货款。",
        "八、违约责任：乙方逾期交货的，每逾期一日按合同总额的千分之三向甲方支付违约金。",
        "九、争议解决：双方协商解决；协商不成的，向甲方所在地人民法院提起诉讼。",
        "十、其他约定：本合同一式两份，甲乙双方各执一份，自双方签章之日起生效。",
    ]:
        doc.add_paragraph(txt)
    doc.add_paragraph("")
    doc.add_paragraph("甲方（盖章）：杭州云帆科技有限公司        乙方（盖章）：上海立达办公设备有限公司")
    docx_path = OUT / "demo-crosspage-partial-001.docx"
    doc.save(docx_path)
    pdf_path = docx_path.with_suffix(".pdf")
    docx_to_pdf(docx_path, pdf_path)
    return pdf_path


if __name__ == "__main__":
    p = make_pdf()
    items = build_items()
    print(f"[crosspage] {p.name} ({p.stat().st_size} bytes)")
    print(f"[crosspage] 合同号={NO}（后端存在） 表头={HEADERS}")
    print(f"[crosspage] 明细 {len(items)} 行 = 后端真实 {len(REAL_ITEMS)} 行 + 数据源多余 {len(EXTRA_NAMES)} 行（部分存在部分不存在）")