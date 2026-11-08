@echo off
setlocal
cd /d "%~dp0"
where npm >nul 2>nul
if errorlevel 1 (
  echo [FAIL] npm not found in PATH. Node.js 20+ required.
  exit /b 1
)
if exist node_modules (
  call npm ci --no-audit --no-fund
) else (
  call npm install --no-audit --no-fund
)
if errorlevel 1 exit /b 1
call npm run build
if errorlevel 1 exit /b 1
echo [OK] dist built
endlocal