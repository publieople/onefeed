@echo off
rem OneFeed launcher: preflight first, then start the server.
rem Keep this file ASCII-only: cmd parses .bat with the OEM code page,
rem and a UTF-8 Chinese string here becomes a "not recognized as a command" error.
setlocal
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8791"

echo ============================================
echo   OneFeed  launcher    port %PORT%
echo ============================================
echo.

uv run python -m onefeed --preflight --port %PORT%
if errorlevel 1 (
  echo.
  echo Preflight failed. Fix the items marked FAIL above, then run this file again.
  pause
  exit /b 1
)

echo.
echo Starting OneFeed... (Ctrl+C stops it)
echo.
uv run python -m onefeed --port %PORT%
echo.
echo Server stopped. Press any key to close.
pause >nul
