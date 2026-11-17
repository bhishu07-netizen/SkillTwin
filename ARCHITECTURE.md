# SkillTwin: how it works

**One line:** SkillTwin measures what a person can actually do (not what their CV claims), then shows the shortest path to a target role.

## The three layers

| Layer | Where | What it does |
|---|---|---|
| Verification engine | `backend/verification/` | Turns a *claim* ("I know SQL") into a *measured* level with a confidence score |
| Career path engine | `backend/career/engine.py` | Takes verified levels and a role's requirements, finds gaps, orders what to learn first |
| Market scorecard | `frontend/skilltwin.html` (Market scorecard tab) | Three small models fitted on the SAS hackathon datasets, run in the browser |

## 1. Verification: why you cannot just type a high score

- The browser never sends a score. It sends raw answers.
- The server grades them: multiple-choice and output questions against a server-side key; code questions by hidden unit tests run in a sandbox.
- Time is measured by the server clock, and answers are locked on submit.
- Final number (`verification/scoring.py`, pure functions, no randomness, no LLM):

  `confidence = 0.70 x assessment + 0.20 x evidence + 0.10 x consistency`

  - assessment = difficulty-weighted accuracy (easy 1, medium 2, hard 3)
  - evidence = certificates, projects, links, combined so extra items add less each time
  - consistency = does the claimed level match what the test showed
- Level thresholds (on the assessment score): Intermediate 40, Advanced 70, Expert 85.
- All weights and thresholds live in one file, `verification/config.py`.

## 2. Code sandbox (`verification/sandbox.py`)

User code is risky, so it is screened before it runs: only allow-listed imports, no `eval`, `exec`, `open`, or `getattr`. It then runs in a separate process with a wall-clock timeout, and the whole process group is killed on expiry. The expected answers never enter that process.

## 3. Career path engine (`career/engine.py`)

Pipeline: verified profile -> role requirement graph -> gap -> priority -> prerequisite-aware ordering -> phases and effort -> comparison with a generic roadmap -> what-if.

`priority = 100 x weighted geometric mean(importance, market demand, gap, dependency criticality)`

Deterministic. The same input always gives the same roadmap.

## 4. Where Gemini is used (and where it is not)

- Used for: plain-language explanations of a result, and the Copilot chat (`backend/llm.py`, the only file that calls Gemini).
- Not used for: any score, level, fit percentage or ordering. Those come from the code above.
- Quota-friendly: if a model returns HTTP 429 the next model is tried, that model is skipped for 60 s, and identical prompts are cached for 10 min.
- If the API key is missing or the call fails, the app still works; explanations fall back to rule-based text. Check with `/api/ai/status?test=1`.

## 5. Market ML models (trained, served live)

Two logistic-regression models trained on 15,841 real job postings (SAS file `Analytics Jobs.csv`): the chance a posting is in the 15 LPA+ band, and the closest market segment, both from the skills the posting lists. Evaluated with grouped 5-fold cross-validation (repeated postings never straddle folds). Honest result: pay AUC 0.81, but experience alone gives 0.80, so skills add only a little. Served by pure-Python inference (`backend/ml/model.py` + `model.json`), retrainable with `python -m ml.train`. The Market ML tab shows the live estimate for your profile, the skill that would move it most, and the full model card. Full details: `backend/ml/README.md`.

## 6. Market scorecard

Built from the SAS hackathon data: a salary-hike model (ridge logistic), a senior-success model (quadratic discriminant), and a salary model (log-linear). Coefficients are stored in `prototype_coefs.json` and applied in the browser, so nothing is uploaded. Full method is in the Approach Note.

## 7. Safety and limits

Per-IP rate limiting, same-origin CORS (no wildcard), SQLite storage, secrets only from environment variables (never in code). Tests: `cd backend && python -m pytest` (172 tests).

## Folder map

```
backend/app.py            Flask app, routes for profile / match / gap / roadmap
backend/core.py           skills + roles dataset, fit score
backend/llm.py            the single Gemini caller
backend/security.py       rate limits, CORS, headers
backend/verification/     assessments, scoring, evidence, sandbox
backend/career/           path engine, what-if, copilot
frontend/skilltwin.html   the whole UI (single file)
frontend/assets/          logo and favicon
```
