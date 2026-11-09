@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Local Offline LLM Server - Spark-X2.6

rem ===========================================================
rem  Local offline LLM launcher for paddle-v3-studio
rem  Double-click to start the model server.
rem  Close this window or press Ctrl+C to stop and release it.
rem  Pure offline: loads a local GGUF, never downloads anything.
rem  GPU is auto-detected; falls back to CPU when unavailable.
rem ===========================================================

rem ---- overrides: set these env vars before launching if needed ----
if "%PORT%"=="" set "PORT=9931"
if "%CTX%"=="" set "CTX=262144"
if "%MODEL%"=="" set "MODEL=Spark-X2.6-4B-Q4_K_M.gguf"
set "ALIAS=spark-x2.6"

rem ---- resolve model home to a canonical ASCII path ----
if "%LLMS_HOME%"=="" set "LLMS_HOME=%~dp0..\..\MODEL-V3\llms"
for %%I in ("%LLMS_HOME%") do set "LLMS_HOME=%%~fI"
set "BIN=%LLMS_HOME%\bin\llama.exe"
set "GGUF=%LLMS_HOME%\%MODEL%"

echo.
echo ===========================================================
echo   Local Offline LLM Server  -  paddle-v3-studio
echo ===========================================================
echo   Engine    : llama.cpp  [llama.exe serve, OpenAI-compatible]
echo   Model     : %MODEL%
echo   GGUF      : %GGUF%
echo   Endpoint  : http://127.0.0.1:%PORT%  [loopback only]
echo   Chat API  : POST http://127.0.0.1:%PORT%/v1/chat/completions
echo   Context   : %CTX% tokens
echo   Offline   : YES  [local GGUF only, no network download]
echo.
echo   The server runs in the FOREGROUND of this window.
echo   Close this window or press Ctrl+C to stop the model
echo   and release GPU / RAM. Closing this window is enough;
echo   the attached llama.exe process is terminated with it.
echo ===========================================================
echo.

rem ---- preflight checks ----
if not exist "%BIN%" (
  echo [FAIL] llama.exe not found: "%BIN%"
  echo        Expected at MODEL-V3\llms\bin\llama.exe
  pause
  exit /b 1
)
if not exist "%GGUF%" (
  echo [FAIL] GGUF model not found: "%GGUF%"
  echo        Place the model in MODEL-V3\llms or set MODEL=filename
  pause
  exit /b 1
)

rem ---- detect GPU offload device ----
set "NGL=0"
set "DEVICE=CPU"
echo [probe] enumerating offload devices ...
"%BIN%" serve --list-devices > "%TEMP%\llm-devices.txt" 2>&1
findstr /I /C:"CUDA" /C:"ROCm" /C:"Metal" /C:"Vulkan" "%TEMP%\llm-devices.txt" >nul
if not errorlevel 1 (
  set "NGL=99"
  set "DEVICE=GPU"
)
if "%FORCE_CPU%"=="1" (
  set "NGL=0"
  set "DEVICE=CPU forced"
)
echo [probe] compute device = %DEVICE%   gpu-layers = %NGL%
echo [probe] device list:
type "%TEMP%\llm-devices.txt"
echo.

rem ---- launch in foreground; closing this window terminates it ----
echo [start] launching llama.cpp server, detailed logs follow ...
echo [start] press Ctrl+C or close this window to stop and release.
echo.
pushd "%LLMS_HOME%\bin"
llama.exe serve -m "%GGUF%" --host 127.0.0.1 --port %PORT% -c %CTX% -ngl %NGL% --no-webui --alias %ALIAS%
set "RC=%ERRORLEVEL%"
popd

echo.
echo [stop] llama.exe exited with code %RC%.
echo [stop] Model stopped; GPU and RAM released.
echo [stop] You may close this window.
pause
endlocal