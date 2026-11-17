# SkillTwin — how to run it (and plug in Gemini)

## 1. Start the app (2 minutes)
Needs **Python 3.10+**. Nothing else.

| OS | Command (from this folder) |
|---|---|
| Windows | double-click `run.bat` (or run it in a terminal) |
| Mac / Linux | `./run.sh` |

Open **http://localhost:5000**. Tap **Continue as demo candidate** (or enter any name + valid-looking email).
Manual way: `cd backend && pip install -r requirements.txt && python app.py`.

## 2. Add your Gemini API key (optional — the app works without it)
1. Get a free key: https://aistudio.google.com/apikey
2. Copy `.env.example` to **`backend/.env`** and replace `paste_your_key_here` with your key:
   ```
   GEMINI_API_KEY=your_real_key
   ```
   (or set the env var instead — Windows PowerShell: `$env:GEMINI_API_KEY="your_key"`; Mac/Linux: `export GEMINI_API_KEY=your_key`)
3. Check it: `cd backend && python check_gemini.py` → should print **WORKING**.
4. **Restart** the app (`Ctrl+C`, then run it again). Confirm: http://localhost:5000/api/ai/status → `{"configured": true, ...}`.

Security: the key lives only on the server. It is never sent to the browser, never logged, and `.env` is git-ignored. **Never paste the key into the HTML/JSX files or share it in chat/screenshots.**

### What Gemini does — and doesn't
- **With a key:** Future Watch panel, LinkedIn outreach drafts, and optional AI re-wording of Copilot answers (discarded automatically if it changes any number).
- **Without a key / on any error:** those features show a clear message or fall back to the calculated text. **Scores, role fit, gaps, roadmap, reverse engineer, what-if and verification never use an LLM** — they work identically with or without Gemini.
- Different model: the default is `gemini-3.6-flash`. To use another one, set `GEMINI_MODEL=<model id>` in `.env` (for example `gemini-2.5-flash`).

## 3. Demo flow (about 3 minutes)
1. **Continue as demo candidate** → **Verify** tab: take the adaptive **Python** (or **SQL**) assessment, add evidence → confidence score + badge.
2. **Roles**: role fit comes from your *verified* levels.
3. **Path** tab → pick a role (e.g. ML Engineer) → **Try demo profile** → **Reverse engineer my path**: dependency-ordered path, skipped skills, compression vs a generic roadmap, **View evidence** on any step.
4. Change a what-if skill/level or the weights → the engine re-runs (labelled PROJECTION).
5. **Copilot**: ask "why is this my top gap?" — answered from engine results.

## 4. React / JSX version (optional)
`frontend-react/src/SkillTwin.jsx` is the same UI as one React component.
`cd frontend-react && npm install && npm run dev` → http://localhost:5173 (proxies `/api` to the backend on :5000, so keep the backend running).

## 5. Put it online (live link for judges)
See **DEPLOY.md** — GitHub + Render, free, ~15 minutes.

## 6. Tests
`cd backend && pip install pytest && python -m pytest tests -q` (172 tests; browser UI tests also need `playwright`).

## Honest limits
Role/skill data is an **illustrative sample** (7 roles, 37 skills), not live O*NET/ESCO/job postings. Only **Python and SQL** are assessable. GitHub/Gemini paths depend on your network and key. No recruiter view yet. Flask + SQLite (FastAPI/Postgres is the scale-up path).

## Troubleshooting
- *Port 5000 in use* → stop the other app (on Mac, turn off AirPlay Receiver) or change the port at the bottom of `backend/app.py`.
- *"backend is not reachable" in the UI* → the server isn't running; start it and open http://localhost:5000.
- *Gemini features say "not configured"* → key not found: check the file is `backend/.env`, no spaces around `=`, then restart.
- *Gemini "did not return a result"* → key invalid, quota exhausted, or no internet; run `python check_gemini.py`.
