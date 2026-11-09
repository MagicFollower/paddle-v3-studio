# -*- coding: utf-8 -*-
"""测试专用：手动拉起本地 llama.exe serve（后端已改为纯 API 客户端，不再自行 spawn）。
仅供 check_studio / llm_benchmark 等判据脚本使用；生产由用户双击 llm-server.cmd 启动。"""
import os
import re
import subprocess
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LLMS = ROOT.parent.parent / "MODEL-V3" / "llms"
BIN = LLMS / "bin" / ("llama.exe" if os.name == "nt" else "llama")
MODEL = LLMS / "Spark-X2.6-1.7B-Q4_K_M.gguf"


class LocalLLM:
    def __init__(self, port=9931, model=None, alias="spark-x2.6"):
        self.port = port
        self.model = Path(model) if model else MODEL
        self.alias = alias
        self.proc = None

    def start(self, timeout=90):
        if not BIN.exists() or not self.model.exists():
            raise RuntimeError(f"本地 llama/bin 或模型缺失：{BIN} / {self.model}")
        ngl = 0
        try:
            out = subprocess.run([str(BIN), "serve", "--list-devices"], capture_output=True,
                                 text=True, timeout=30, encoding="utf-8", errors="replace").stdout
            if re.search(r"(CUDA|ROCm|Metal|Vulkan)\w*\s*:", out, re.I):
                ngl = 99
        except Exception:
            pass
        args = [str(BIN), "serve", "-m", str(self.model), "--host", "127.0.0.1",
                "--port", str(self.port), "-c", "4096", "-ngl", str(ngl),
                "--no-webui", "--alias", self.alias]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, cwd=str(BIN.parent))
        base = f"http://127.0.0.1:{self.port}"
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError("llama serve 提前退出")
            try:
                if requests.get(base + "/health", timeout=3).ok:
                    return base
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("llama serve 启动超时")

    def stop(self):
        if self.proc is not None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                                   capture_output=True, timeout=15)
                else:
                    self.proc.terminate()
                    self.proc.wait(timeout=10)
            except Exception:
                pass
            self.proc = None