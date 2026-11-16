@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Hay chay INSTALL_APP.bat truoc.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\check_environment.py
if errorlevel 1 (
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1
pause
