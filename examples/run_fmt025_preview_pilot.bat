@echo off
setlocal
cd /d "%~dp0\.."
REM Stage 13E-3G-35: experimental read-only preview; no SQLite DB required.
python -m phase2_engine.hiroshima_stage13e3g35_preview_gui --data-dir data
endlocal
