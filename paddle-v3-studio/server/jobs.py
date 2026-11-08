"""任务引擎：内存任务表 + 单工作线程（模型推理串行），产物落盘。"""
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config as cfgmod
import store
from pipeline import PipelineError

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="v3-job")
_jobs = {}
_lock = threading.Lock()

IMAGE_STAGES = [
    {"key": "prepare", "label": "准备流水线", "chip": "准备"},
    {"key": "predict", "label": "V3 流水线推理（版面+OCR+表格）", "chip": "推理"},
    {"key": "persist", "label": "产物落盘", "chip": "落盘"},
]
CONTRACT_STAGES = [
    {"key": "convert", "label": "文件转逐页图片", "chip": "转图"},
    {"key": "predict", "label": "逐页 V3 流水线推理", "chip": "推理"},
    {"key": "extract", "label": "合同号与明细提取", "chip": "提取"},
    {"key": "verify", "label": "对照数据源校验", "chip": "校验"},
    {"key": "persist", "label": "产物落盘", "chip": "落盘"},
]


def _new_job(kind: str, ref_id: str, stages: list) -> dict:
    job = {
        "id": f"job-{uuid.uuid4().hex[:8]}", "kind": kind, "refId": ref_id,
        "status": "queued", "progress": 0, "stage": None,
        "stagePath": [], "stages": stages, "logs": [],
        "error": None, "createdAt": time.time(), "finishedAt": None,
    }
    with _lock:
        _jobs[job["id"]] = job
    return job


def _log(job, stage, msg):
    job["stage"] = stage
    if stage not in job["stagePath"]:
        job["stagePath"].append(stage)
    job["logs"].append({"t": round(time.time() - job["createdAt"], 3), "stage": stage, "msg": msg})


def _fail(job, code, message, hint=None):
    job.update(status="failed", error={"code": code, "message": message, "hint": hint},
               finishedAt=time.time())


def get_job(job_id):
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def list_jobs(ref_id=None):
    with _lock:
        items = [dict(j) for j in _jobs.values()]
    if ref_id:
        items = [j for j in items if j["refId"] == ref_id]
    return sorted(items, key=lambda j: j["createdAt"], reverse=True)


def active_job_for(ref_id):
    for j in list_jobs(ref_id):
        if j["status"] in ("queued", "running"):
            return j
    return None


# ---------- 图片解析任务 ----------

def start_image_job(doc_id: str) -> dict:
    exist = active_job_for(doc_id)
    if exist:
        return exist
    job = _new_job("image", doc_id, IMAGE_STAGES)

    def run():
        import device as devmod
        import pipeline
        job["status"] = "running"
        try:
            _log(job, "prepare", "探测设备并加载 PP-StructureV3 流水线")
            cfg = cfgmod.load_config()
            dev = devmod.detect_device(cfg["model"]["device"], force=True)
            if dev["fallback"]:
                _log(job, "prepare", f"GPU 不可用，降级 CPU：{dev['reason']}")
            pipeline.get_pipeline()
            job["progress"] = 15
            doc = store.get_document(doc_id)
            img_path = store.UPLOADS / doc["diskName"]
            _log(job, "predict", f"推理 {doc['name']}（{doc['width']}×{doc['height']}）")
            t0 = time.time()
            out = pipeline.predict_image(img_path)
            out["timings"] = {"predictMs": round((time.time() - t0) * 1000)}
            job["progress"] = 85
            _log(job, "persist", "写 data/parse 产物")
            payload = {"docId": doc_id, "real": True, "parsedAt": store._now(), **out}
            store.save_parse(doc_id, payload)
            job["progress"] = 100
            job["status"] = "done"
            job["finishedAt"] = time.time()
            _log(job, "persist", f"完成：版面 {out['counts']['layout']} 块 / OCR {out['counts']['ocr']} 行 / 表格 {out['counts']['tables']} 个")
        except PipelineError as e:
            _fail(job, e.code, str(e), e.hint)
        except Exception as e:
            traceback.print_exc()
            _fail(job, "INTERNAL", str(e)[:400])

    _executor.submit(run)
    return job


# ---------- 合同解析任务 ----------

def start_contract_job(contract_id: str) -> dict:
    exist = active_job_for(contract_id)
    if exist:
        return exist
    job = _new_job("contract", contract_id, CONTRACT_STAGES)

    def run():
        import contract as ct
        import device as devmod
        import pipeline
        import verify
        job["status"] = "running"
        entry = store.get_contract(contract_id)
        work_dir = store.CONTRACTS / contract_id
        src = work_dir / entry["diskName"]
        try:
            _log(job, "convert", f"转换 {entry['name']} 为逐页图片")
            pages, how = ct.convert_to_pages(src, work_dir)
            entry_update = {"pageCount": len(pages), "pages": pages, "convert": how}
            store.update_contract(contract_id, entry_update)
            _log(job, "convert", f"{how}：共 {len(pages)} 页")
            job["progress"] = 10

            cfg = cfgmod.load_config()
            dev = devmod.detect_device(cfg["model"]["device"], force=True)
            if dev["fallback"]:
                _log(job, "predict", f"GPU 不可用，降级 CPU：{dev['reason']}")
            pipeline.get_pipeline()
            page_results = []
            for i, pg in enumerate(pages):
                _log(job, "predict", f"推理第 {pg['page']}/{len(pages)} 页")
                out = pipeline.predict_image(work_dir / "pages" / pg["file"])
                out.pop("raw", None)
                page_results.append({"page": pg["page"], **out})
                job["progress"] = 10 + round(60 * (i + 1) / len(pages))

            _log(job, "extract", "提取合同号与明细表格")
            no_info = ct.extract_contract_no(page_results)
            tables, carry = [], None
            for pr in page_results:
                for t in pr.get("tables", []):
                    parsed = ct.table_to_entries(t.get("html", ""), fallback=carry,
                                                 cells=t.get("cellBoxesNorm"))
                    cm = parsed.pop("colmap", None)
                    if cm:
                        carry = {"headers": parsed.get("headers"), "colmap": cm}
                    tables.append({"page": pr["page"], "bbox": t.get("bbox"),
                                   "bboxNorm": t.get("bboxNorm"), **parsed})
                    t.pop("cellBoxesNorm", None)   # 单元格框仅用于定位，不持久化以免结果膨胀
            extracted = {"contractNo": no_info["found"], "noCandidates": no_info["candidates"],
                         "crossPage": no_info["crossPage"], "tables": tables}
            job["progress"] = 78

            _log(job, "verify", "对照 Spring Boot 数据源校验")
            try:
                report = verify.verify(extracted, cfg["contract"]["source_url"])
            except verify.SourceError as e:
                report = {"status": "source_unreachable", "contractNo": (no_info["found"] or {}).get("number"),
                          "checks": [{"key": "source", "label": "数据源可达", "ok": False, "detail": str(e)}],
                          "hint": e.hint, "itemComparison": []}
            job["progress"] = 90

            _log(job, "persist", "写合同解析产物")
            payload = {"contractId": contract_id, "parsedAt": store._now(),
                       "pages": page_results, "extracted": extracted, "report": report}
            store.save_contract_result(contract_id, payload)
            store.update_contract(contract_id, {
                "status": "parsed", "contractNo": (no_info["found"] or {}).get("number"),
                "verifyStatus": report["status"],
            })
            job["progress"] = 100
            job["status"] = "done"
            job["finishedAt"] = time.time()
            _log(job, "persist", f"完成：合同号 {(no_info['found'] or {}).get('number') or '未识别'} / 校验 {report['status']}")
        except PipelineError as e:
            store.update_contract(contract_id, {"status": "failed"})
            _fail(job, e.code, str(e), e.hint)
        except Exception as e:
            traceback.print_exc()
            store.update_contract(contract_id, {"status": "failed"})
            _fail(job, "INTERNAL", str(e)[:400])

    _executor.submit(run)
    return job


def reverify_contract(contract_id: str) -> dict:
    """只重跑校验（不重新推理），数据源补录后常用。"""
    import verify
    payload = store.load_contract_result(contract_id)
    if not payload:
        raise ValueError("该合同尚未解析")
    cfg = cfgmod.load_config()
    try:
        report = verify.verify(payload["extracted"], cfg["contract"]["source_url"])
    except verify.SourceError as e:
        report = {"status": "source_unreachable",
                  "contractNo": (payload["extracted"].get("contractNo") or {}).get("number"),
                  "checks": [{"key": "source", "label": "数据源可达", "ok": False, "detail": str(e)}],
                  "hint": e.hint, "itemComparison": []}
    payload["report"] = report
    store.save_contract_result(contract_id, payload)
    store.update_contract(contract_id, {"verifyStatus": report["status"]})
    return report