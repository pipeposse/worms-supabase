@echo off
REM Brief semanal de Direccion - WORMS
REM Se ejecuta los lunes por tarea programada. Genera el PDF y, si hay SMTP
REM configurado en el .env, lo manda por mail.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" brief_semanal.py %*
) else (
  python brief_semanal.py %*
)
if errorlevel 1 (
  echo.
  echo *** El brief NO se genero. Revisa el mensaje de arriba.
  pause
)
