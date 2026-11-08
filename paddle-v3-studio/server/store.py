"""落盘存储：上传件、解析产物、合同条目。写盘只碰 data/。"""
import json
import re
import threading
import uuid
from pathlib import Path

from config import DATA

UPLOADS = DATA / "uploads"
PARSE = DATA / "parse"
CONTRACTS = DATA / "contracts"

_lock = threading.Lock()


def _read_index(path: Path) -> list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _write_index(path: Path, items: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def safe_name(original: str) -> str:
    name = Path(original).name
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)[:120] or "unnamed"


# ---------- 图片文档 ----------

def add_document(doc_id: str, original: str, mime: str, width: int, height: int, size: int, disk_name: str):
    with _lock:
        idx = _read_index(UPLOADS / "index.json")
        idx.insert(0, {
            "id": doc_id, "name": safe_name(original), "mime": mime,
            "width": width, "height": height, "size": size,
            "diskName": disk_name, "uploadedAt": _now(), "favorite": False,
        })
        _write_index(UPLOADS / "index.json", idx)


def list_documents(q: str = "", status: str = "") -> list:
    idx = _read_index(UPLOADS / "index.json")
    out = []
    for d in idx:
        parsed = (PARSE / f"{d['id']}.parse.json").exists()
        d = dict(d, parsed=parsed)
        if q and q.lower() not in d["name"].lower():
            continue
        if status == "parsed" and not parsed:
            continue
        if status == "unparsed" and parsed:
            continue
        out.append(d)
    return out


def get_document(doc_id: str):
    for d in _read_index(UPLOADS / "index.json"):
        if d["id"] == doc_id:
            return dict(d, parsed=(PARSE / f"{doc_id}.parse.json").exists())
    return None


def set_favorite(doc_id: str, on: bool):
    with _lock:
        idx = _read_index(UPLOADS / "index.json")
        for d in idx:
            if d["id"] == doc_id:
                d["favorite"] = on
        _write_index(UPLOADS / "index.json", idx)


def delete_document(doc_id: str) -> bool:
    with _lock:
        idx = _read_index(UPLOADS / "index.json")
        keep = [d for d in idx if d["id"] != doc_id]
        if len(keep) == len(idx):
            return False
        _write_index(UPLOADS / "index.json", keep)
    for p in (UPLOADS.glob(f"{doc_id}.*"), ):
        for f in p:
            f.unlink(missing_ok=True)
    (PARSE / f"{doc_id}.parse.json").unlink(missing_ok=True)
    return True


def save_parse(doc_id: str, payload: dict):
    PARSE.mkdir(parents=True, exist_ok=True)
    (PARSE / f"{doc_id}.parse.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_parse(doc_id: str):
    p = PARSE / f"{doc_id}.parse.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


# ---------- 合同条目 ----------

def add_contract(entry: dict):
    with _lock:
        idx = _read_index(CONTRACTS / "index.json")
        idx.insert(0, entry)
        _write_index(CONTRACTS / "index.json", idx)


def update_contract(contract_id: str, patch: dict):
    with _lock:
        idx = _read_index(CONTRACTS / "index.json")
        for e in idx:
            if e["id"] == contract_id:
                e.update(patch)
        _write_index(CONTRACTS / "index.json", idx)


def list_contracts() -> list:
    return _read_index(CONTRACTS / "index.json")


def get_contract(contract_id: str):
    for e in _read_index(CONTRACTS / "index.json"):
        if e["id"] == contract_id:
            return e
    return None


def delete_contract(contract_id: str) -> bool:
    import shutil
    with _lock:
        idx = _read_index(CONTRACTS / "index.json")
        keep = [e for e in idx if e["id"] != contract_id]
        if len(keep) == len(idx):
            return False
        _write_index(CONTRACTS / "index.json", keep)
    shutil.rmtree(CONTRACTS / contract_id, ignore_errors=True)
    return True


def save_contract_result(contract_id: str, payload: dict):
    d = CONTRACTS / contract_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_contract_result(contract_id: str):
    p = CONTRACTS / contract_id / "result.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------- 统一文件条目查询（图片 + 合同）----------

def all_entries() -> list:
    entries = []
    for c in list_contracts():
        entries.append({
            "id": c["id"], "name": c["name"], "size": c.get("size"),
            "ext": (c.get("ext") or "").lstrip("."), "type": "contract",
            "pageCount": c.get("pageCount", 0), "uploadedAt": c.get("uploadedAt"),
            "contractNo": c.get("contractNo"), "parsed": c.get("status") == "parsed",
            "verifyStatus": c.get("verifyStatus"),
        })
    for d in list_documents():
        entries.append({
            "id": d["id"], "name": d["name"], "size": d.get("size"),
            "ext": Path(d["diskName"]).suffix.lstrip("."), "type": "image",
            "pageCount": 1, "uploadedAt": d.get("uploadedAt"),
            "contractNo": None, "parsed": bool(d.get("parsed")), "verifyStatus": None,
        })
    return entries


def query_entries(params: dict) -> dict:
    entries = all_entries()
    q = (params.get("q") or "").strip().lower()
    if q:
        entries = [e for e in entries if e["contractNo"] and q in e["contractNo"].lower()]
    date_from = params.get("dateFrom")
    date_to = params.get("dateTo")
    if date_from:
        entries = [e for e in entries if (e["uploadedAt"] or "") >= date_from]
    if date_to:
        entries = [e for e in entries if (e["uploadedAt"] or "")[:10] <= date_to]
    parsed = params.get("parsed")
    if parsed in ("true", True, "1"):
        entries = [e for e in entries if e["parsed"]]
    elif parsed in ("false", False, "0"):
        entries = [e for e in entries if not e["parsed"]]
    verify = params.get("verify")
    if verify:
        wanted = {v for v in verify.split(",") if v}
        entries = [e for e in entries if e["verifyStatus"] in wanted]
    etype = params.get("type")
    if etype in ("contract", "image"):
        entries = [e for e in entries if e["type"] == etype]
    entries.sort(key=lambda e: e["uploadedAt"] or "", reverse=True)
    total = len(entries)
    try:
        page = max(1, int(params.get("page", 1)))
        page_size = max(1, min(500, int(params.get("pageSize", 15))))
    except (TypeError, ValueError):
        page, page_size = 1, 15
    start = (page - 1) * page_size
    return {"items": entries[start:start + page_size], "total": total,
            "page": page, "pageSize": page_size}