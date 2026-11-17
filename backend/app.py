"""
SkillTwin backend - Flask API.

Role-fit / gap / roadmap logic lives in core.py; the Skill Verification & Confidence Engine
lives in the verification/ package. Candidates' role-fit now uses VERIFIED levels (demonstrated
level scaled by confidence) rather than blindly trusting self-declared ones.

Run:  python app.py   ->  http://localhost:5000  (serves the frontend too)
"""
import json
import re
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

from core import (TAXONOMY, ROLES, DW, PROJECTS, LEVEL_LABEL, classify, extract_skills, fit_score,
                  role_gaps, shortest_path)
from verification import db as VDB
from verification import engine as VENG
from verification.api import bp as verification_bp
from ml.api import bp as ml_bp

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
DB_PATH = VDB.DB_PATH

app = Flask(__name__)
app.register_blueprint(verification_bp)
from career.api import bp as career_bp  # noqa: E402
app.register_blueprint(career_bp)
app.register_blueprint(ml_bp)
app.teardown_appcontext(VDB.close_db)
get_db = VDB.get_db


def init_db():
    VDB.init_db(taxonomy=list(TAXONOMY))


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "skilltwin.html")


@app.route("/assets/<path:name>")
def assets(name):
    """Logo and favicon files used by the page."""
    return send_from_directory(FRONTEND_DIR / "assets", name, max_age=86400)



import security  # noqa: E402
security.install(app)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "dataset": "illustrative sample (5 roles, %d skills)" % len(TAXONOMY)})


@app.route("/api/skills")
def list_skills():
    return jsonify({"skills": [{"canonical_name": k, "aliases": v} for k, v in TAXONOMY.items()]})


@app.route("/api/roles")
def list_roles():
    return jsonify({"roles": [
        {"title": name, "skills": {s: {"importance": i, "demand": d, "sample_frequency_pct": p}
                                    for s, (i, d, p) in data["skills"].items()}}
        for name, data in ROLES.items()
    ]})


@app.route("/api/roles/<role_id>")
def get_role(role_id):
    for name, data in ROLES.items():
        if name.lower().replace(" ", "-") == role_id.lower():
            return jsonify({"title": name, "skills": {
                s: {"importance": i, "demand": d, "sample_frequency_pct": p}
                for s, (i, d, p) in data["skills"].items()
            }})
    return jsonify({"error": "unknown role", "known_roles": list(ROLES.keys())}), 404


@app.route("/api/profile", methods=["POST"])
def create_profile():
    body = request.get_json(force=True, silent=True) or {}
    text = body.get("text", "")
    if not text.strip():
        return jsonify({"error": "field 'text' (resume/skills text) is required"}), 400
    skills = extract_skills(text)
    candidate_id = str(uuid.uuid4())
    db = get_db()
    db.execute("INSERT INTO candidates (id, skills_json) VALUES (?, ?)",
               (candidate_id, json.dumps(skills)))
    now = VDB.now()
    for k, v in skills.items():
        db.execute("INSERT INTO skill_claims(candidate_id, skill, claimed_level, created_at, updated_at) VALUES (?,?,?,?,?)",
                   (candidate_id, k, LEVEL_LABEL.get(v, "Intermediate"), now, now))
    return jsonify({
        "candidate_id": candidate_id, "token": security.token_for(candidate_id),
        "extracted_skills": {k: {"level": v, "label": LEVEL_LABEL.get(v, "Intermediate")} for k, v in skills.items()},
    }), 201


@app.route("/api/profile/<candidate_id>")
def get_profile(candidate_id):
    row = get_db().execute("SELECT skills_json FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        return jsonify({"error": "unknown candidate_id"}), 404
    skills = json.loads(row["skills_json"])
    return jsonify({"candidate_id": candidate_id, "skills": skills})


def _load_candidate_skills(body):
    """Accepts either a stored candidate_id or an inline {skills: {...}} override."""
    if "candidate_id" in body:
        db = get_db()
        row = db.execute("SELECT skills_json FROM candidates WHERE id=?", (body["candidate_id"],)).fetchone()
        if not row:
            return None
        declared = json.loads(row["skills_json"])
        if body.get("mode") == "declared":
            return declared
        # role-fit uses VERIFIED levels: demonstrated level scaled by confidence; unverified claims discounted
        prof = VENG.effective_profile(db, body["candidate_id"])
        return {s: p["effective_value"] for s, p in prof.items()} if prof else declared
    return body.get("skills", {})


@app.route("/api/match", methods=["POST"])
def match():
    body = request.get_json(force=True, silent=True) or {}
    role = body.get("role")
    if not isinstance(role, str) or role not in ROLES:
        return jsonify({"error": "unknown role", "known_roles": list(ROLES.keys())}), 400
    skills = _load_candidate_skills(body)
    if skills is None:
        return jsonify({"error": "unknown candidate_id"}), 404
    score = fit_score(role, skills)
    declared = _load_candidate_skills({**body, "mode": "declared"}) if "candidate_id" in body else skills
    return jsonify({
        "role": role, "fit_score": score, "fit_pct": round(score * 100, 1),
        "declared_fit_pct": round(fit_score(role, declared) * 100, 1),
        "basis": "verified-adjusted" if "candidate_id" in body and body.get("mode") != "declared" else "as supplied",
        "method": "importance-weighted attainment: sum(importance x min(1, level_units / required_units)) / sum(importance)",
    })


def _engine_profile(body):
    """Profile for the career engine: a stored candidate (verified levels) or inline {skills: {skill: 0..1}}."""
    from career import engine as CE
    if "candidate_id" in body:
        db = get_db()
        if not db.execute("SELECT 1 FROM candidates WHERE id=?", (body["candidate_id"],)).fetchone():
            return None
        return CE.build_profile(verification_profile=VENG.effective_profile(db, body["candidate_id"]),
                                trust_declared=bool(body.get("trust_declared")))
    skills = body.get("skills", {})
    if not isinstance(skills, dict):
        return None
    return CE.profile_from_values(skills)


# Legacy endpoints kept for compatibility - now thin wrappers over the Career Path Optimization Engine,
# so every screen and API agrees on fit, gaps, ordering and what-if results.
@app.route("/api/gap-analysis", methods=["POST"])
def gap_analysis():
    from career import engine as CE
    body = request.get_json(force=True, silent=True) or {}
    role = body.get("role")
    if not isinstance(role, str) or role not in ROLES:
        return jsonify({"error": "unknown role", "known_roles": list(ROLES.keys())}), 400
    prof = _engine_profile(body)
    if prof is None:
        return jsonify({"error": "unknown candidate_id or invalid skills"}), 404 if "candidate_id" in body else 400
    res = CE.analyze(role, prof)
    return jsonify({"role": role, "fit_pct": res["fit_pct"], "fit_score": round(res["fit_pct"] / 100, 4),
                    "gaps": [{"skill": s["skill"], "status": s["status"], "importance": s["importance"], "demand_index": s["demand"],
                              "sample_frequency_pct": s["freq"], "current_level": s["current_level"],
                              "required_level": s["required_level"], "gap_units": s["gap_units"], "priority_score": s["priority"],
                              "basis": s["basis"]} for s in sorted((x for x in res["role_skills"] if x["status"] != "meets"),
                                                                    key=lambda x: (-(x["priority"] or 0), x["skill"]))],
                    "engine": "career-path-optimization"})


@app.route("/api/roadmap", methods=["POST"])
def roadmap():
    from career import engine as CE
    body = request.get_json(force=True, silent=True) or {}
    role = body.get("role")
    if not isinstance(role, str) or role not in ROLES:
        return jsonify({"error": "unknown role", "known_roles": list(ROLES.keys())}), 400
    prof = _engine_profile(body)
    if prof is None:
        return jsonify({"error": "unknown candidate_id or invalid skills"}), 404 if "candidate_id" in body else 400
    res = CE.analyze(role, prof)
    by_phase = {}
    for st in res["steps"]:
        by_phase.setdefault(st["phase"], []).append({**st, "suggested_project": st["project"]})
    return jsonify({"role": role, "total_hours": res["total_hours"], "weeks": res["weeks"], "compression": res["compression"],
                    "phases": [{"phase": p, "skills": v} for p, v in sorted(by_phase.items())], "engine": "career-path-optimization"})


@app.route("/api/simulate", methods=["POST"])
def simulate():
    """What-If: delegates to the engine (prerequisites are pulled in; result is a PROJECTION)."""
    from career import engine as CE
    body = request.get_json(force=True, silent=True) or {}
    role = body.get("role")
    learn = body.get("learn_skills", [])
    if not isinstance(role, str) or role not in ROLES:
        return jsonify({"error": "unknown role", "known_roles": list(ROLES.keys())}), 400
    if not isinstance(learn, list):
        return jsonify({"error": "learn_skills must be a list"}), 400
    prof = _engine_profile(body)
    if prof is None:
        return jsonify({"error": "unknown candidate_id or invalid skills"}), 404 if "candidate_id" in body else 400
    sim = CE.simulate(role, prof, learn[:30])
    return jsonify({**sim, "role": role, "before": {"fit_pct": sim["fit_before_pct"]}, "after": {"fit_pct": sim["fit_after_pct"]},
                    "note": "PROJECTION computed by the engine - not a guarantee of employment."})


@app.route("/api/analytics")
def analytics():
    totals = {}
    for role_data in ROLES.values():
        for skill, (imp, dem, pct) in role_data["skills"].items():
            totals[skill] = totals.get(skill, 0) + imp * DW[dem]
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    max_v = ranked[0][1] if ranked else 1
    return jsonify({
        "dataset": "illustrative sample (%d roles)" % len(ROLES),
        "top_demand_skills": [{"skill": s, "score": v, "relative_pct": round(v / max_v * 100, 1)} for s, v in ranked],
    })


# --- deployment settings (all optional; defaults keep local runs unchanged) ---
import os  # noqa: E402
if os.environ.get("SKILLTWIN_DB"):                      # e.g. a persistent-disk path on the host
    VDB.set_db_path(os.environ["SKILLTWIN_DB"])
if os.environ.get("SKILLTWIN_TRUST_PROXY") == "1":      # behind Render/Railway: real client IP for rate limits
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)
