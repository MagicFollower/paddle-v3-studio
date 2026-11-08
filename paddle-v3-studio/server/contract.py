"""合同文件处理：docx/pdf → 逐页图片 → 合同号与明细表格提取。

DOCX 转 PDF 走本机 WPS COM（KWPS.Application），不依赖 Office/LibreOffice。
PDF 逐页渲染用 pypdfium2（纯本地，无外部二进制）。
"""
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import config as cfgmod

# ---------- DOCX → PDF（WPS COM） ----------

def docx_to_pdf(docx_path: Path, pdf_path: Path):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        try:
            word = win32com.client.Dispatch("KWPS.Application")
        except Exception:
            word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        try:
            word.DisplayAlerts = 0
        except Exception:
            pass
        doc = word.Documents.Open(str(docx_path.resolve()))
        try:
            doc.ExportAsFixedFormat(str(pdf_path.resolve()), 17)
        except Exception:
            try:
                doc.SaveAs2(str(pdf_path.resolve()), FileFormat=17)
            except Exception:
                doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise RuntimeError("WPS 未产出 PDF 文件")
    finally:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()


# ---------- PDF → 逐页 PNG ----------

def pdf_to_pages(pdf_path: Path, out_dir: Path, dpi: int) -> list:
    import pypdfium2 as pdfium

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=dpi / 72.0)
            pil = bitmap.to_pil()
            dest = out_dir / f"page-{i + 1:03d}.png"
            pil.save(dest)
            pages.append({"page": i + 1, "file": dest.name,
                          "width": pil.width, "height": pil.height})
            page.close()
    finally:
        pdf.close()
    return pages


def convert_to_pages(src: Path, work_dir: Path) -> tuple:
    """返回 (pages 元信息列表, 转换方式)。一个文件一个条目，逐页独立图片。"""
    cfg = cfgmod.load_config()
    dpi = int(cfg["contract"]["page_dpi"])
    ext = src.suffix.lower()
    pages_dir = work_dir / "pages"
    if ext == ".pdf":
        return pdf_to_pages(src, pages_dir, dpi), "pypdfium2"
    if ext in (".docx", ".doc"):
        pdf_path = work_dir / "converted.pdf"
        docx_to_pdf(src, pdf_path)
        return pdf_to_pages(pdf_path, pages_dir, dpi), "wps-com+pypdfium2"
    raise ValueError(f"不支持的合同文件类型：{ext}（仅支持 .docx/.doc/.pdf）")


# ---------- 合同号提取 ----------

_NO_BODY = r"[A-Za-z0-9][A-Za-z0-9\-_/\.（）()第号年月日]*"
CONTRACT_NO_PATTERNS = [
    re.compile(r"(?:合同编号|合同号码|合同号|协议编号|采购单号|订单编号)\s*[:：]?\s*(" + _NO_BODY + r")"),
    re.compile(r"(?:Contract\s*(?:No|Number)|CONTRACT\s*NO)\s*[.:：]?\s*(" + _NO_BODY + r")", re.I),
    re.compile(r"(?:^|\s)编号\s*[:：]\s*(" + _NO_BODY + r")"),
    re.compile(r"(?:^|\s)No\s*[.:]\s*([A-Za-z0-9][A-Za-z0-9\-_/\.]*)"),
]
_LABEL_ONLY = re.compile(r"^(合同编号|合同号码|合同号|协议编号|编号|Contract\s*No\.?)\s*[:：]?\s*$", re.I)
_BARE_NO = re.compile(r"^[A-Za-z]{0,6}[-_]?\d{2,}[-A-Za-z0-9_/\.第号年月日]*$")


def extract_contract_no(pages_ocr: list) -> dict:
    """pages_ocr: [{page, ocr:[{text,bbox,bboxNorm,poly}]}]。返回首个命中 + 全部候选。"""
    candidates = []
    for pg in pages_ocr:
        lines = pg.get("ocr", [])
        for i, line in enumerate(lines):
            text = (line.get("text") or "").strip()
            for pat in CONTRACT_NO_PATTERNS:
                m = pat.search(text)
                if m:
                    candidates.append({
                        "page": pg["page"], "number": m.group(1).strip(),
                        "lineText": text, "bbox": line.get("bbox"),
                        "bboxNorm": line.get("bboxNorm"), "poly": line.get("poly"),
                        "source": "same-line",
                    })
                    break
            else:
                if _LABEL_ONLY.match(text) and i + 1 < len(lines):
                    nxt = lines[i + 1]
                    nxt_text = (nxt.get("text") or "").strip()
                    if _BARE_NO.match(nxt_text):
                        candidates.append({
                            "page": pg["page"], "number": nxt_text,
                            "lineText": f"{text} {nxt_text}",
                            "bbox": nxt.get("bbox"), "bboxNorm": nxt.get("bboxNorm"),
                            "poly": nxt.get("poly"), "source": "next-line",
                        })
    return {"found": candidates[0] if candidates else None, "candidates": candidates}


# ---------- 表格 HTML → 结构化条目 ----------

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            a = dict(attrs)
            self._cell = {"text": "", "rowspan": int(a.get("rowspan", 1) or 1),
                          "colspan": int(a.get("colspan", 1) or 1)}

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._cell["text"] = self._cell["text"].strip()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def html_table_to_grid(html: str) -> list:
    p = _TableParser()
    p.feed(html or "")
    grid, pending = [], {}
    for row in p.rows:
        out, col = [], 0
        cells = list(row)
        while cells or any(r >= 0 for r in pending.values()):
            while pending.get(col, 0) > 0:
                out.append(None)
                pending[col] -= 1
                col += 1
            if not cells:
                break
            c = cells.pop(0)
            for k in range(c["colspan"]):
                while pending.get(col, 0) > 0:
                    out.append(None)
                    pending[col] -= 1
                    col += 1
                out.append(c["text"])
                if c["rowspan"] > 1:
                    pending[col] = c["rowspan"] - 1
                col += 1
        grid.append(out)
    return grid


_COL_HINTS = {
    "name": ["名称", "品名", "产品", "货物", "商品", "项目", "物料", "品名规格"],
    "spec": ["规格", "型号"],
    "unit": ["单位"],
    "qty": ["数量"],
    "price": ["单价"],
    "amount": ["金额", "总价", "小计"],
    "no": ["序号", "编号"],
}


def _match_col(header: str):
    h = (header or "").strip()
    for key, hints in _COL_HINTS.items():
        if any(x in h for x in hints):
            return key
    return None


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _num(s):
    if s is None:
        return None
    m = _NUM.search(str(s).replace(",", "").replace("，", ""))
    return float(m.group()) if m else None


def table_to_entries(html: str) -> dict:
    grid = html_table_to_grid(html)
    if not grid:
        return {"headers": [], "entries": [], "totalRow": None}
    header_idx, colmap = None, {}
    for i, row in enumerate(grid[:3]):
        cm = {}
        for j, cell in enumerate(row):
            key = _match_col(cell)
            if key and key not in cm:
                cm[key] = j
        if "name" in cm and ("qty" in cm or "amount" in cm or "price" in cm):
            header_idx, colmap = i, cm
            break
    if header_idx is None:
        return {"headers": [str(c) if c is not None else "" for c in grid[0]],
                "entries": [], "totalRow": None}
    headers = [str(c) if c is not None else "" for c in grid[header_idx]]
    entries, total_row = [], None
    for row in grid[header_idx + 1:]:
        def get(key):
            j = colmap.get(key)
            return row[j] if j is not None and j < len(row) else None
        joined = "".join(str(c or "") for c in row)
        if re.search(r"合\s*计|总\s*计|总\s*金\s*额|合\s*同\s*总\s*价", joined):
            total_row = {"text": joined, "amount": _num(get("amount"))}
            continue
        name = get("name")
        if not name or not str(name).strip():
            continue
        entries.append({
            "no": get("no"), "name": str(name).strip(), "spec": get("spec"),
            "unit": get("unit"), "qty": _num(get("qty")), "qtyText": get("qty"),
            "price": _num(get("price")), "priceText": get("price"),
            "amount": _num(get("amount")), "amountText": get("amount"),
        })
    return {"headers": headers, "entries": entries, "totalRow": total_row}