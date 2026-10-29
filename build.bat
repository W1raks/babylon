@echo off
rem Сборка Babylon.exe в папку dist\Babylon
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (py -3 -m venv .venv || python -m venv .venv)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm babylon.spec
echo Готово: dist\Babylon\Babylon.exe
pause
