# SkillTwin — Full Project Package

## What's in here
- `frontend/skilltwin.html` — the working prototype UI (client-side scoring +
  Copilot/Connect/Future Watch, which use Claude's key-free `sample`
  capability when opened as a Claude.ai artifact).
- `backend/app.py` — a real Flask HTTP API with the same scoring engine and
  dataset, persisted in SQLite. Tested and confirmed working (see
  `backend/README.md` for how it was verified) — not wired to the frontend
  yet (see below).
- `SkillTwin_Proposal.pptx` — the 15-slide pitch deck.

## Current state, plainly
- The **frontend** (`skilltwin.html`) does all its scoring in-browser and
  does not call the backend.
- The **backend** (`app.py`) is a separate, independently working API — you
  can run it and hit it with `curl` right now — but nothing currently
  points the frontend at it.
- These are two halves of the same design that aren't connected yet. That's
  the next concrete step if you want a "real" full-stack app rather than
  two working pieces.

## Quick start
**Frontend only (what you've been demoing):**
Open `frontend/skilltwin.html` in a browser, or publish it (Netlify Drop /
GitHub Pages) for a public link. AI features only work inside a Claude.ai
artifact view.

**Backend only:**
```bash
cd backend
pip install -r requirements.txt
python app.py
```
Then `curl http://localhost:5000/api/health`. Full endpoint list in
`backend/README.md`.

**Both, connected — not done yet.** Say the word and I'll wire
`skilltwin.html`'s scoring calls to fetch from this API instead of
computing client-side; at that point the backend becomes load-bearing
and the SQLite `candidates` table becomes the real source of truth
instead of browser memory.

## Known gaps (unchanged from before, for the record)
- Dataset is illustrative (5 roles, ~18 skills), not real O*NET/ESCO data.
- No auth beyond an unguessable candidate UUID.
- No deployment config, no rate limiting.
- LLM features (Copilot/Connect/Future Watch) call Claude directly from the
  browser, not through the backend — that's the natural home for a real,
  server-side LLM API key once this is deployed.
