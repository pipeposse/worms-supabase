@echo off
cd /d "%~dp0\.."
python -m etl.wedo_stock sync
pause
