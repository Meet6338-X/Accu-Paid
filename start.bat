@echo off
REM AccuPaid one-shot launcher (Windows).
REM Seeds SQLite if needed, starts the FastAPI gateway (:8000)
REM and the React console (:8501), then opens both.
cd /d %~dp0

where python >nul 2>&1 || (echo [start] python not found on PATH. & exit /b 1)
where node >nul 2>&1 || (echo [start] node not found on PATH. Get it from https://nodejs.org/ & exit /b 1)

if not exist accupaid.db (
  echo [start] seeding accupaid.db ...
  python db\seed.py || (echo [start] seed failed. & exit /b 1)
)

python -c "import fastapi, langgraph" >nul 2>&1
if errorlevel 1 (
  echo [start] installing pinned python deps ^(one-time^) ...
  pip install -q -r requirements.txt || (echo [start] pip install failed. & exit /b 1)
)

if not exist frontend\node_modules (
  echo [start] installing console deps ^(one-time^) ...
  pushd frontend && call npm install --no-audit --no-fund || (popd & echo [start] npm install failed. & exit /b 1)
  popd
)

echo [start] launching API :8000 ...
start "AccuPaid-API" cmd /k "uvicorn app.main:app --host 127.0.0.1 --port 8000"
echo [start] launching console :8501 ...
start "AccuPaid-UI" cmd /k "cd frontend && npm run dev"

timeout /t 6 >nul
start http://127.0.0.1:8501
start http://127.0.0.1:8000/docs
echo [start] done. Console http://127.0.0.1:8501  API http://127.0.0.1:8000
echo [start] run stop.bat to shut both down.
