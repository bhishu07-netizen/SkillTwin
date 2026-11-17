"""
Assessment lifecycle + persistence for the Skill Verification & Confidence Engine.

The client never submits a score. It submits raw answers; this module grades them
(MCQ/output by comparison with the server-side key, code by hidden unit tests in the
sandbox), measures time with the SERVER clock, locks every answer on submit, serves the
next question adaptively, and finally asks scoring.py for the result.
"""
import hashlib
import hmac
import json
import random
import secrets
import uuid

from . import adaptive, config as C, db as D, scoring
from . import sandbox
from .bank import advice_for, get_question, is_supported, questions_for


class EngineError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _acfg():
    return C.CONFIG["assessment"]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _norm_output(text: str) -> str:
    return "\n".join(line.rstrip() for line in str(text).strip().splitlines())


def option_order(seed: str, qid: str, n: int):
    idx = list(range(n))
    random.Random("%s|%s|opts" % (seed, qid)).shuffle(idx)
    return idx


def option_token(secret: str, attempt_id: str, qid: str, idx: int) -> str:
    return hmac.new(secret.encode(), ("%s|%s|%d" % (attempt_id, qid, idx)).encode(), hashlib.sha256).hexdigest()[:12]


def format_test(func: str, t: dict) -> dict:
    if "ops" in t:
        call = "%s(%s) then %s" % (func, ", ".join(repr(a) for a in t.get("ctor", [])),
                                   "; ".join("%s(%s)" % (o[0], ", ".join(repr(a) for a in o[1:])) for o in t["ops"][:12])
                                   + (" ..." if len(t["ops"]) > 12 else ""))
    elif "seq" in t:
        call = "calls in order: " + "; ".join("%s(%s)" % (func, ", ".join(repr(a) for a in c)) for c in t["seq"])
    else:
        call = "%s(%s)" % (func, ", ".join(repr(a) for a in t["args"]))
    exp = ("raises %s" % t["raises"]) if "raises" in t else repr(t["expected"])
    if len(call) > 300:
        call = call[:300] + "..."
    if len(exp) > 300:
        exp = exp[:300] + "..."
    return {"call": call, "expected": exp}


def _load_attempt(db, attempt_id, candidate_id=None):
    row = db.execute("SELECT * FROM assessment_attempts WHERE id=?", (attempt_id,)).fetchone()
    if not row:
        raise EngineError("unknown attempt", 404)
    if candidate_id is not None and row["candidate_id"] != candidate_id:
        raise EngineError("attempt does not belong to this candidate", 403)
    return row


def load_answers(db, attempt_id):
    rows = db.execute("SELECT a.*, q.type AS qtype FROM answers a JOIN questions q ON q.id=a.question_id "
                      "WHERE a.attempt_id=? ORDER BY a.position", (attempt_id,)).fetchall()
    out = []
    for r in rows:
        out.append({"qid": r["question_id"], "position": r["position"], "difficulty": r["difficulty"],
                    "category": r["category"], "concept": r["concept"], "score": r["score"],
                    "time_taken_s": r["time_taken_s"], "qtype": r["qtype"],
                    "client_meta": D.jloads(r["client_meta_json"], {}), "row": r})
    return out


def load_evidence(db, candidate_id, skill):
    rows = db.execute("SELECT * FROM evidence WHERE candidate_id=? AND skill=? ORDER BY created_at",
                      (candidate_id, skill)).fetchall()
    return [dict(r) for r in rows]


def _recent_seen(db, candidate_id, skill):
    n = _acfg()["recent_attempt_window"]
    rows = db.execute("SELECT state_json FROM assessment_attempts WHERE candidate_id=? AND skill=? "
                      "ORDER BY started_at DESC LIMIT ?", (candidate_id, skill, n)).fetchall()
    seen = set()
    for r in rows:
        for s in D.jloads(r["state_json"], {}).get("served", []):
            seen.add(s["qid"])
    return seen


def get_claim(db, candidate_id, skill):
    row = db.execute("SELECT claimed_level FROM skill_claims WHERE candidate_id=? AND skill=?",
                     (candidate_id, skill)).fetchone()
    return row["claimed_level"] if row else None


# ---------------------------------------------------------------------------
# public question payload (never contains the key, hidden tests, or explanations)
# ---------------------------------------------------------------------------

def public_question(db, attempt, q, position, state_entry):
    secret = D.option_secret(db)
    out = {"id": q["id"], "position": position, "type": q["type"], "category": q["category"],
           "category_label": C.CATEGORY_LABELS[q["category"]], "prompt": q["prompt"], "code": q.get("code"),
           "time_hint_s": q.get("time_hint_s", 90), "served_at": state_entry["served_at"]}
    if q["type"] in ("mcq", "scenario"):
        order = option_order(_state(attempt)["seed"], q["id"], len(q["options"]))
        out["options"] = [{"id": option_token(secret, attempt["id"], q["id"], i), "text": q["options"][i]} for i in order]
    elif q["type"] == "output":
        out["answer_format"] = "text"
    else:
        out["starter"] = q["starter"]
        out["function_name"] = q["func"]
        out["visible_tests"] = [format_test(q["func"], t) for t in q["tests"] if t.get("visible")]
        out["sample_runs_left"] = _acfg()["sample_run_limit"] - _state(attempt)["runs"].get(q["id"], 0)
    return out


def _state(attempt):
    return D.jloads(attempt["state_json"], {})


def _save_state(db, attempt_id, state):
    db.execute("UPDATE assessment_attempts SET state_json=? WHERE id=?", (json.dumps(state), attempt_id))


# ---------------------------------------------------------------------------
# starting / resuming
# ---------------------------------------------------------------------------

def start_attempt(db, candidate_id, skill):
    if not db.execute("SELECT 1 FROM candidates WHERE id=?", (candidate_id,)).fetchone():
        raise EngineError("unknown candidate", 404)
    if not is_supported(skill):
        raise EngineError("No assessment is available for '%s' yet." % skill, 422, code="unsupported_skill")
    claimed = get_claim(db, candidate_id, skill)
    if not claimed:
        raise EngineError("Declare this skill (and a proficiency level) before verifying it.", 422, code="no_claim")

    with D.tx(db):
        existing = db.execute("SELECT * FROM assessment_attempts WHERE candidate_id=? AND skill=? AND status='in_progress'",
                              (candidate_id, skill)).fetchone()
        if existing:
            if D.now() <= existing["deadline"]:
                return attempt_view(db, existing["id"], candidate_id, _in_tx=True)
            _finalize(db, existing, "expired", "time_limit")
        a_id, attempt_id = uuid.uuid4().hex, uuid.uuid4().hex
        seed = secrets.token_hex(8)
        now = D.now()
        limit = _acfg()["time_limit_s"]
        db.execute("INSERT INTO assessments(id, skill, claimed_level, variant_seed, time_limit_s, config_json, created_at) "
                   "VALUES (?,?,?,?,?,?,?)", (a_id, skill, claimed, seed, limit, json.dumps(C.CONFIG), now))
        state = {"seed": seed, "served": [], "current": None, "runs": {}}
        db.execute("INSERT INTO assessment_attempts(id, assessment_id, candidate_id, skill, claimed_level, status, "
                   "started_at, deadline, state_json) VALUES (?,?,?,?,?,?,?,?,?)",
                   (attempt_id, a_id, candidate_id, skill, claimed, "in_progress", now, now + limit, json.dumps(state)))
        attempt = _load_attempt(db, attempt_id)
        _serve_next(db, attempt, state, [])
    return attempt_view(db, attempt_id, candidate_id)


def _serve_next(db, attempt, state, answers):
    asked = {s["qid"] for s in state["served"]}
    q, reason = adaptive.select_next(attempt["skill"], answers, asked,
                                     _recent_seen(db, attempt["candidate_id"], attempt["skill"]), state["seed"])
    state["served"].append({"qid": q["id"], "position": len(state["served"]) + 1, "served_at": D.now(),
                            "reason": reason})
    state["current"] = q["id"]
    _save_state(db, attempt["id"], state)


def attempt_view(db, attempt_id, candidate_id, _in_tx=False):
    attempt = _load_attempt(db, attempt_id, candidate_id)
    if attempt["status"] == "in_progress" and D.now() > attempt["deadline"]:
        if _in_tx:
            _finalize(db, attempt, "expired", "time_limit")
        else:
            with D.tx(db):
                attempt = _load_attempt(db, attempt_id)
                if attempt["status"] == "in_progress":
                    _finalize(db, attempt, "expired", "time_limit")
        attempt = _load_attempt(db, attempt_id)
    state = _state(attempt)
    a = _acfg()
    view = {
        "attempt_id": attempt["id"], "skill": attempt["skill"], "claimed_level": attempt["claimed_level"],
        "status": attempt["status"], "started_at": attempt["started_at"], "deadline": attempt["deadline"],
        "server_now": D.now(), "seconds_remaining": max(0, round(attempt["deadline"] - D.now(), 1)),
        "time_limit_s": a["time_limit_s"], "answered": attempt["answered_count"],
        "min_questions": a["min_questions"], "max_questions": a["max_questions"],
        "stop_reason": attempt["stop_reason"],
    }
    if attempt["status"] == "in_progress" and state.get("current"):
        entry = next(s for s in state["served"] if s["qid"] == state["current"])
        view["question"] = public_question(db, attempt, get_question(state["current"]), entry["position"], entry)
    else:
        res = db.execute("SELECT id FROM verification_results WHERE attempt_id=?", (attempt_id,)).fetchone()
        view["result_id"] = res["id"] if res else None
        view["assessment_score"] = attempt["assessment_score"]
    return view


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------

def _grade(db, attempt, q, raw_answer):
    """Returns (score 0..1, stored_candidate_answer, expected_answer_text, details)."""
    t = q["type"]
    if t in ("mcq", "scenario"):
        secret = D.option_secret(db)
        by_token = {option_token(secret, attempt["id"], q["id"], i): i for i in range(len(q["options"]))}
        if raw_answer not in by_token:
            raise EngineError("Choose one of the listed options.", 400)
        chosen = by_token[raw_answer]
        return (1.0 if chosen == q["answer"] else 0.0, q["options"][chosen], q["options"][q["answer"]], {})
    if t == "output":
        text = "" if raw_answer is None else str(raw_answer)
        if len(text) > 2000:
            raise EngineError("Answer too long.", 400)
        ok = _norm_output(text) == _norm_output(q["expected"])
        return (1.0 if ok else 0.0, text, q["expected"], {})
    # code / debug -> sandbox against ALL tests
    source = "" if raw_answer is None else str(raw_answer)
    try:
        res = sandbox.run_function_tests(source, q["func"], q["tests"])
    except sandbox.SandboxRejected as e:
        return 0.0, source, "hidden unit tests", {"rejected": str(e), "passed": 0, "total": len(q["tests"])}
    details = {"passed": res["passed"], "total": res["total"], "timed_out": res["timed_out"], "fatal": res["fatal"],
               "failed_tests": [r["index"] for r in res["results"] if not r["passed"]]}
    return res["score"], source, "hidden unit tests (%d)" % res["total"], details


def submit_answer(db, attempt_id, candidate_id, question_id, answer, client_meta=None):
    client_meta = client_meta if isinstance(client_meta, dict) else {}
    meta = {"tab_switches": int(client_meta.get("tab_switches", 0) or 0),
            "pastes": int(client_meta.get("pastes", 0) or 0)}
    with D.tx(db):
        attempt = _load_attempt(db, attempt_id, candidate_id)
        if attempt["status"] != "in_progress":
            raise EngineError("This assessment is already finished.", 409, code="finished")
        if D.now() > attempt["deadline"]:
            _finalize(db, attempt, "expired", "time_limit")
            raise EngineError("Time is up - the assessment was closed.", 410, code="expired",
                              result_id=_result_id(db, attempt_id))
        state = _state(attempt)
        if state.get("current") != question_id:
            raise EngineError("That question is not the current question (answers are locked once submitted).",
                              409, code="not_current")
        q = get_question(question_id)
        entry = next(s for s in state["served"] if s["qid"] == question_id)
        score, stored, expected_text, details = _grade(db, attempt, q, answer)
        answered_at = D.now()
        details["qtype"] = q["type"]
        db.execute(
            "INSERT INTO answers(attempt_id, question_id, position, difficulty, category, concept, served_at, answered_at, "
            "time_taken_s, candidate_answer, expected_answer, is_correct, score, details_json, client_meta_json, selection_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (attempt_id, question_id, entry["position"], q["difficulty"], q["category"], q["concept"], entry["served_at"],
             answered_at, round(answered_at - entry["served_at"], 2), stored, expected_text,
             1 if scoring.is_correct(score) else 0, score, json.dumps(details), json.dumps(meta), entry["reason"]))
        state["current"] = None
        answers = load_answers(db, attempt_id)
        db.execute("UPDATE assessment_attempts SET answered_count=? WHERE id=?", (len(answers), attempt_id))
        stop, reason = adaptive.should_stop(answers)
        if stop:
            attempt = _load_attempt(db, attempt_id)
            _save_state(db, attempt_id, state)
            _finalize(db, attempt, "completed", reason)
        else:
            attempt = _load_attempt(db, attempt_id)
            _serve_next(db, attempt, state, answers)
    view = attempt_view(db, attempt_id, candidate_id)
    return {"accepted": True, "finished": view["status"] != "in_progress", "attempt": view}


def _result_id(db, attempt_id):
    r = db.execute("SELECT id FROM verification_results WHERE attempt_id=?", (attempt_id,)).fetchone()
    return r["id"] if r else None


def run_samples(db, attempt_id, candidate_id, question_id, code):
    """'Run sample tests': executes ONLY the visible tests; records nothing; capped per question."""
    with D.tx(db):
        attempt = _load_attempt(db, attempt_id, candidate_id)
        if attempt["status"] != "in_progress" or D.now() > attempt["deadline"]:
            raise EngineError("This assessment is not active.", 409)
        state = _state(attempt)
        if state.get("current") != question_id:
            raise EngineError("That question is not the current question.", 409)
        q = get_question(question_id)
        if q["type"] not in ("code", "debug"):
            raise EngineError("This question has no code to run.", 400)
        used = state["runs"].get(question_id, 0)
        limit = _acfg()["sample_run_limit"]
        if used >= limit:
            raise EngineError("Sample-run limit reached for this question (%d)." % limit, 429)
        state["runs"][question_id] = used + 1
        _save_state(db, attempt_id, state)
    visible = [t for t in q["tests"] if t.get("visible")]
    try:
        res = sandbox.run_function_tests(code if isinstance(code, str) else "", q["func"], visible)
    except sandbox.SandboxRejected as e:
        return {"rejected": str(e), "runs_left": limit - used - 1}
    return {"passed": res["passed"], "total": res["total"], "timed_out": res["timed_out"], "fatal": res["fatal"],
            "results": [{"call": format_test(q["func"], visible[r["index"]])["call"], "passed": r["passed"],
                         "expected": r.get("expected"), "got": r.get("got"), "error": r.get("error")}
                        for r in res["results"]],
            "runs_left": limit - used - 1,
            "note": "Sample tests only. Your submission is graded on additional hidden tests."}


def finish_attempt(db, attempt_id, candidate_id):
    with D.tx(db):
        attempt = _load_attempt(db, attempt_id, candidate_id)
        if attempt["status"] != "in_progress":
            return attempt_view(db, attempt_id, candidate_id, _in_tx=True)
        _finalize(db, attempt, "completed" if attempt["answered_count"] >= _acfg()["min_questions"] else "abandoned",
                  "candidate_finished")
    return attempt_view(db, attempt_id, candidate_id)


def _finalize(db, attempt, status, reason):
    """Close an attempt. Records a verification result only if enough questions were answered."""
    answers = load_answers(db, attempt["id"])
    now = min(D.now(), attempt["deadline"]) if status == "expired" else D.now()
    score = scoring.weighted_score(answers) if answers else None
    enough = len(answers) >= _acfg()["min_questions"]
    final_status = status if (enough or status == "abandoned") else ("expired" if status == "expired" else "abandoned")
    db.execute("UPDATE assessment_attempts SET status=?, completed_at=?, duration_s=?, assessment_score=?, stop_reason=?, "
               "answered_count=? WHERE id=?",
               (final_status, now, round(now - attempt["started_at"], 1), score,
                reason if enough else reason + ";insufficient_answers", len(answers), attempt["id"]))
    state = _state(attempt)
    state["current"] = None
    _save_state(db, attempt["id"], state)
    if enough:
        return build_and_store_result(db, attempt["id"])
    return None


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

def _evidence_items(db, candidate_id, skill):
    items = load_evidence(db, candidate_id, skill)
    return [{"type": e["type"], "status": "verified" if e["status"] == "verified" else "provided",
             "strength": e["strength"], "relevance": e["relevance"]} for e in items]


def _snapshot(db, candidate_id, trigger):
    """Record a readiness snapshot (best-effort: history must never break a verification)."""
    try:
        from career import history  # lazy: career.history imports this module
        history.snapshot(db, candidate_id, trigger)
    except Exception:  # noqa: BLE001
        pass


def build_and_store_result(db, attempt_id):
    attempt = _load_attempt(db, attempt_id)
    answers = load_answers(db, attempt_id)
    ev_items = _evidence_items(db, attempt["candidate_id"], attempt["skill"])
    res = scoring.compose_result(claimed=attempt["claimed_level"], answers=answers, evidence_items=ev_items,
                                 duration_s=attempt["duration_s"],
                                 time_limit_s=int(attempt["deadline"] - attempt["started_at"]))
    res["weaknesses"] = weaknesses(attempt["skill"], answers, res["breakdown"]["categories"])
    now = D.now()
    existing = db.execute("SELECT id, created_at FROM verification_results WHERE attempt_id=?", (attempt_id,)).fetchone()
    vals = (attempt["candidate_id"], attempt["skill"], res["claimed_level"], res["demonstrated_level"],
            res["assessment_score"], res["evidence_score"], res["verified_evidence_score"], res["consistency_score"],
            res["confidence"], res["badge"],
            json.dumps(res["discrepancy"]),
            json.dumps({"categories": res["breakdown"]["categories"], "difficulty": res["breakdown"]["difficulty"],
                        "questions_answered": res["breakdown"]["questions_answered"],
                        "questions_correct": res["breakdown"]["questions_correct"],
                        "formula": res["formula"], "level_notes": res["level_notes"]}),
            json.dumps(res["weaknesses"]), json.dumps(res["integrity"]), json.dumps(res["evidence_summary"]),
            json.dumps(C.CONFIG))
    if existing:
        db.execute("UPDATE verification_results SET candidate_id=?, skill=?, claimed_level=?, demonstrated_level=?, "
                   "assessment_score=?, evidence_score=?, verified_evidence_score=?, consistency_score=?, confidence=?, "
                   "badge=?, discrepancy_json=?, breakdown_json=?, weaknesses_json=?, integrity_json=?, "
                   "evidence_summary_json=?, config_json=?, updated_at=? WHERE attempt_id=?", vals + (now, attempt_id))
        rid = existing["id"]
    else:
        rid = uuid.uuid4().hex
        db.execute("INSERT INTO verification_results(id, attempt_id, candidate_id, skill, claimed_level, demonstrated_level, "
                   "assessment_score, evidence_score, verified_evidence_score, consistency_score, confidence, badge, "
                   "discrepancy_json, breakdown_json, weaknesses_json, integrity_json, evidence_summary_json, config_json, "
                   "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (rid, attempt_id) + vals + (now, now))
    _snapshot(db, attempt["candidate_id"], "verification")
    return rid


def weaknesses(skill, answers, categories):
    """Weak categories + missed concepts, with plain-language study pointers (authored, not generated)."""
    advice = advice_for(skill)
    weak_cats = [{"category": c, "label": v["label"], "score": v["score"]}
                 for c, v in categories.items() if v["score"] is not None and v["score"] < 60]
    weak_cats.sort(key=lambda x: x["score"])
    missed = []
    for a in answers:
        if a["score"] < C.CONFIG["assessment"]["correct_cut"]:
            q = get_question(a["qid"])
            missed.append({"concept": a["concept"], "category": a["category"], "difficulty": a["difficulty"],
                           "study": advice.get(a["concept"], a["concept"].replace("_", " ")),
                           "partial": a["score"] > 0, "score": round(a["score"], 2)})
    return {"weak_categories": weak_cats, "missed_concepts": missed}


def result_view(db, result_id=None, attempt_id=None):
    row = (db.execute("SELECT * FROM verification_results WHERE id=?", (result_id,)).fetchone() if result_id else
           db.execute("SELECT * FROM verification_results WHERE attempt_id=?", (attempt_id,)).fetchone())
    if not row:
        return None
    breakdown = D.jloads(row["breakdown_json"], {})
    attempt = db.execute("SELECT started_at, completed_at, duration_s, stop_reason, answered_count FROM assessment_attempts "
                         "WHERE id=?", (row["attempt_id"],)).fetchone()
    cur_claim = get_claim(db, row["candidate_id"], row["skill"])
    ev = [dict(e) for e in load_evidence(db, row["candidate_id"], row["skill"])]
    for e in ev:
        e["checks"] = D.jloads(e.pop("checks_json"), [])
    return {
        "result_id": row["id"], "attempt_id": row["attempt_id"], "candidate_id": row["candidate_id"], "skill": row["skill"],
        "claimed_level": row["claimed_level"], "demonstrated_level": row["demonstrated_level"],
        "assessment_score": row["assessment_score"], "evidence_score": row["evidence_score"],
        "verified_evidence_score": row["verified_evidence_score"], "consistency_score": row["consistency_score"],
        "confidence": row["confidence"], "badge": row["badge"],
        "discrepancy": D.jloads(row["discrepancy_json"]), "breakdown": breakdown,
        "weaknesses": D.jloads(row["weaknesses_json"]), "integrity": D.jloads(row["integrity_json"]),
        "evidence_summary": D.jloads(row["evidence_summary_json"]), "evidence": ev,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "attempt": dict(attempt) if attempt else None,
        "claim_changed_since": bool(cur_claim and cur_claim != row["claimed_level"]),
        "current_claim": cur_claim,
        "disclaimer": scoring.DISCLAIMER,
    }


def latest_result_row(db, candidate_id, skill):
    return db.execute("SELECT * FROM verification_results WHERE candidate_id=? AND skill=? "
                      "ORDER BY created_at DESC, rowid DESC LIMIT 1", (candidate_id, skill)).fetchone()


def recompute_latest_result(db, candidate_id, skill):
    """Evidence changed -> recompute the current result so confidence/badge reflect it (history rows keep snapshots)."""
    row = latest_result_row(db, candidate_id, skill)
    if row:
        build_and_store_result(db, row["attempt_id"])
        return row["id"]
    return None


def history(db, candidate_id, skill=None):
    q = ("SELECT r.*, a.duration_s, a.answered_count FROM verification_results r JOIN assessment_attempts a "
         "ON a.id=r.attempt_id WHERE r.candidate_id=?")
    args = [candidate_id]
    if skill:
        q += " AND r.skill=?"
        args.append(skill)
    rows = db.execute(q + " ORDER BY r.created_at DESC", args).fetchall()
    return [{"result_id": r["id"], "attempt_id": r["attempt_id"], "skill": r["skill"], "claimed_level": r["claimed_level"],
             "demonstrated_level": r["demonstrated_level"], "assessment_score": r["assessment_score"],
             "evidence_score": r["evidence_score"], "confidence": r["confidence"], "badge": r["badge"],
             "discrepancy": D.jloads(r["discrepancy_json"]).get("label"), "created_at": r["created_at"],
             "duration_s": r["duration_s"], "answered": r["answered_count"]} for r in rows]


def review(db, attempt_id, candidate_id):
    attempt = _load_attempt(db, attempt_id, candidate_id)
    if attempt["status"] == "in_progress":
        raise EngineError("Review is available after the assessment is finished.", 409)
    rows = db.execute("SELECT * FROM answers WHERE attempt_id=? ORDER BY position", (attempt_id,)).fetchall()
    out = []
    for r in rows:
        q = get_question(r["question_id"])
        det = D.jloads(r["details_json"], {})
        out.append({"position": r["position"], "question_id": r["question_id"], "type": q["type"],
                    "category": C.CATEGORY_LABELS[r["category"]], "concept": r["concept"], "difficulty": r["difficulty"],
                    "prompt": q["prompt"], "code": q.get("code"), "candidate_answer": r["candidate_answer"],
                    "expected_answer": r["expected_answer"], "score": r["score"], "correct": bool(r["is_correct"]),
                    "time_taken_s": r["time_taken_s"], "selection_reason": r["selection_reason"],
                    "explanation": q["explanation"],
                    "tests": ({"passed": det.get("passed"), "total": det.get("total"),
                               "rejected": det.get("rejected")} if q["type"] in ("code", "debug") else None)})
    return out


# ---------------------------------------------------------------------------
# candidate profile as seen by the role-fit engine
# ---------------------------------------------------------------------------

def effective_profile(db, candidate_id):
    claims = db.execute("SELECT skill, claimed_level FROM skill_claims WHERE candidate_id=? ORDER BY id",
                        (candidate_id,)).fetchall()
    out = {}
    for c in claims:
        skill, level = c["skill"], c["claimed_level"]
        declared = C.LEVEL_VALUE[level]
        res = latest_result_row(db, candidate_id, skill)
        entry = {"skill": skill, "declared_level": level, "declared_value": declared,
                 "assessable": is_supported(skill)}
        if res:
            entry.update({"basis": "verified", "demonstrated_level": res["demonstrated_level"],
                          "confidence": res["confidence"], "badge": res["badge"], "result_id": res["id"],
                          "effective_value": scoring.effective_value(res["demonstrated_level"], res["confidence"]),
                          "verified_claim_level": res["claimed_level"]})
        else:
            entry.update({"basis": "self-declared", "demonstrated_level": None, "confidence": None,
                          "badge": "SELF-DECLARED", "result_id": None,
                          "effective_value": scoring.unverified_value(declared)})
        out[skill] = entry
    return out
