@echo off
REM One-command start (Windows): creates a venv, installs deps, starts the app on http://localhost:5000
cd /d "%~dp0backend"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
python app.py
