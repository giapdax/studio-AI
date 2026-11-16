@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Hay chay INSTALL_APP.bat truoc.
  pause
  exit /b 1
)
echo Worker nay chi tu dong xu ly MOCK. Khong goi API co phi.
".venv\Scripts\python.exe" -m studio.worker --resume-mock
pause
