"""双击即用的离线模型下载器（纯 Python 标准库，无需 venv / paddleocr）。

从百度 BOS 官方源下载 PP-StructureV3 所需的全部 10 个模型，按项目要求的布局存放：
    <模型库>/official_models/<模型名>/inference.json + inference.pdiparams + inference.yml

规则：
  * 目标模型目录已存在（含 inference.pdiparams）则跳过，不重复下载——中断后重跑即续传。
  * 模型库默认取 ../../MODEL-V3（相对本脚本，ASCII 路径）；可用 PADDLE_V3_MODEL_HOME 覆盖。
  * 仅安装阶段联网；下载完成后运行时零联网。

直接双击本文件即可（Windows 会用已关联的 Python 运行）。命令行亦可：
    python scripts/download_models.py
退出码 = 失败模型数（0 = 全部就位）。
"""
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# ---- 让双击出来的 Windows 控制台正确显示中文且不因 GBK 崩溃 ----
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent                       # paddle-v3-studio
DEFAULT_HOME = PROJECT_ROOT.parent.parent / "MODEL-V3"   # OCR-ALONE/MODEL-V3
MODEL_HOME = Path(os.environ.get("PADDLE_V3_MODEL_HOME", str(DEFAULT_HOME))).resolve()
DEST = MODEL_HOME / "official_models"

BASE_URL = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"

MODELS = [
    "PP-DocLayoutV3",
    "PP-OCRv5_server_det",
    "PP-OCRv5_server_rec",
    "SLANeXt_wired",
    "SLANet_plus",
    "PP-LCNet_x1_0_table_cls",
    "RT-DETR-L_wired_table_cell_det",
    "RT-DETR-L_wireless_table_cell_det",
    "PP-LCNet_x1_0_doc_ori",
    "PP-LCNet_x1_0_textline_ori",
]


def is_complete(model_dir: Path) -> bool:
    f = model_dir / "inference.pdiparams"
    return model_dir.is_dir() and f.exists() and f.stat().st_size > 0


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def report(blocknum, blocksize, total):
    done = blocknum * blocksize
    if total > 0:
        pct = min(100.0, done * 100.0 / total)
        bar = "#" * int(pct // 4)
        sys.stdout.write(f"\r    [{bar:<25}] {pct:5.1f}%  {human(min(done, total))}/{human(total)}")
        sys.stdout.flush()


def safe_extract(tar: tarfile.TarFile, dest: str):
    try:
        tar.extractall(dest, filter="data")   # Python 3.12+ 防路径穿越
    except TypeError:
        tar.extractall(dest)                 # 旧版本回退（源为官方可信 BOS）


def fetch_one(name: str) -> str:
    """返回 'skip' / 'ok' / 错误信息。"""
    target = DEST / name
    if is_complete(target):
        return "skip"
    url = f"{BASE_URL}/{name}_infer.tar"
    print(f"  下载 {url}")
    tmp = tempfile.mkdtemp(prefix="v3model_")
    try:
        arc = os.path.join(tmp, f"{name}_infer.tar")
        urllib.request.urlretrieve(url, arc, reporthook=report)
        sys.stdout.write("\n")
        if not tarfile.is_tarfile(arc):
            return "下载内容不是有效 tar 归档"
        extract_dir = os.path.join(tmp, "extract")
        os.makedirs(extract_dir, exist_ok=True)
        with tarfile.open(arc, "r:*") as tar:
            safe_extract(tar, extract_dir)
        # 包内顶层目录名为 <name>_infer，定位含权重文件的目录后重命名为 <name>
        src = None
        for root, _dirs, files in os.walk(extract_dir):
            if "inference.pdiparams" in files:
                src = root
                break
        if src is None:
            return "归档内未找到 inference.pdiparams"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        DEST.mkdir(parents=True, exist_ok=True)
        shutil.move(src, str(target))
        if not is_complete(target):
            return "解压后校验失败（缺权重文件）"
        return "ok"
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 64)
    print("Paddle V3 离线模型下载器")
    print(f"模型库: {MODEL_HOME}")
    print(f"目标  : {DEST}")
    print(f"模型数: {len(MODELS)}")
    print("=" * 64)

    if not str(MODEL_HOME).isascii():
        print("[警告] 模型库路径含非 ASCII 字符，Paddle C++ 引擎将无法加载！")
        print("       请把模型库放到纯英文路径，或设 PADDLE_V3_MODEL_HOME 指向 ASCII 目录。")

    DEST.mkdir(parents=True, exist_ok=True)
    ok = skipped = 0
    failed = []
    for i, name in enumerate(MODELS, 1):
        print(f"\n[{i}/{len(MODELS)}] {name}")
        result = fetch_one(name)
        if result == "skip":
            print("    已存在，跳过")
            skipped += 1
        elif result == "ok":
            size = sum(f.stat().st_size for f in (DEST / name).rglob("*") if f.is_file())
            print(f"    完成（{human(size)}）")
            ok += 1
        else:
            print(f"    失败：{result}")
            failed.append((name, result))

    print("\n" + "=" * 64)
    print(f"结果: 新下载 {ok} · 跳过 {skipped} · 失败 {len(failed)} · 共 {len(MODELS)}")
    if failed:
        print("失败明细:")
        for name, err in failed:
            print(f"  - {name}: {err}")
        print("重跑本脚本即可续传（已完成的会被跳过）。")
    else:
        print("全部模型就位，运行时零联网。")
    print("=" * 64)
    return len(failed)


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except KeyboardInterrupt:
        print("\n已取消（重跑可续传）。")
        code = 130
    try:
        input("\n按回车键退出...")
    except EOFError:
        pass
    sys.exit(code)