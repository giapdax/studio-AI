@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Dang cai Fashion AI Studio...
where python >nul 2>nul
if errorlevel 1 (
  echo Can cai Python 3.11+ va chon Add Python to PATH.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe python -m venv .venv
if not exist .venv\Scripts\python.exe goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" tools\check_environment.py
if errorlevel 1 goto fail
echo Cai dat xong. Mo START_APP.bat de chay.
pause
exit /b 0
:fail
echo Cai dat chua hoan tat. Kiem tra Internet va loi o tren.
pause
exit /b 1
