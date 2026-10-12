@echo off
REM AccuPaid one-shot launcher (Windows).
REM Seeds SQLite if needed, starts the FastAPI gateway (:8000)
REM and the Streamlit approval queue (:8501), then opens API docs.
cd /d %~dp0

where python >nul 2>&1 || (echo [start] python not found on PATH. & exit /b 1)

if not exist accupaid.db (
  echo [start] seeding accupaid.db ...
  python db\seed.py || (echo [start] seed failed. & exit /b 1)
)

python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
  echo [start] installing pinned deps from requirements.txt ^(one-time^) ...
  pip install -q -r requirements.txt || (echo [start] pip install failed. & exit /b 1)
)

echo [start] launching API :8000 ...
start "AccuPaid-API" cmd /k "uvicorn app.main:app --host 127.0.0.1 --port 8000"
echo [start] launching approval UI :8501 ...
start "AccuPaid-UI" cmd /k "streamlit run ui\approve.py --server.port 8501 --server.address 127.0.0.1 <nul"

timeout /t 5 >nul
start http://127.0.0.1:8000/docs
echo [start] done. API http://127.0.0.1:8000  UI http://127.0.0.1:8501
echo [start] run stop.bat to shut both down.
