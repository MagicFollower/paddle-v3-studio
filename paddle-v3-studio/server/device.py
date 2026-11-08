"""设备探测：GPU 优先，失败降级 CPU，降级原因如实记录并暴露给管理界面。"""
import json
import threading
from pathlib import Path

from config import DATA

_state = None
_lock = threading.Lock()


def _probe_gpu():
    """返回 (ok, detail)。真做一次 GPU 张量运算，不只看编译旗标。"""
    import paddle
    if not paddle.device.is_compiled_with_cuda():
        return False, "当前安装的 paddlepaddle 是 CPU 构建（不含 CUDA 支持）"
    try:
        count = paddle.device.cuda.device_count()
    except Exception as e:
        return False, f"CUDA 设备枚举失败：{e}"
    if count == 0:
        return False, "未检测到可用 CUDA 设备（无 NVIDIA 显卡或驱动不可用）"
    try:
        name = paddle.device.cuda.get_device_name(0)
    except Exception:
        name = "CUDA device 0"
    try:
        place = paddle.CUDAPlace(0)
        x = paddle.to_tensor([1.0, 2.0], place=place)
        y = (x * 2).numpy()
        assert float(y[1]) == 4.0
        return True, name
    except Exception as e:
        return False, f"GPU 张量运算自检失败：{str(e)[:300]}"


def detect_device(preference: str = "auto", force: bool = False) -> dict:
    """preference: auto/gpu/cpu。结果落盘 data/device.json，重启后仍可显示上次探测。"""
    global _state
    with _lock:
        if _state is not None and not force and _state.get("requested") == preference:
            return _state
        info = {"requested": preference, "device": "cpu", "device_name": None,
                "fallback": False, "reason": None, "paddle_version": None, "cuda_compiled": False}
        try:
            import paddle
            info["paddle_version"] = paddle.__version__
            info["cuda_compiled"] = bool(paddle.device.is_compiled_with_cuda())
            if preference == "cpu":
                info["reason"] = "配置指定使用 CPU"
            else:
                ok, detail = _probe_gpu()
                if ok:
                    info.update(device="gpu", device_name=detail)
                    paddle.set_device("gpu:0")
                else:
                    info.update(fallback=(preference != "cpu"), reason=detail)
                    paddle.set_device("cpu")
                    if preference == "gpu":
                        info["reason"] = f"配置要求 GPU 但不可用，已降级 CPU：{detail}"
        except Exception as e:
            info.update(fallback=True, reason=f"Paddle 初始化失败：{str(e)[:300]}")
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "device.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        _state = info
        return info


def current_device() -> str:
    info = detect_device()
    return "gpu:0" if info["device"] == "gpu" else "cpu"