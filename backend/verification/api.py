"""HTTP API for candidates, claims, assessments, evidence, results and role impact."""
import json
import uuid

from flask import Blueprint, jsonify, request

import core
from . import config as C, db as D, engine, evidence as EV, explain, sandbox, scoring
from .bank import bank_stats, is_supported, supported_skills

bp = Blueprint("verification", __name__)


def _body():
    return request.get_json(force=True, silent=True) or {}


@bp.errorhandler(engine.EngineError)
def _engine_error(e):
    return jsonify({"error": str(e), **e.extra}), e.status


def _cand(db, cid):
    row = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    if not row:
        raise engine.EngineError("unknown candidate", 404)
    return row


# ---------------- candidates & claims ----------------

@bp.route("/api/candidates", methods=["POST"])
def create_candidate():
    b = _body()
    cid = str(uuid.uuid4())
    db = D.get_db()
    db.execute("INSERT INTO candidates(id, skills_json, name) VALUES (?,?,?)", (cid, "{}", (b.get("name") or "")[:80]))
    import security  # noqa: PLC0415
    return jsonify({"candidate_id": cid, "token": security.token_for(cid)}), 201


def _claim_level(v):
    """Accepts 'Beginner'/'Intermediate'/'Advanced' or the legacy 0.4/0.7/1.0."""
    if isinstance(v, str) and v.capitalize() in C.CLAIMABLE_LEVELS:
        return v.capitalize()
    if isinstance(v, (int, float)) and float(v) in C.LEGACY_TO_LEVEL:
        return C.LEGACY_TO_LEVEL[float(v)]
    raise engine.EngineError("level must be one of %s" % C.CLAIMABLE_LEVELS, 400)


def _sync_legacy(db, cid):
    claims = db.execute("SELECT skill, claimed_level FROM skill_claims WHERE candidate_id=?", (cid,)).fetchall()
    db.execute("UPDATE candidates SET skills_json=? WHERE id=?",
               (json.dumps({r["skill"]: C.LEVEL_VALUE[r["claimed_level"]] for r in claims}), cid))


def _profile_payload(db, cid):
    prof = engine.effective_profile(db, cid)
    cfg = C.CONFIG["profile"]
    return {"candidate_id": cid, "skills": prof,
            "declared": {s: p["declared_value"] for s, p in prof.items()},
            "effective": {s: p["effective_value"] for s, p in prof.items()},
            "unverified_weight": cfg["unverified_weight"]}


@bp.route("/api/candidates/<cid>", methods=["GET"])
def get_candidate(cid):
    db = D.get_db()
    row = _cand(db, cid)
    out = _profile_payload(db, cid)
    out.update({"name": row["name"], "github_username": row["github_username"]})
    return jsonify(out)


@bp.route("/api/candidates/<cid>", methods=["PATCH"])
def patch_candidate(cid):
    db = D.get_db()
    _cand(db, cid)
    b = _body()
    gh = (b.get("github_username") or "").strip()[:60]
    db.execute("UPDATE candidates SET github_username=?, name=COALESCE(?, name) WHERE id=?",
               (gh or None, b.get("name"), cid))
    return jsonify({"ok": True})


@bp.route("/api/candidates/<cid>/claims", methods=["PUT"])
def put_claims(cid):
    """Body {"claims": {"python": "Advanced", ...}, "replace": bool}. Verification history is never deleted."""
    db = D.get_db()
    _cand(db, cid)
    b = _body()
    claims = b.get("claims") or {}
    if not isinstance(claims, dict):
        raise engine.EngineError("claims must be an object", 400)
    clean = {}
    for skill, lvl in claims.items():
        s = str(skill).strip().lower()
        if s not in core.TAXONOMY:
            raise engine.EngineError("unknown skill '%s'" % skill, 400, known_skills=sorted(core.TAXONOMY))
        clean[s] = _claim_level(lvl)
    now = D.now()
    with D.tx(db):
        if b.get("replace"):
            for r in db.execute("SELECT skill FROM skill_claims WHERE candidate_id=?", (cid,)).fetchall():
                if r["skill"] not in clean:
                    db.execute("DELETE FROM skill_claims WHERE candidate_id=? AND skill=?", (cid, r["skill"]))
        for s, lvl in clean.items():
            db.execute("INSERT INTO skill_claims(candidate_id, skill, claimed_level, created_at, updated_at) VALUES (?,?,?,?,?) "
                       "ON CONFLICT(candidate_id, skill) DO UPDATE SET claimed_level=excluded.claimed_level, "
                       "updated_at=excluded.updated_at", (cid, s, lvl, now, now))
        _sync_legacy(db, cid)
    engine._snapshot(db, cid, "claims")
    return jsonify(_profile_payload(db, cid))


@bp.route("/api/candidates/<cid>/claims/<skill>", methods=["DELETE"])
def delete_claim(cid, skill):
    db = D.get_db()
    _cand(db, cid)
    with D.tx(db):
        db.execute("DELETE FROM skill_claims WHERE candidate_id=? AND skill=?", (cid, skill.lower()))
        _sync_legacy(db, cid)
    engine._snapshot(db, cid, "claims")
    return jsonify(_profile_payload(db, cid))


# ---------------- config & skills ----------------

@bp.route("/api/verification/config")
def get_config():
    return jsonify({"config": C.CONFIG, "sandbox": sandbox.describe(), "disclaimer": scoring.DISCLAIMER,
                    "badges": scoring.BADGES, "integrity_measures": INTEGRITY_MEASURES})


INTEGRITY_MEASURES = [
    "Server-side timer for the whole assessment (client clock is ignored)",
    "Question order adapts to your answers and options are shuffled per attempt",
    "Every assessment draws from a bank ~3x larger than what is shown; retakes prefer unseen questions",
    "Answers are locked on submit - no going back or changing them",
    "Time per question is measured by the server; implausibly fast answers are flagged",
    "Code runs in an isolated, resource-limited sandbox against hidden tests",
    "Tab-switch and paste counts are recorded as advisory signals",
]


@bp.route("/api/verification/skills")
def list_assessable():
    out = []
    for skill in core.TAXONOMY:
        sup = is_supported(skill)
        out.append({"skill": skill, "assessable": sup, **({"bank": bank_stats(skill)} if sup else {})})
    return jsonify({"skills": out, "assessable": supported_skills(),
                    "evidence_types": EV.EVIDENCE_TYPES, "integrity_measures": INTEGRITY_MEASURES,
                    "assessment": {k: C.CONFIG["assessment"][k] for k in ("min_questions", "max_questions", "time_limit_s")}})


# ---------------- attempts ----------------

@bp.route("/api/verification/attempts", methods=["POST"])
def start_attempt():
    b = _body()
    return jsonify(engine.start_attempt(D.get_db(), b.get("candidate_id"), (b.get("skill") or "").lower())), 201


@bp.route("/api/verification/attempts/<aid>")
def get_attempt(aid):
    return jsonify(engine.attempt_view(D.get_db(), aid, request.args.get("candidate_id")))


@bp.route("/api/verification/attempts/<aid>/answer", methods=["POST"])
def answer(aid):
    b = _body()
    return jsonify(engine.submit_answer(D.get_db(), aid, b.get("candidate_id"), b.get("question_id"),
                                        b.get("answer"), b.get("client_meta")))


@bp.route("/api/verification/attempts/<aid>/run", methods=["POST"])
def run(aid):
    b = _body()
    return jsonify(engine.run_samples(D.get_db(), aid, b.get("candidate_id"), b.get("question_id"), b.get("code")))


@bp.route("/api/verification/attempts/<aid>/finish", methods=["POST"])
def finish(aid):
    return jsonify(engine.finish_attempt(D.get_db(), aid, _body().get("candidate_id")))


@bp.route("/api/verification/attempts/<aid>/review")
def review(aid):
    return jsonify({"review": engine.review(D.get_db(), aid, request.args.get("candidate_id"))})


# ---------------- results ----------------

@bp.route("/api/verification/results")
def results():
    cid, skill = request.args.get("candidate_id"), request.args.get("skill")
    db = D.get_db()
    _cand(db, cid)
    hist = engine.history(db, cid, skill.lower() if skill else None)
    latest = None
    if skill:
        row = engine.latest_result_row(db, cid, skill.lower())
        latest = engine.result_view(db, result_id=row["id"]) if row else None
    return jsonify({"latest": latest, "history": hist})


@bp.route("/api/verification/results/<rid>")
def result(rid):
    r = engine.result_view(D.get_db(), result_id=rid)
    if not r:
        raise engine.EngineError("unknown result", 404)
    return jsonify(r)


@bp.route("/api/verification/results/<rid>/explain", methods=["POST"])
def explain_result(rid):
    db = D.get_db()
    r = engine.result_view(db, result_id=rid)
    if not r:
        raise engine.EngineError("unknown result", 404)
    rv = engine.review(db, r["attempt_id"], r["candidate_id"])
    out = explain.ai(r, rv) if _body().get("use_ai", True) else None
    return jsonify(out or explain.deterministic(r, rv))


# ---------------- evidence ----------------

def _evidence_view(row):
    d = dict(row)
    d["checks"] = D.jloads(d.pop("checks_json"), [])
    return d


@bp.route("/api/verification/evidence", methods=["GET"])
def list_evidence():
    db = D.get_db()
    cid, skill = request.args.get("candidate_id"), (request.args.get("skill") or "").lower()
    _cand(db, cid)
    return jsonify({"evidence": [_evidence_view(e) for e in engine.load_evidence(db, cid, skill)]})


@bp.route("/api/verification/evidence", methods=["POST"])
def add_evidence():
    db = D.get_db()
    b = _body()
    cid, skill = b.get("candidate_id"), (b.get("skill") or "").lower()
    cand = _cand(db, cid)
    if not db.execute("SELECT 1 FROM skill_claims WHERE candidate_id=? AND skill=?", (cid, skill)).fetchone():
        raise engine.EngineError("Declare this skill before attaching evidence to it.", 422)
    n = db.execute("SELECT COUNT(*) c FROM evidence WHERE candidate_id=? AND skill=?", (cid, skill)).fetchone()["c"]
    if n >= C.CONFIG["evidence"]["max_items_per_skill"]:
        raise engine.EngineError("Evidence limit reached for this skill.", 429)
    try:
        res = EV.evaluate(skill, b.get("type"), b.get("title"), b.get("url"), b.get("description"), b.get("code"),
                          cand["github_username"])
    except EV.EvidenceError as e:
        raise engine.EngineError(str(e), 400)
    eid = uuid.uuid4().hex
    with D.tx(db):
        db.execute("INSERT INTO evidence(id, candidate_id, skill, type, title, url, description, status, strength, relevance, "
                   "checks_json, limitations, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (eid, cid, skill, b["type"], res["title"], res["url"], res["description"], res["status"], res["strength"],
                    res["relevance"], json.dumps(res["checks"]), res["limitations"], D.now()))
        rid = engine.recompute_latest_result(db, cid, skill)
    return jsonify({"evidence": _evidence_view(db.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()),
                    "result_id": rid, "profile": _profile_payload(db, cid)}), 201


@bp.route("/api/verification/evidence/<eid>", methods=["DELETE"])
def delete_evidence(eid):
    db = D.get_db()
    cid = request.args.get("candidate_id")
    row = db.execute("SELECT * FROM evidence WHERE id=? AND candidate_id=?", (eid, cid)).fetchone()
    if not row:
        raise engine.EngineError("unknown evidence", 404)
    with D.tx(db):
        db.execute("DELETE FROM evidence WHERE id=?", (eid,))
        engine.recompute_latest_result(db, cid, row["skill"])
    return jsonify({"ok": True, "profile": _profile_payload(db, cid)})


# ---------------- career impact ----------------

@bp.route("/api/candidates/<cid>/impact")
def impact(cid):
    """Fit per role using self-declared levels vs verification-adjusted levels (same engine, two inputs)."""
    db = D.get_db()
    _cand(db, cid)
    p = _profile_payload(db, cid)
    rows = []
    for role in core.ROLES:
        fd, fe = core.fit_score(role, p["declared"]), core.fit_score(role, p["effective"])
        rows.append({"role": role, "declared_fit_pct": round(fd * 100, 1), "verified_fit_pct": round(fe * 100, 1),
                     "delta_pct": round((fe - fd) * 100, 1)})
    rows.sort(key=lambda r: r["verified_fit_pct"], reverse=True)
    return jsonify({"roles": rows, "best_role": rows[0]["role"] if rows else None, "skills": p["skills"],
                    "note": "Verified fit uses demonstrated level scaled by confidence; unverified claims count at "
                            "%d%%." % round(100 * C.CONFIG["profile"]["unverified_weight"])})
