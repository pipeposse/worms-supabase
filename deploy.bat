@echo off
REM Deploy a GitHub → Streamlit Cloud rebuildea solo.
REM Uso:  deploy.bat "mensaje del commit"

cd /d "%~dp0"

if "%~1"=="" (
  set /p MSG="Mensaje del commit: "
) else (
  set MSG=%~1
)

echo.
echo == Cambios pendientes ==
git status --short
echo.

echo == git add . ==
git add .
if errorlevel 1 goto :err

echo.
echo == git commit -m "%MSG%" ==
git commit -m "%MSG%"
if errorlevel 1 (
  echo No hay nada que commitear o el commit fallo.
  goto :end
)

echo.
echo == git push ==
git push
if errorlevel 1 goto :err

echo.
echo Deploy enviado. Streamlit Cloud rebuildea en ~1 min.
echo URL: https://share.streamlit.io  ^(ver "Manage app" para el log^)
goto :end

:err
echo ERROR. Revisa el output arriba.
exit /b 1

:end
pause
