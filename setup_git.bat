@echo off
REM Setup inicial del repo Git apuntando a GitHub.
REM Solo se corre UNA vez. Despues usa deploy.bat para cada cambio.

cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  echo Git no esta instalado. Bajalo de https://git-scm.com/download/win y corre de nuevo.
  pause
  exit /b 1
)

if exist ".git" (
  echo Este directorio ya tiene un repo Git inicializado.
  echo Si queres reapuntarlo a otro remote:
  echo    git remote set-url origin https://github.com/USUARIO/REPO.git
  pause
  exit /b 0
)

set /p GH_USER="Tu usuario GitHub: "
set /p GH_REPO="Nombre del repo en GitHub (ej. worms-supabase): "

echo.
echo Iniciando repo...
git init
git branch -M main

REM Verificar que no haya secretos antes del primer commit
findstr /m "DATABASE_URL=" .env >nul 2>nul
if not errorlevel 1 (
  echo.
  echo OK: .env existe localmente. Esta excluido por .gitignore y NO se va a subir.
)

git add .
git commit -m "WORMS · primera version"

git remote add origin https://github.com/%GH_USER%/%GH_REPO%.git

echo.
echo Subiendo a GitHub...
git push -u origin main
if errorlevel 1 (
  echo.
  echo Si el push fallo, antes tenes que CREAR el repo vacio en GitHub:
  echo   1. github.com/%GH_USER% -^> New repository
  echo   2. Nombre: %GH_REPO%
  echo   3. Privado, sin README ni gitignore inicial.
  echo   4. Volve a correr este script o corre: git push -u origin main
  pause
  exit /b 1
)

echo.
echo ====================================================
echo Repo subido a: https://github.com/%GH_USER%/%GH_REPO%
echo.
echo Proximo paso: conectar Streamlit Cloud al repo.
echo Ver: docs\DEPLOY_STREAMLIT_CLOUD.md (seccion 4 en adelante)
echo ====================================================
pause
