"""路径规范判据：扫描两工程源码，发现硬编码绝对路径即非零退出。

用法：.venv\\Scripts\\python.exe scripts\\check_paths.py
退出码 = 命中条数（0 = 全部相对路径，合规）。
只查清晰的绝对文件路径信号，避开 http:// URL、XML 命名空间、仓库 URL。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = [ROOT, ROOT.parent / "contract-source"]
EXTS = {".py", ".js", ".vue", ".cmd", ".yml", ".yaml", ".xml", ".sql", ".java"}
SKIP_DIRS = {"node_modules", ".venv", "dist", "data", "__pycache__", ".git", "target"}
SKIP_FILES = {"package-lock.json", "check_paths.py"}

PATTERNS = [
    ("Windows 反斜杠盘符路径", re.compile(r"\b[A-Za-z]:\\")),
    ("Windows 正斜杠盘符路径", re.compile(r"\b[A-Za-z]:/[^/\s]")),
    ("Unix 用户主目录绝对路径", re.compile(r"/(?:Users|home)/[A-Za-z0-9_]")),
    ("USERPROFILE 变量绝对路径", re.compile(r"%USERPROFILE%", re.I)),
]


def iter_files():
    for proj in PROJECTS:
        if not proj.exists():
            continue
        for p in proj.rglob("*"):
            if not p.is_file() or p.suffix not in EXTS or p.name in SKIP_FILES:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            yield p


def main():
    violations = []
    scanned = 0
    for f in iter_files():
        scanned += 1
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for label, pat in PATTERNS:
                if pat.search(line):
                    rel = f.relative_to(ROOT.parent)
                    violations.append((rel, i, label, line.strip()[:100]))
    print(f"scanned {scanned} source files across {len(PROJECTS)} projects")
    for rel, i, label, snippet in violations:
        print(f"FAIL  {rel}:{i}  [{label}]  {snippet}")
    if not violations:
        print("PASS  no hardcoded absolute file paths (relative-path rule satisfied)")
    print(f"\nRESULT {len(violations)} violation(s)")
    sys.exit(len(violations))


if __name__ == "__main__":
    main()