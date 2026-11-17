# SkillTwin Backend (Flask)

A real, running HTTP API — not the client-side-only prototype. Same scoring
engine and dataset as `skilltwin.html`, ported to Python and persisted in
SQLite instead of the browser.

**Framework note:** the deck's architecture slide names FastAPI as the
target stack. This is shipped in Flask because that's what was actually
available to install and test in the build environment (no network access
to `pip install fastapi` there). Endpoint shapes and logic are the same —
swapping frameworks later is mechanical, not a redesign.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Starts on `http://localhost:5000`. First request creates `skilltwin.db`
(SQLite) automatically.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/skills` | List the skill taxonomy |
| GET | `/api/roles` | List all roles + their required skills |
| GET | `/api/roles/<role-id>` | e.g. `/api/roles/data-scientist` |
| POST | `/api/profile` | `{"text": "Python, SQL, ..."}` → extracts skills, returns `candidate_id` |
| GET | `/api/profile/<candidate_id>` | Retrieve a stored profile |
| POST | `/api/match` | `{"candidate_id", "role"}` → fit score |
| POST | `/api/gap-analysis` | `{"candidate_id", "role"}` → ranked gaps with evidence |
| POST | `/api/roadmap` | `{"candidate_id", "role"}` → phased roadmap + suggested projects |
| POST | `/api/simulate` | `{"candidate_id", "role", "learn_skills": [...]}` → before/after What-If |
| GET | `/api/analytics` | Aggregate skill demand across all roles (institution view) |

All of `/api/match`, `/api/gap-analysis`, `/api/roadmap`, `/api/simulate`
also accept an inline `{"skills": {"python": 0.7, ...}}` instead of
`candidate_id`, if you want to test without persisting a profile first.

## Try it

```bash
curl -X POST http://localhost:5000/api/profile \
  -H "Content-Type: application/json" \
  -d '{"text":"Python, SQL, Pandas, basic machine learning"}'
# → {"candidate_id": "...", "extracted_skills": {...}}

curl -X POST http://localhost:5000/api/gap-analysis \
  -H "Content-Type: application/json" \
  -d '{"candidate_id":"<id from above>","role":"Data Scientist"}'
```

## What's real here vs. still missing
- ✅ Real HTTP server, real SQLite persistence, real computed scoring —
  verified working (not just written) before this was handed over.
- ✅ CORS enabled (manually — `flask-cors` wasn't installable offline either),
  so `skilltwin.html` or any frontend can call this directly.
- ❌ No auth — `candidate_id` is an unguessable UUID but anyone with it can
  read that profile. Fine for a hackathon demo, not for production.
- ❌ Still the same illustrative 5-role dataset, not real O*NET/ESCO data.
- ❌ No rate limiting, no deployment config (see main README for
  Render/Railway pointers).
- ❌ The LLM Copilot/Connect/Future Watch features are NOT wired through
  this backend — they still call Claude directly from the browser via the
  artifact's `sample` capability. Routing them through here (with a
  server-side key) is the natural next step once this is deployed.

## Wiring it to the frontend
`skilltwin.html` currently does all scoring client-side and doesn't call
this API. To connect them: replace the JS `fitScore()` / `renderGap()` /
`renderRoadmap()` calls with `fetch('http://localhost:5000/api/...')`
calls to the matching endpoint above. Not done yet — flag if you want that
wired up next.

---
# Skill Verification & Confidence Engine (new)

**Claim → Demonstrate → Verify → Match.** Run `python app.py` and open http://localhost:5000 (the backend now serves the frontend).

| Piece | Where |
|---|---|
| Config (weights, thresholds, guards - all tunable; override with `SKILLTWIN_VERIFY_CONFIG=file.json`) | `verification/config.py` |
| Deterministic scoring (assessment, evidence, consistency, confidence, level, discrepancy, badge) | `verification/scoring.py` |
| Adaptive selection (staircase + prerequisite probing + early stop) | `verification/adaptive.py` |
| Attempt lifecycle, server-side grading, results, effective profile | `verification/engine.py` |
| Code sandbox | `verification/sandbox.py`, `sandbox_harness.py` |
| Evidence checks (GitHub API, credential links, Python code analysis) | `verification/evidence.py` |
| Python question bank (41 questions, 5 categories, 3 difficulties) | `verification/bank/python_bank.py` |
| AI explanation (optional, numbers never touched) | `verification/explain.py` (`GEMINI_API_KEY`, `GEMINI_MODEL`) |

Confidence = 70% assessment + 20% evidence + 10% consistency (configurable). Level comes from the assessment score
(0-39 Beginner, 40-69 Intermediate, 70-84 Advanced, 85+ Expert) with a guard requiring hard-question evidence for Advanced/Expert.
Role-fit uses demonstrated level x certainty; unverified claims count at 80% (`profile.unverified_weight`, set 1.0 to disable).
Badges: SELF-DECLARED, PARTIALLY VERIFIED, EVIDENCE-BACKED (verified-evidence score >= 40), VERIFIED (also confidence >= 85, claim met, no rapid-answer flags).

## Tests
```
pip install pytest
python -m pytest tests -q            # bank self-test + sandbox + full API flow (62 tests)
python tests/simulate_ability.py      # Monte-Carlo: score vs. simulated ability
python app.py &  python tests/ui_e2e.py 0.75   # headless-browser run of the real UI (needs playwright)
```

## Honest limits
- Only **Python** has a question bank. Other skills show "assessment not available yet" (never fabricated questions). Add `<skill>_bank.py` + register it in `bank/__init__.py`; `tests/test_bank.py` validates it.
- The sandbox is prototype-grade (process, rlimits, uid drop, import allow-list). For production run it in a container/gVisor/microVM or Judge0.
- Evidence "verified" = exists and is relevant, **not** proof of authorship. GitHub checks need outbound access to api.github.com (set `GITHUB_TOKEN` for rate limits); logic is unit-tested with a mocked API only.
- 8-12 questions give a noisy level near a threshold; the "claim nearly supported" state and confidence score reflect that.
- Integrity measures reduce casual copying; they do not make cheating impossible. No auth beyond candidate UUID.

## Career Path Optimization Engine / Reverse Engineer (new)

Verified profile -> role requirement graph -> gap -> priority -> dependency-ordered path -> what-if. No LLM decides anything.

- `career/data.py` - sample dataset: 37 skills (demand index, effort hours, prerequisite DAG, aliases, project) and 7 roles
  (importance, required level, posting frequency). Validated acyclic at import. **Illustrative data, not live market data.**
- `career/engine.py` - level units (0.4/0.7/1.0 -> 1/2/3), requirement-aware fit, priority = 100 x weighted geometric mean
  (importance, demand, gap, dependency criticality), Kahn topological order with priority tie-break, phases, effort,
  compression vs a generic full-closure roadmap, what-if (re-runs the engine; pulls in unmet prerequisites), best-next-moves.
- `career/explain.py` - deterministic wording; optional Gemini rewording discarded if it contains any number not in the facts.
- `career/api.py` - `/api/career/{roles,config,demo-profile,reverse-engineer,simulate,evidence/<role>/<skill>}`.
- Verified skills credit the *demonstrated* level (scaled down below 70% confidence); self-declared claims are credited at 80%
  unless the demo toggle "take claims at face value" is on; skipped-but-unverified skills are listed as "verify".
- Legacy `/api/gap-analysis`, `/api/roadmap`, `/api/simulate` still exist (same dataset, simpler logic); the UI uses the new endpoints.
- Tests: `python -m pytest tests -q` (94 pass); UI: `python tests/ui_career_e2e.py` with the server running.

## Round 3 additions (audit follow-up)

**One engine everywhere.** Role grid, fit card, Gap tab, Roadmap tab, Reverse Engineer, What-If, Copilot and the legacy
`/api/match|gap-analysis|roadmap|simulate` endpoints all call `career/engine.py`; the browser never computes a score.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/career/fit-all` | fit for every role (drives the role grid) |
| POST | `/api/career/copilot` | answer composed from engine results; AI may only reword (discarded if it changes a number) |
| POST | `/api/ai/generate` | server-side prompts for Future Watch / outreach wording (needs `GEMINI_API_KEY`; 503 otherwise) |
| GET | `/api/career/history/<cid>?role=` | readiness snapshots, what changed, projected-vs-actual for what-if runs |

- **SQL assessment** (`verification/bank/sql_bank.py`): 37 questions; output keys are produced by executing the query with sqlite3;
  every "pick the query" option is executed by `tests/test_sql_bank.py`.
- **Skill extraction** is whole-word, negation-aware ("never used Python" is not a claim) and reads local level cues.
- **Readiness history**: tables `readiness_snapshots`, `projections`; snapshots are stored when the effective profile changes.
- **Security** (`security.py`): per-candidate token (`X-Candidate-Token`, HMAC under a per-database secret) on every candidate-scoped
  route, attempts/results resolved to their owner; per-IP rate limits; same-origin CORS (`SKILLTWIN_CORS_ORIGINS` to extend);
  256 KB body cap; JSON errors only; API key read from the environment only and never returned.
- Env: `GEMINI_API_KEY`, `GEMINI_MODEL`, `SKILLTWIN_CORS_ORIGINS`, `SKILLTWIN_VERIFY_CONFIG`.
- Tests: `python -m pytest tests -q` (172). UI (server running): `python tests/ui_judge_demo.py`, `tests/ui_career_e2e.py`, `tests/ui_e2e.py`.
