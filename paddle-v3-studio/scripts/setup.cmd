@echo off
setlocal
cd /d "%~dp0.."
echo [setup] project root: %CD%

where python >nul 2>nul
if errorlevel 1 (
  echo [FAIL] python not found in PATH. Python 3.10+ required.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [setup] creating venv...
  python -m venv .venv
  if errorlevel 1 exit /b 1
)
set PY=.venv\Scripts\python.exe

echo [setup] trying GPU wheel (paddlepaddle-gpu 3.4.0 cu129)...
%PY% -m pip install paddlepaddle-gpu==3.4.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/
if errorlevel 1 (
  echo [setup][WARN] GPU wheel failed, falling back to CPU wheel...
  %PY% -m pip install paddlepaddle==3.4.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
  if errorlevel 1 (
    echo [FAIL] both GPU and CPU paddle installs failed
    exit /b 1
  )
)

echo [setup] installing paddleocr + web deps (tsinghua mirror)...
%PY% -m pip install paddleocr==3.7.0 "paddlex[ocr]==3.7.2" fastapi uvicorn python-multipart pypdfium2 python-docx pywin32 -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo [FAIL] dependency install failed
  exit /b 1
)

echo [setup] pre-downloading models into ASCII MODEL-V3 (network used ONLY here)...
%PY% scripts\setup_models.py
if errorlevel 1 (
  echo [FAIL] model pre-download failed
  exit /b 1
)
echo [setup] DONE. Next: build.cmd then run.cmd
endlocal