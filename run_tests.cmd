@echo off
rem Double-click this file to run all tests. No PyCharm configuration needed.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_tests.py
) else (
  py run_tests.py
)

echo.
echo Press any key to close this window...
pause >nul
