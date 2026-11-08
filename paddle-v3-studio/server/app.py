"""FastAPI 主程序：/api + 同源直出 dist。只绑 127.0.0.1，写盘只碰 data/。"""
import io
import json
import os
import socket
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfgmod  # noqa: E402
import device as devmod  # noqa: E402
import jobs  # noqa: E402
import pipeline  # noqa: E402
import store  # noqa: E402
import verify  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
MAX_UPLOAD = 60 * 1024 * 1024

app = FastAPI(title="Paddle V3 Studio")


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": {"code": exc.detail if isinstance(exc.detail, str) else "ERROR",
                                           "message": str(exc.detail)}})


# ---------- 概览 / 健康 / 设备 ----------

@app.get("/api/health")
def health():
    return {"ok": True, "service": "paddle-v3-studio"}


@app.get("/api/overview")
def overview():
    docs = store.list_documents()
    contracts = store.list_contracts()
    return {
        "documents": len(docs),
        "parsed": sum(1 for d in docs if d["parsed"]),
        "contracts": len(contracts),
        "contractsParsed": sum(1 for c in contracts if c.get("status") == "parsed"),
        "jobsRunning": sum(1 for j in jobs.list_jobs() if j["status"] in ("queued", "running")),
    }


@app.get("/api/model/status")
def model_status():
    cfg = cfgmod.load_config()
    dev = devmod.detect_device(cfg["model"]["device"])
    models = {}
    for key in ("layout_model", "det_model", "rec_model", "table_model"):
        name = cfg["model"][key]
        models[key] = {"name": name, "present": (
            (pipeline.MODELS / "official_models" / name).exists()
            or (pipeline.MODELS / name).exists())}
    return {
        "device": dev, "models": models,
        "pipeline": "PP-StructureV3",
        "paddleocrVersion": _pkg_version("paddleocr"),
        "offline": True,
        "parsedCount": sum(1 for d in store.list_documents() if d["parsed"]),
    }


def _pkg_version(name):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


@app.post("/api/model/reprobe")
def model_reprobe():
    cfg = cfgmod.load_config()
    dev = devmod.detect_device(cfg["model"]["device"], force=True)
    pipeline.invalidate()
    return {"device": dev}


# ---------- 配置 ----------

@app.get("/api/schema")
def schema():
    return cfgmod.SCHEMA


@app.get("/api/config")
def get_config():
    return cfgmod.load_config()


@app.post("/api/config")
async def post_config(request: Request):
    # 纯 JSON 文件存储：只校验+写盘，不在此触发流水线/设备重建（避免阻塞保存）。
    # 配置生效是懒式的：get_pipeline 下次解析按 key 变化自动重建，
    # detect_device 在 preference 变化时自动重探。
    patch = await request.json()
    try:
        merged = cfgmod.save_config(patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return merged


@app.post("/api/config/validate")
async def validate_config(request: Request):
    patch = await request.json()
    errs = cfgmod.validate_config(patch)
    if errs:
        raise HTTPException(400, "; ".join(errs))
    return {"ok": True}


# ---------- 图片文档 ----------

def sniff_image(data: bytes):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if data.startswith(b"BM"):
        return "image/bmp", ".bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None, None


@app.get("/api/documents")
def list_documents(q: str = "", status: str = ""):
    return {"items": store.list_documents(q, status)}


@app.post("/api/documents", status_code=201)
async def upload_document(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "文件超过 60MB 上限")
    mime, ext = sniff_image(data)
    if not mime:
        raise HTTPException(400, "仅支持 PNG/JPEG/BMP/WebP 图片（文件头校验）")
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except Exception:
        raise HTTPException(400, "图片文件头损坏，无法读取尺寸")
    doc_id = store.new_id("doc")
    disk_name = f"{doc_id}{ext}"
    store.UPLOADS.mkdir(parents=True, exist_ok=True)
    (store.UPLOADS / disk_name).write_bytes(data)
    store.add_document(doc_id, file.filename or "unnamed", mime, width, height, len(data), disk_name)
    job = jobs.start_image_job(doc_id)
    return {"id": doc_id, "jobId": job["id"], "width": width, "height": height}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    d = store.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    return d


@app.get("/api/documents/{doc_id}/image")
def document_image(doc_id: str):
    d = store.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    p = store.UPLOADS / d["diskName"]
    if not p.exists():
        raise HTTPException(404, "图片文件缺失")
    return FileResponse(p, media_type=d["mime"])


@app.get("/api/documents/{doc_id}/result")
def document_result(doc_id: str):
    d = store.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    payload = store.load_parse(doc_id)
    if not payload:
        raise HTTPException(409, "尚未解析完成")
    slim = {k: v for k, v in payload.items() if k != "raw"}
    slim["raw"] = {"available": True}
    return slim


@app.get("/api/documents/{doc_id}/raw")
def document_raw(doc_id: str):
    payload = store.load_parse(doc_id)
    if not payload:
        raise HTTPException(409, "尚未解析完成")
    return payload.get("raw", {})


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not store.delete_document(doc_id):
        raise HTTPException(404, "文档不存在")
    return {"ok": True}


@app.post("/api/documents/{doc_id}/favorite")
async def favorite(doc_id: str, request: Request):
    body = await request.json()
    if not store.get_document(doc_id):
        raise HTTPException(404, "文档不存在")
    store.set_favorite(doc_id, bool(body.get("on", True)))
    return {"ok": True}


# ---------- 任务 ----------

@app.post("/api/parse", status_code=202)
async def parse(request: Request):
    body = await request.json()
    doc_id = body.get("docId")
    if not doc_id or not store.get_document(doc_id):
        raise HTTPException(404, "文档不存在")
    job = jobs.start_image_job(doc_id)
    return {"jobId": job["id"], "status": job["status"]}


@app.get("/api/jobs")
def list_jobs(refId: str = ""):
    return {"items": jobs.list_jobs(refId or None)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = jobs.get_job(job_id)
    if not j:
        raise HTTPException(404, "任务不存在")
    return j


@app.get("/api/stages")
def stages():
    return {"image": jobs.IMAGE_STAGES, "contract": jobs.CONTRACT_STAGES}


# ---------- 合同 ----------

@app.get("/api/contracts")
def list_contracts():
    return {"items": store.list_contracts()}


@app.get("/api/entries")
def query_entries(request: Request):
    return store.query_entries(dict(request.query_params))


@app.post("/api/contracts/upload", status_code=201)
async def upload_contract(file: UploadFile = File(...)):
    name = store.safe_name(file.filename or "contract")
    ext = Path(name).suffix.lower()
    if ext not in (".docx", ".doc", ".pdf"):
        raise HTTPException(400, "仅支持 .docx / .doc / .pdf 合同文件")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "文件超过 60MB 上限")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise HTTPException(400, "PDF 文件头校验失败")
    if ext in (".docx",) and not data.startswith(b"PK"):
        raise HTTPException(400, "DOCX 文件头校验失败")
    cid = store.new_id("ct")
    work = store.CONTRACTS / cid
    work.mkdir(parents=True, exist_ok=True)
    disk_name = f"original{ext}"
    (work / disk_name).write_bytes(data)
    entry = {"id": cid, "name": name, "ext": ext, "size": len(data), "diskName": disk_name,
             "uploadedAt": store._now(), "status": "parsing", "pageCount": 0,
             "contractNo": None, "verifyStatus": None}
    store.add_contract(entry)
    job = jobs.start_contract_job(cid)
    return {"id": cid, "jobId": job["id"]}


@app.get("/api/contracts/{contract_id}")
def get_contract(contract_id: str):
    e = store.get_contract(contract_id)
    if not e:
        raise HTTPException(404, "合同条目不存在")
    return e


@app.get("/api/contracts/{contract_id}/result")
def contract_result(contract_id: str):
    if not store.get_contract(contract_id):
        raise HTTPException(404, "合同条目不存在")
    payload = store.load_contract_result(contract_id)
    if not payload:
        raise HTTPException(409, "尚未解析完成")
    return payload


@app.get("/api/contracts/{contract_id}/pages/{page_no}/image")
def contract_page_image(contract_id: str, page_no: int):
    e = store.get_contract(contract_id)
    if not e:
        raise HTTPException(404, "合同条目不存在")
    p = store.CONTRACTS / contract_id / "pages" / f"page-{page_no:03d}.png"
    if not p.exists():
        raise HTTPException(404, "页图不存在")
    return FileResponse(p, media_type="image/png")


@app.post("/api/contracts/{contract_id}/parse", status_code=202)
def contract_parse(contract_id: str):
    if not store.get_contract(contract_id):
        raise HTTPException(404, "合同条目不存在")
    store.update_contract(contract_id, {"status": "parsing"})
    job = jobs.start_contract_job(contract_id)
    return {"jobId": job["id"], "status": job["status"]}


@app.post("/api/contracts/{contract_id}/reverify")
def contract_reverify(contract_id: str):
    if not store.get_contract(contract_id):
        raise HTTPException(404, "合同条目不存在")
    try:
        return jobs.reverify_contract(contract_id)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.delete("/api/contracts/{contract_id}")
def delete_contract(contract_id: str):
    if not store.delete_contract(contract_id):
        raise HTTPException(404, "合同条目不存在")
    return {"ok": True}


@app.get("/api/source/status")
def source_status():
    cfg = cfgmod.load_config()
    return verify.probe_source(cfg["contract"]["source_url"])


# ---------- 静态 ----------

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "no such api")
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")


def main():
    import uvicorn
    base = int(os.environ.get("PORT", "8390"))
    port = None
    for p in range(base, base + 41):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                port = p
                break
            except OSError:
                continue
    if port is None:
        print(f"[server] {base}–{base + 40} 全被占用。手动指定：PORT=8621 python server/app.py")
        sys.exit(1)
    if os.environ.get("NO_PORT_FILE") != "1":
        store.DATA.mkdir(parents=True, exist_ok=True)
        (store.DATA / ".port").write_text(str(port), encoding="utf-8")
    print(f"[server] http://127.0.0.1:{port}/  (dist={'yes' if DIST.exists() else 'no'})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()