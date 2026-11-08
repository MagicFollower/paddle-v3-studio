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


_CONFUSABLE = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})


def _canon(s: str, normalize: bool) -> str:
    """跨页比对/投票用的归一化键：去空白、可选易混字符替换、转大写。"""
    s = re.sub(r"\s+", "", s or "")
    if normalize:
        s = s.translate(_CONFUSABLE)
    return s.upper()


def _clean_number(s: str, normalize: bool) -> str:
    """输出/查询用编号：trim，可选易混字符替换（保留大小写）。"""
    s = (s or "").strip()
    return s.translate(_CONFUSABLE) if normalize else s


def _read_multiline_number(lines: list, i: int):
    """标签独占一行时，从其后 1~2 行读出编号（含编号本身被折成两行的情况）。
    返回 (number, 用于定位的行索引, source) 或 None。"""
    if i + 1 >= len(lines):
        return None
    nxt = (lines[i + 1].get("text") or "").strip()
    nxt2 = (lines[i + 2].get("text") or "").strip() if i + 2 < len(lines) else None
    # 首行以连接符结尾（如 HT-2026-）疑似编号被折行，优先与次行拼接；
    # 否则 _BARE_NO 允许尾部连字符，会把半截编号误判为完整。
    if nxt2 is not None and re.search(r"[-_/]$", nxt):
        for joined in (nxt + nxt2, nxt + "-" + nxt2):
            if _BARE_NO.match(joined):
                return joined, i + 1, "split-line"
    if _BARE_NO.match(nxt):
        return nxt, i + 1, "next-line"
    if nxt2 is not None and re.match(r"^[A-Za-z0-9][A-Za-z0-9\-_/\.]*$", nxt):
        for joined in (nxt + nxt2, nxt + "-" + nxt2):
            if _BARE_NO.match(joined):
                return joined, i + 1, "split-line"
    return None


def _select_found(candidates: list, cross: bool, prefer_first: bool, normalize: bool):
    if not candidates:
        return None
    if not cross:
        return candidates[0]   # 候选按页序排列，首个即最早页
    # 跨页开启：多数投票；平票时（若首页优先）先看是否出现在最早页，再取最早出现者
    min_page = min(c["page"] for c in candidates)
    first_idx, counts, on_min_page = {}, {}, {}
    for idx, c in enumerate(candidates):
        k = _canon(c["number"], normalize)
        counts[k] = counts.get(k, 0) + 1
        first_idx.setdefault(k, idx)
        if c["page"] == min_page:
            on_min_page[k] = True

    def score(k):
        return (counts[k], (1 if on_min_page.get(k) else 0) if prefer_first else 0, -first_idx[k])

    best = max(counts, key=score)
    return candidates[first_idx[best]]


def extract_contract_no(pages_ocr: list, options: dict = None) -> dict:
    """pages_ocr: [{page, ocr:[{text,bbox,bboxNorm,poly,confidence}]}]。

    匹配与跨页开关（默认全开）：
      match_single_line  单行匹配：标签与编号同在一行
      match_multi_line   多行匹配：标签独占一行、编号在下一行或被折成两行
      cross_page_check   跨页准确性校验：统计各页出现、判定一致性、多数投票选定
    准确性增强开关：
      min_no_confidence      候选行 OCR 置信度下限（低于则丢弃，默认 0.6）
      no_format_regex        编号格式白名单正则（fullmatch，空=不启用）
      prefer_first_page      选定/平票时优先最早页命中（默认开）
      normalize_confusables  跨页比对与输出编号做 O→0/I,l→1 归一化（默认关）
    均可取自 config.contract，或被 options 覆盖。
    """
    cfg = cfgmod.load_config()["contract"]
    opt = options or {}

    def get(key, default):
        return opt.get(key, cfg.get(key, default))

    single = get("match_single_line", True)
    multi = get("match_multi_line", True)
    cross = get("cross_page_check", True)
    min_conf = float(get("min_no_confidence", 0.6))
    prefer_first = get("prefer_first_page", True)
    normalize = get("normalize_confusables", False)
    fmt = (get("no_format_regex", "") or "").strip()
    fmt_re = None
    if fmt:
        try:
            fmt_re = re.compile(fmt)
        except re.error:
            fmt_re = None   # 非法正则不启用过滤（config 校验会另行报错）

    raw = []
    for pg in pages_ocr:
        lines = pg.get("ocr", [])
        for i, line in enumerate(lines):
            text = (line.get("text") or "").strip()
            matched = False
            if single:
                for pat in CONTRACT_NO_PATTERNS:
                    m = pat.search(text)
                    if m:
                        raw.append({
                            "page": pg["page"], "number": m.group(1).strip(),
                            "lineText": text, "bbox": line.get("bbox"),
                            "bboxNorm": line.get("bboxNorm"), "poly": line.get("poly"),
                            "confidence": line.get("confidence"), "source": "same-line",
                        })
                        matched = True
                        break
            if multi and not matched and _LABEL_ONLY.match(text):
                read = _read_multiline_number(lines, i)
                if read:
                    number, loc, source = read
                    loc_line = lines[loc]
                    raw.append({
                        "page": pg["page"], "number": number,
                        "lineText": f"{text} {number}", "bbox": loc_line.get("bbox"),
                        "bboxNorm": loc_line.get("bboxNorm"), "poly": loc_line.get("poly"),
                        "confidence": loc_line.get("confidence"), "source": source,
                    })

    candidates, dropped_conf, dropped_fmt = [], 0, 0
    for c in raw:
        conf = c.get("confidence")
        if conf is not None and conf < min_conf:
            dropped_conf += 1
            continue
        if fmt_re is not None and not fmt_re.fullmatch(c["number"]):
            dropped_fmt += 1
            continue
        candidates.append(c)

    found = _select_found(candidates, cross, prefer_first, normalize)
    if found and normalize:
        found = dict(found)
        found["numberRaw"] = found["number"]
        found["number"] = _clean_number(found["number"], True)

    occurrences = [{"page": c["page"], "number": c["number"], "source": c["source"],
                    "confidence": c.get("confidence")} for c in candidates]
    distinct, seen = [], set()
    for c in candidates:
        k = _canon(c["number"], normalize)
        if k not in seen:
            seen.add(k)
            distinct.append(_clean_number(c["number"], normalize))
    pages = sorted({c["page"] for c in candidates})
    cross_page = {
        "enabled": bool(cross),
        "occurrences": occurrences,
        "pages": pages,
        "distinctNumbers": distinct,
        "occurrenceCount": len(candidates),
        "consistent": (len(distinct) <= 1) if cross else None,
        "chosenBy": "majority" if cross else "first",
        "preferFirstPage": bool(prefer_first),
        "normalizeConfusables": bool(normalize),
        "filtered": {"confidence": dropped_conf, "format": dropped_fmt,
                     "total": len(raw) - len(candidates)},
    }
    return {"found": found, "candidates": candidates, "crossPage": cross_page}


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


def table_to_entries(html: str, fallback: dict = None) -> dict:
    grid = html_table_to_grid(html)
    if not grid:
        return {"headers": [], "entries": [], "totalRow": None,
                "colmap": (fallback or {}).get("colmap")}
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
        # 跨页续表：本页无表头则沿用上一页列映射，整页按数据行处理
        if not (fallback and fallback.get("colmap")):
            return {"headers": [str(c) if c is not None else "" for c in grid[0]],
                    "entries": [], "totalRow": None, "colmap": None}
        colmap = fallback["colmap"]
        headers = fallback.get("headers") or [str(c) if c is not None else "" for c in grid[0]]
        data_rows = grid
    else:
        headers = [str(c) if c is not None else "" for c in grid[header_idx]]
        data_rows = grid[header_idx + 1:]
    entries, total_row = [], None
    for row in data_rows:
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
    return {"headers": headers, "entries": entries, "totalRow": total_row, "colmap": colmap}