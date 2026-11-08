@echo off
setlocal
cd /d "%~dp0"
if not exist "target\contract-source.jar" (
  echo [run] jar missing, building first...
  call build.cmd
  if errorlevel 1 exit /b 1
)
where java >nul 2>nul
if errorlevel 1 (
  echo [FAIL] java not found in PATH. JDK 8+ required.
  exit /b 1
)
echo [run] contract-source on http://127.0.0.1:8081  (H2 file db: data\contractdb)
java -jar target\contract-source.jar
endlocal