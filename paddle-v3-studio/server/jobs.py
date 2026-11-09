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
    {"key": "llm_map", "label": "LLM 表头→业务字段映射", "chip": "映射"},
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


class JobCancelled(Exception):
    pass


def _check_cancel(job):
    if job.get("cancelRequested") or job["status"] == "cancelled":
        raise JobCancelled()


def _restore_ref(job):
    if job["kind"] == "contract":
        rid = job["refId"]
        store.update_contract(rid, {"status": "parsed" if store.load_contract_result(rid) else "uploaded"})


def _on_cancel(job):
    job.update(status="cancelled", finishedAt=time.time())
    _restore_ref(job)
    _log(job, job.get("stage") or "prepare", "任务已取消")


def cancel_job(job_id):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return None
    if job["status"] == "queued":
        _on_cancel(job)
    elif job["status"] == "running":
        job["cancelRequested"] = True   # 协作式：工作线程在检查点退出
    return dict(job)


# ---------- 解析前全模型可用性门控 ----------

class ModelUnavailable(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


def preflight_models() -> dict:
    """同步检测所有模型可用性：4 个 Paddle 模型本地就位 + LLM（启用时端点可达且暴露所配模型）。
    返回 {ok, models[], errors[]}；任一必需模型不可用 → ok=False。供设置页展示与解析前门控。"""
    import pipeline
    import llm as llmmod
    models = pipeline.model_availability()
    av = llmmod.availability()
    models.append({"key": "llm", "kind": "llm", "name": av.get("model") or "LLM",
                   "required": av.get("required", False), "available": av.get("available", False),
                   "present": av.get("reachable", False), "endpoint": av.get("endpoint"),
                   "reason": av.get("reason")})
    errors = [f"{m.get('name') or m['key']}：{m.get('reason') or '不可用'}"
              for m in models if m.get("required") and not m.get("available")]
    return {"ok": not errors, "models": models, "errors": errors}


def require_models() -> dict:
    pf = preflight_models()
    if not pf["ok"]:
        raise ModelUnavailable(pf["errors"])
    return pf


# ---------- 图片解析任务 ----------

def start_image_job(doc_id: str) -> dict:
    exist = active_job_for(doc_id)
    if exist:
        return exist
    require_models()   # 解析前同步门控：所有模型可用才放行
    job = _new_job("image", doc_id, IMAGE_STAGES)

    def run():
        import device as devmod
        import pipeline
        if job["status"] == "cancelled":
            return
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
            _check_cancel(job)
            out = pipeline.predict_image(img_path)
            _check_cancel(job)
            out["timings"] = {"predictMs": round((time.time() - t0) * 1000)}
            job["progress"] = 85
            _log(job, "persist", "写 data/parse 产物")
            payload = {"docId": doc_id, "real": True, "parsedAt": store._now(), **out}
            store.save_parse(doc_id, payload)
            job["progress"] = 100
            job["status"] = "done"
            job["finishedAt"] = time.time()
            _log(job, "persist", f"完成：版面 {out['counts']['layout']} 块 / OCR {out['counts']['ocr']} 行 / 表格 {out['counts']['tables']} 个")
        except JobCancelled:
            _on_cancel(job)
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
    require_models()   # 解析前同步门控：所有模型可用才放行
    job = _new_job("contract", contract_id, CONTRACT_STAGES)

    def run():
        import contract as ct
        import device as devmod
        import pipeline
        import verify
        if job["status"] == "cancelled":
            return
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
                _check_cancel(job)
                _log(job, "predict", f"推理第 {pg['page']}/{len(pages)} 页")
                out = pipeline.predict_image(work_dir / "pages" / pg["file"])
                out.pop("raw", None)
                page_results.append({"page": pg["page"], **out})
                job["progress"] = 10 + round(60 * (i + 1) / len(pages))

            _log(job, "extract", "提取合同号与明细表格")
            import llm as llmmod
            no_info = ct.extract_contract_no(page_results)
            llm_enabled = cfg.get("llm", {}).get("enabled", True)
            tables, carry = [], None
            for pr in page_results:
                for t in pr.get("tables", []):
                    html = t.get("html", "")
                    reg = ct.assess_regularity(html)
                    _log(job, "extract", f"第 {pr['page']} 页表格判定：{reg['layout']}"
                                         f"（{'规则→启发式精确解析' if reg['regular'] else '不规则→4B LLM 结构理解'}）")
                    method = "heuristic"
                    parsed = ct.table_to_entries(html, fallback=carry, cells=t.get("cellBoxesNorm"))
                    # 动态路由：不规则表格优先 4B LLM 结构理解；规则表格走启发式（空结果时 LLM 兜底）。
                    need_llm = (not reg["regular"]) or (not parsed.get("entries"))
                    if need_llm and html.strip() and llm_enabled:
                        _check_cancel(job)
                        try:
                            alt = llmmod.understand_table(html, cells=t.get("cellBoxesNorm"))
                            if alt.get("entries"):
                                parsed, method = alt, "llm-table"
                                _log(job, "extract", f"第 {pr['page']} 页 {reg['layout']} 表格经 4B LLM 结构理解抽取 {len(alt['entries'])} 条")
                                if not no_info.get("found") and alt.get("contractNo"):
                                    no_info["found"] = {"number": alt["contractNo"], "page": pr["page"], "source": "table-llm"}
                        except llmmod.LLMError as e:
                            _log(job, "extract", f"第 {pr['page']} 页 LLM 结构理解失败：{e}（保留启发式结果）")
                    cm = parsed.pop("colmap", None)
                    if cm:
                        carry = {"headers": parsed.get("headers"), "colmap": cm}
                    tables.append({"page": pr["page"], "bbox": t.get("bbox"),
                                   "bboxNorm": t.get("bboxNorm"), **parsed,
                                   "method": method, "layout": reg["layout"],
                                   "regular": reg["regular"], "regularityReasons": reg["reasons"]})
                    t.pop("cellBoxesNorm", None)   # 单元格框仅用于定位，不持久化以免结果膨胀
            extracted = {"contractNo": no_info["found"], "noCandidates": no_info["candidates"],
                         "crossPage": no_info["crossPage"], "tables": tables}
            job["progress"] = 72

            _check_cancel(job)
            _log(job, "llm_map", "本地大模型把中文表头映射为业务英文字段")
            mapped = llmmod.run_mapping(extracted, contract_id)
            if mapped.get("status") == "ok":
                _log(job, "llm_map", f"映射完成：{mapped.get('entryCount')} 条 / 模型 {mapped.get('engine')} / 字段 {[f['field'] for f in mapped.get('fields', [])]}")
            else:
                _log(job, "llm_map", f"映射跳过：{mapped.get('reason')}")
            job["progress"] = 82

            _check_cancel(job)
            _log(job, "verify", "对照 Spring Boot 数据源校验")
            try:
                report = verify.verify(extracted, cfg["contract"]["source_url"], mapped=mapped)
            except verify.SourceError as e:
                report = {"status": "source_unreachable", "contractNo": (no_info["found"] or {}).get("number"),
                          "checks": [{"key": "source", "label": "数据源可达", "ok": False, "detail": str(e)}],
                          "hint": e.hint, "itemComparison": []}
            job["progress"] = 90

            _log(job, "persist", "写合同解析产物")
            payload = {"contractId": contract_id, "parsedAt": store._now(),
                       "pages": page_results, "extracted": extracted, "report": report,
                       "mapped": mapped}
            store.save_contract_result(contract_id, payload)
            store.update_contract(contract_id, {
                "status": "parsed", "contractNo": (no_info["found"] or {}).get("number"),
                "verifyStatus": report["status"],
            })
            job["progress"] = 100
            job["status"] = "done"
            job["finishedAt"] = time.time()
            _log(job, "persist", f"完成：合同号 {(no_info['found'] or {}).get('number') or '未识别'} / 校验 {report['status']}")
        except JobCancelled:
            _on_cancel(job)
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
        report = verify.verify(payload["extracted"], cfg["contract"]["source_url"], mapped=payload.get("mapped"))
    except verify.SourceError as e:
        report = {"status": "source_unreachable",
                  "contractNo": (payload["extracted"].get("contractNo") or {}).get("number"),
                  "checks": [{"key": "source", "label": "数据源可达", "ok": False, "detail": str(e)}],
                  "hint": e.hint, "itemComparison": []}
    payload["report"] = report
    store.save_contract_result(contract_id, payload)
    store.update_contract(contract_id, {"verifyStatus": report["status"]})
    return report


def remap_contract(contract_id: str) -> dict:
    """只重跑 LLM 字段映射（不重新推理），映射配置或模型变化后常用。"""
    import llm as llmmod
    payload = store.load_contract_result(contract_id)
    if not payload:
        raise ValueError("该合同尚未解析")
    mapped = llmmod.run_mapping(payload.get("extracted") or {}, contract_id)
    payload["mapped"] = mapped
    store.save_contract_result(contract_id, payload)
    return mapped