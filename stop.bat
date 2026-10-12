@echo off
REM Stop AccuPaid (API :8000 + UI :8501) by listening port.
for %%P in (8000 8501) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
  )
)
echo [stop] AccuPaid API + UI stopped.
