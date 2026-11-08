@echo off
setlocal
cd /d "%~dp0"
where mvn >nul 2>nul
if errorlevel 1 (
  echo [FAIL] mvn not found in PATH. Install Maven first.
  exit /b 1
)
call mvn -q -DskipTests package
if errorlevel 1 (
  echo [FAIL] maven build failed
  exit /b 1
)
echo [OK] target\contract-source.jar
endlocal