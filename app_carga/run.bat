@echo off
cd /d "%~dp0..\.."
set PYTHONPATH=%CD%
if exist worms_supabase\.venv\Scripts\activate.bat call worms_supabase\.venv\Scripts\activate.bat
echo.
echo  App: http://localhost:8501  /  http://TU_IP:8501
echo.
streamlit run worms_supabase\app_carga\app.py --server.address 0.0.0.0 --server.port 8501
