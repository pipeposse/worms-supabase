@echo off
REM Bootstrap todo de una. Doble click para instalar.
cd /d "%~dp0"
echo Verificando Python...
where python >nul 2>nul
if errorlevel 1 (
    echo Falta Python. Instalalo de https://www.python.org/downloads/
    pause
    exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip --quiet
python -m pip install -r app_carga\requirements.txt
echo.
echo Setup OK. Ahora completa .env (copialo de .env.example) y luego:
echo   setup.bat   (crea schema + seed en Supabase)
echo   app_carga\run.bat   (levanta la app)
pause
