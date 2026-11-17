#!/usr/bin/env bash
# One-command start (Mac/Linux): creates a venv, installs deps, starts the app on http://localhost:5000
set -e
cd "$(dirname "$0")/backend"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python app.py
