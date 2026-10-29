@echo off
rem Запуск из исходников (нужен Python 3.10+ с python.org)
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Первый запуск: ставлю библиотеки, это займёт пару минут...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe run_babylon.py
