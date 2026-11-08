@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [FAIL] venv missing. Run scripts\setup.cmd first.
  exit /b 1
)
if not exist "dist\index.html" (
  echo [run] dist missing, building frontend first...
  call build.cmd
  if errorlevel 1 exit /b 1
)
echo [run] paddle-v3-studio backend + UI, default http://127.0.0.1:8390
.venv\Scripts\python.exe server\app.py
endlocal