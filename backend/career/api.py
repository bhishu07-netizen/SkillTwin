"""HTTP API for the Career Path Optimization Engine. Reads the verified profile from the verification engine."""
from flask import Blueprint, jsonify, request

from verification import engine as VENG
from verification import db as VDB
import llm
from . import copilot, data as D, engine as E, explain, history

bp = Blueprint("career", __name__)

DEMO_PROFILE = {"python": "Advanced", "statistics": "Intermediate", "sql": "Beginner",
                "machine learning": "Beginner"}   # Docker: none (absent)
DEMO_ROLE = "ML Engineer"

POSITIONING = {
    "tagline": "AI can generate a roadmap. SkillTwin computes YOUR shortest path.",
    "judge_answer": ("Any LLM can tell you what to learn for a career. The difference is that SkillTwin doesn't generate a "
                     "generic roadmap. It models the destination role, measures the candidate's verified starting point, "
                     "understands skill dependencies, weights gaps using market demand, and computes the shortest "
                     "personalized path between the two. AI only explains the result."),
}

COMPARISON = [
    {"aspect": "Starting point", "generic": "Assumes you know nothing or guesses from your wording",
     "skilltwin": "Your verified levels and confidence; self-declared claims are flagged"},
    {"aspect": "Skill dependencies", "generic": "Often implied in prose, unchecked", "skilltwin": "Explicit graph, topologically ordered"},
    {"aspect": "Prioritisation", "generic": "Opinion", "skilltwin": "importance x market demand x gap x criticality, traceable"},
    {"aspect": "What you already know", "generic": "Repeats it", "skilltwin": "Skips it and says how many skills/hours that saves"},
    {"aspect": "Repeatability", "generic": "Different answer each run", "skilltwin": "Same inputs, same path"},
    {"aspect": "Numbers", "generic": "May invent statistics", "skilltwin": "Every number traces to the dataset ([View Evidence])"},
]


def _err(msg, code=400, **kw):
    return jsonify({"error": msg, **kw}), code


def _resolve(body):
    """role + profile + cfg from a request body. Returns (role, profile, cfg, meta) or an error response."""
    role = body.get("role")
    if not isinstance(role, str) or role not in D.ROLES:
        return _err("unknown role", 400, known_roles=list(D.ROLES))
    if not isinstance(body.get("weights", {}), dict):
        return _err("weights must be an object")
    cfg = E.cfg_with({k: body[k] for k in ("weights", "hours_per_week") if k in body})
    trust = bool(body.get("trust_declared", False))
    meta = {"trust_declared": trust}
    if body.get("candidate_id") is not None and not isinstance(body["candidate_id"], str):
        return _err("candidate_id must be a string")
    if body.get("candidate_id"):
        db = VDB.get_db()
        if not db.execute("SELECT 1 FROM candidates WHERE id=?", (body["candidate_id"],)).fetchone():
            return _err("unknown candidate_id", 404)
        vp = VENG.effective_profile(db, body["candidate_id"])
        profile = E.build_profile(verification_profile=vp, trust_declared=trust, cfg=cfg)
        meta["source"] = "candidate"
    else:
        decl = body.get("declared") or {}
        if not isinstance(decl, dict) or len(decl) > 60:
            return _err("declared must be an object of {skill: level} (max 60 skills)")
        bad = [s for s in decl if s not in D.SKILLS]
        if bad:
            return _err("unknown skills", 400, unknown=bad)
        badlvl = {s: l for s, l in decl.items() if l not in E.LEVEL_VALUE}
        if badlvl:
            return _err("invalid levels", 400, invalid=badlvl, allowed=list(E.LEVEL_VALUE))
        profile = E.build_profile(declared=decl, trust_declared=trust, cfg=cfg)
        meta["source"] = "inline-declared"
    meta["verified_count"] = sum(1 for p in profile.values() if p["basis"] == "verified")
    meta["declared_count"] = len(profile) - meta["verified_count"]
    return role, profile, cfg, meta


@bp.route("/api/career/roles")
def roles():
    q = request.args.get("q", "")
    return jsonify({"query": q, "results": E.search_roles(q), "all_roles": E.roles_overview(), "dataset_note": D.DATASET_NOTE})


@bp.route("/api/career/config")
def config():
    return jsonify({"config": E.CONFIG, "formula": "priority = 100 x weighted geometric mean(importance, demand, gap, criticality)",
                    "dataset_note": D.DATASET_NOTE, "skills": len(D.SKILLS), "roles": len(D.ROLES)})


@bp.route("/api/career/demo-profile")
def demo_profile():
    return jsonify({"declared": DEMO_PROFILE, "role": DEMO_ROLE, "trust_declared": True,
                    "note": "Judge demo: claims are taken at face value here (not verified). Verify skills in the Verification tab to see the same engine use measured levels.",
                    "positioning": POSITIONING})


@bp.route("/api/career/reverse-engineer", methods=["POST"])
def reverse_engineer():
    r = _resolve(request.get_json(force=True, silent=True) or {})
    if not isinstance(r, tuple) or len(r) != 4:
        return r
    role, profile, cfg, meta = r
    if meta["source"] == "candidate":
        history.snapshot(VDB.get_db(), request.get_json(silent=True)["candidate_id"], "viewed")
    res = E.analyze(role, profile, cfg)
    moves = E.best_next_moves(role, profile, cfg)
    exp = explain.ai(res, moves) or explain.deterministic(res, moves)
    reqs = D.ROLES[role]["reqs"]
    return jsonify({
        **res, "profile": {s: {k: v for k, v in p.items()} for s, p in profile.items()}, "meta": meta,
        "best_next_moves": moves, "explanation": exp, "comparison": COMPARISON, "positioning": POSITIONING,
        "pipeline": [
            {"stage": "Verified profile", "detail": "%d skills (%d verified, %d self-declared)" % (len(profile), meta["verified_count"], meta["declared_count"])},
            {"stage": "Role requirement graph", "detail": "%s: %d required skills" % (role, len(reqs))},
            {"stage": "Gap engine", "detail": "%d skills still needed, %d already satisfied" % (len(res["steps"]), len(res["skipped"]))},
            {"stage": "Dependency-ordered path", "detail": "%d phases, %s hours" % (len(res["phases"]), res["total_hours"])},
        ],
        "config": cfg, "dataset_note": D.DATASET_NOTE,
    })


@bp.route("/api/career/simulate", methods=["POST"])
def simulate():
    body = request.get_json(force=True, silent=True) or {}
    r = _resolve(body)
    if not isinstance(r, tuple) or len(r) != 4:
        return r
    role, profile, cfg, meta = r
    learn = body.get("learn") or []
    if not isinstance(learn, list) or not all(isinstance(x, str) for x in learn) or len(learn) > 40:
        return _err("learn must be a list of up to 40 skill names")
    sim = E.simulate(role, profile, learn[:30], cfg)
    if meta["source"] == "candidate" and not meta["trust_declared"]:
        sim["projection_id"] = history.record_projection(VDB.get_db(), body["candidate_id"], role, sim)
    return jsonify(sim)


@bp.route("/api/career/history/<cid>")
def career_history(cid):
    db = VDB.get_db()
    if not db.execute("SELECT 1 FROM candidates WHERE id=?", (cid,)).fetchone():
        return _err("unknown candidate_id", 404)
    role = request.args.get("role")
    if role and role not in D.ROLES:
        return _err("unknown role", 400, known_roles=list(D.ROLES))
    history.snapshot(db, cid, "viewed")
    return jsonify(history.history(db, cid, role))


@bp.route("/api/career/evidence/<role>/<skill>")
def evidence(role, skill):
    if role not in D.ROLES or skill not in D.SKILLS:
        return _err("unknown role or skill", 404)
    return jsonify(E.evidence_for(role, skill))


@bp.route("/api/career/fit-all", methods=["POST"])
def fit_all():
    """Role fit for every role at once (drives the role grid)."""
    body = request.get_json(force=True, silent=True) or {}
    body = {**body, "role": next(iter(D.ROLES))}
    r = _resolve(body)
    if not isinstance(r, tuple) or len(r) != 4:
        return r
    _, profile, _, meta = r
    return jsonify({"fits": E.fit_all(profile), "meta": meta})


@bp.route("/api/career/copilot", methods=["POST"])
def copilot_route():
    body = request.get_json(force=True, silent=True) or {}
    msg = body.get("message")
    if not isinstance(msg, str) or not msg.strip() or len(msg) > 500:
        return _err("message must be 1-500 characters")
    selected = body.get("role") if isinstance(body.get("role"), str) and body.get("role") in D.ROLES else None
    r = _resolve({**body, "role": selected or next(iter(D.ROLES))})
    if not isinstance(r, tuple) or len(r) != 4:
        return r
    _, profile, cfg, _ = r
    return jsonify(copilot.respond(msg, selected, profile, cfg))


def _skills_text(profile):
    return ", ".join(sorted(profile)) or "no skills entered yet"


@bp.route("/api/ai/status")
def ai_status():
    """Is AI wording configured? Never returns the key."""
    out = {"configured": llm.configured(), "model": llm.model_name() if llm.configured() else None}
    if request.args.get("test") == "1" and llm.configured():      # live check: GET /api/ai/status?test=1
        out["working"] = bool(llm.generate("Reply with exactly the single word: ready", timeout=15, cache=False))
        out["error"] = llm.last_error()
        out["answered_by"] = llm.last_model() if out["working"] else None
    return jsonify(out)


@bp.route("/api/ai/generate", methods=["POST"])
def ai_generate():
    """Server-side prompts for the non-calculation AI features (Future Watch, outreach wording).
    Not an open proxy: the client supplies only a kind and a role; prompts are fixed here; the key never leaves the server."""
    body = request.get_json(force=True, silent=True) or {}
    kind = body.get("kind")
    role = body.get("role") if isinstance(body.get("role"), str) and body.get("role") in D.ROLES else None
    if kind not in ("future_watch", "outreach_mentor", "outreach_recruiter"):
        return _err("unknown kind")
    if not llm.configured():
        return _err("AI wording is not configured on this server (set GEMINI_API_KEY). Calculated features are unaffected.", 503)
    r = _resolve({**body, "role": role or next(iter(D.ROLES))})
    if not isinstance(r, tuple) or len(r) != 4:
        return r
    _, profile, cfg, _ = r
    if kind == "future_watch":
        prompt = ("You are generating a 'Future Watch' panel for a career app. Target role: %s. Candidate skills: %s. Give exactly 4 "
                  "emerging technology or industry-direction items based on general knowledge (not live news). For each: trend, "
                  "why_it_matters (1 sentence), connects_to_skill (one of: %s, or null), confidence_note (short phrase flagging it as a "
                  "general speculative direction). Do NOT invent statistics, market sizes, companies or dates. Respond ONLY as a JSON "
                  "array of 4 objects." % (role or "general tech careers", _skills_text(profile), ", ".join(sorted(D.SKILLS))))
    else:
        top = E.analyze(role, profile, cfg)["critical_gaps"][:1] if role and profile is not None else []
        who = ("an experienced professional or mentor in this field, asking for a short informational chat"
               if kind == "outreach_mentor" else "a recruiter or HR contact, introducing yourself as a candidate interested in this role")
        prompt = ("Write a short, warm, professional LinkedIn outreach message (under 80 words) to %s. Target role: %s. Candidate skills: %s. "
                  "Top skill gap: %s. Use only these facts; do not invent achievements, companies, dates or credentials. Leave [Name] as a "
                  "placeholder. Plain text only." % (who, role or "unspecified", _skills_text(profile), top[0] if top else "none"))
    text = llm.generate(prompt, timeout=20)
    if not text:
        busy = "429" in (llm.last_error() or "")
        return _err(("AI wording is busy right now (usage limit reached), try again in a minute." if busy
                     else "AI wording is unavailable right now.") + " Calculated features are unaffected.", 502)
    return jsonify({"kind": kind, "text": text, "source": "ai:" + llm.last_model(),
                    "note": "AI wording only - generated text, not computed results"})
