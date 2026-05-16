@echo off
REM ============================================================
REM  Pre-download & warm up the plate detector + OCR models.
REM
REM  Why this batch file exists:
REM  -----------------------------
REM  `python` on this machine resolves to Inkscape's bundled
REM  interpreter, which does NOT have aimm installed.
REM  The real Python (where pip put fast-plate-ocr) lives at:
REM     %LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13...
REM  This script picks the right one explicitly.
REM ============================================================

setlocal

REM Prefer the Windows Store Python (the one `pip install` actually targets here).
set "PY=%LOCALAPPDATA%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"

if not exist "%PY%" (
    REM Fall back to the `py` launcher.
    where py >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Could not find Python 3.13. Install from the Microsoft Store or python.org.
        exit /b 1
    )
    set "PY=py -3.13"
)

echo Using interpreter: %PY%
echo.

REM Resolve repo root (parent of /scripts).
set "REPO=%~dp0.."

"%PY%" -c "import sys; sys.path.insert(0, r'%REPO%\src'); import logging; logging.basicConfig(level=logging.INFO); from ai_marketplace_monitor.plate_ocr import _ensure_models; _ensure_models(logging.getLogger('warmup')); print('Models ready.')"

endlocal
