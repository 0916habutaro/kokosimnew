@echo off
setlocal
cd /d "%~dp0\.."
python -m phase2_engine.browse_gui --db out\kokosim_browse.sqlite3 --data-dir data
endlocal
