"""
Deterministic scoring - the single source of truth for every number SkillTwin
shows about a verified skill. Pure functions only: no I/O, no randomness, no LLM.

    assessment_score   difficulty-weighted accuracy over the questions asked (0-100)
    evidence_score     noisy-OR aggregate of per-item evidence strength (0-100)
    consistency_score  how well the claim matches measured performance (0-100)
    confidence         weights.assessment*A + weights.evidence*E + weights.consistency*C
    demonstrated level thresholds on the ASSESSMENT score (not on confidence), with guards
"""
from . import config as C

BADGES = ["SELF-DECLARED", "PARTIALLY VERIFIED", "EVIDENCE-BACKED", "VERIFIED"]

DISCLAIMER = ("SkillTwin does not attempt to detect lies. It evaluates whether a skill claim is "
              "supported by measurable evidence.")


def cfg():
    return C.CONFIG


def level_index(level: str) -> int:
    return C.LEVELS.index(level)


def level_from_score(score: float) -> str:
    t = cfg()["level_thresholds"]
    if score >= t["Expert"]:
        return "Expert"
    if score >= t["Advanced"]:
        return "Advanced"
    if score >= t["Intermediate"]:
        return "Intermediate"
    return "Beginner"


def is_correct(score: float) -> bool:
    return score >= cfg()["assessment"]["correct_cut"]


def weighted_score(answers) -> float:
    """answers: iterable of {'difficulty': str, 'score': 0..1}. Returns 0-100."""
    w = cfg()["difficulty_weights"]
    num = den = 0.0
    for a in answers:
        num += w[a["difficulty"]] * a["score"]
        den += w[a["difficulty"]]
    return round(100.0 * num / den, 2) if den else 0.0


def category_breakdown(answers) -> dict:
    out = {}
    for cat in C.CATEGORY_LABELS:
        rows = [a for a in answers if a["category"] == cat]
        if not rows:
            out[cat] = {"label": C.CATEGORY_LABELS[cat], "score": None, "questions": 0, "correct": 0}
            continue
        out[cat] = {"label": C.CATEGORY_LABELS[cat], "score": weighted_score(rows),
                    "questions": len(rows), "correct": sum(1 for a in rows if is_correct(a["score"]))}
    return out


def difficulty_breakdown(answers) -> dict:
    out = {}
    for d in ("easy", "medium", "hard"):
        rows = [a for a in answers if a["difficulty"] == d]
        out[d] = {"questions": len(rows),
                  "accuracy": round(100 * sum(a["score"] for a in rows) / len(rows), 1) if rows else None}
    return out


def hard_stats(answers):
    hard = [a for a in answers if a["difficulty"] == "hard"]
    acc = (sum(a["score"] for a in hard) / len(hard)) if hard else 0.0
    return len(hard), acc


def demonstrated_level(score: float, answers):
    """Level from thresholds, then guards so a high level needs enough hard-question evidence."""
    g = cfg()["level_guards"]
    level = level_from_score(score)
    notes = []
    n_hard, hard_acc = hard_stats(answers)
    if level == "Expert" and (n_hard < g["min_hard_for_expert"] or hard_acc < g["min_hard_accuracy_for_expert"]):
        level = "Advanced"
        notes.append("Capped at Advanced: Expert needs at least %d hard questions answered with %d%% accuracy "
                     "(you attempted %d, accuracy %d%%)." % (g["min_hard_for_expert"],
                                                           round(100 * g["min_hard_accuracy_for_expert"]),
                                                           n_hard, round(100 * hard_acc)))
    if level == "Advanced" and n_hard < g["min_hard_for_advanced"]:
        level = "Intermediate"
        notes.append("Capped at Intermediate: Advanced needs at least %d hard questions attempted (you attempted %d)."
                     % (g["min_hard_for_advanced"], n_hard))
    return level, notes


def consistency_score(claimed: str, assessment_score: float) -> float:
    c = cfg()["consistency"]
    d = assessment_score - cfg()["claim_midpoints"][claimed]
    if d < 0:
        penalty = c["over_claim_factor"] * (-d)
    else:
        penalty = min(c["under_claim_max_penalty"], c["under_claim_factor"] * d)
    return round(max(0.0, min(100.0, 100.0 - penalty)), 2)


def confidence(assessment: float, evidence: float, consistency: float) -> float:
    w = cfg()["weights"]
    return round(w["assessment"] * assessment + w["evidence"] * evidence + w["consistency"] * consistency, 1)


def discrepancy(claimed: str, demonstrated: str, assessment_score: float) -> dict:
    ci, di = level_index(claimed), level_index(demonstrated)
    margin = cfg()["discrepancy"]["near_margin"]
    base = {"claimed": claimed, "demonstrated": demonstrated, "disclaimer": DISCLAIMER}
    if di == ci:
        return {**base, "code": "claim_supported", "label": "Claim supported",
                "message": "Your measured performance is consistent with a %s claim." % claimed}
    if di > ci:
        return {**base, "code": "skill_underestimated", "label": "Skill may be underestimated",
                "message": "You performed at %s level, above your declared %s." % (demonstrated, claimed)}
    lower_bound = cfg()["level_thresholds"].get(claimed, 0)
    if assessment_score >= lower_bound - margin:
        gap = round(lower_bound - assessment_score, 1)
        return {**base, "code": "claim_near", "label": "Claim nearly supported",
                "message": "Your performance was %s points short of the %s threshold - close, but not yet demonstrated. "
                           "A retake or supporting evidence could close the gap." % (max(gap, 0), claimed)}
    return {**base, "code": "overestimation", "label": "Claim exceeds demonstrated proficiency",
            "message": "Potential overestimation detected: assessment performance matched %s, below the declared %s. "
                       "This is a skill gap to work on, not a verdict." % (demonstrated, claimed)}


def integrity_summary(answers, duration_s, time_limit_s) -> dict:
    rapid_cfg = cfg()["badges"]["rapid_answer_seconds"]
    rapid = 0
    tab_switches = pastes = 0
    for a in answers:
        grp = "mcq" if a["qtype"] in ("mcq", "scenario") else "output" if a["qtype"] == "output" else "code"
        if a["time_taken_s"] < rapid_cfg[grp]:
            rapid += 1
        meta = a.get("client_meta") or {}
        tab_switches += int(meta.get("tab_switches", 0) or 0)
        pastes += int(meta.get("pastes", 0) or 0)
    ok = rapid <= cfg()["badges"]["verified_max_rapid_answers"]
    return {"rapid_answers": rapid, "tab_switches_reported": tab_switches, "pastes_reported": pastes,
            "duration_s": round(duration_s, 1) if duration_s is not None else None,
            "time_limit_s": time_limit_s, "server_checks_ok": ok,
            "note": "Advisory integrity signals. Only server-measured rapid answers can block the VERIFIED badge; "
                    "browser-reported signals are informational."}


# ---------------------------------------------------------------------------
# Evidence aggregation
# ---------------------------------------------------------------------------

def evidence_scores(items) -> dict:
    """
    items: [{'type', 'status', 'strength' (0..1, already includes provided_factor for unverified), 'relevance'}]
    Noisy-OR: each item independently 'convinces' with probability strength*type_weight, so more
    evidence helps with diminishing returns and can never exceed 100.
    """
    ec = cfg()["evidence"]
    tw = ec["type_weights"]
    prod_all = prod_ver = 1.0
    verified_n = 0
    for it in items:
        s = max(0.0, min(1.0, it["strength"])) * tw.get(it["type"], 0.5)
        prod_all *= (1 - s)
        if it["status"] == "verified" and it["strength"] >= ec["verified_min_strength"]:
            prod_ver *= (1 - s)
            verified_n += 1
    return {"evidence_score": round(100 * (1 - prod_all), 2),
            "verified_evidence_score": round(100 * (1 - prod_ver), 2),
            "verified_items": verified_n}


def evidence_summary(items) -> dict:
    by_type = {}
    for it in items:
        by_type[it["type"]] = by_type.get(it["type"], 0) + 1
    return {
        "total": len(items),
        "provided": sum(1 for i in items if i["status"] != "verified"),
        "verified": sum(1 for i in items if i["status"] == "verified"),
        "relevant": sum(1 for i in items if i["relevance"] >= 0.3),
        "by_type": by_type,
    }


def badge_for(*, has_assessment: bool, verified_evidence: float, conf: float, claimed: str, demonstrated: str,
              integrity_ok: bool) -> str:
    if not has_assessment:
        return "SELF-DECLARED"
    b = cfg()["badges"]
    backed = verified_evidence >= b["evidence_backed_min_verified_evidence"]
    if backed and conf >= b["verified_min_confidence"] and level_index(demonstrated) >= level_index(claimed) \
            and integrity_ok:
        return "VERIFIED"
    if backed:
        return "EVIDENCE-BACKED"
    return "PARTIALLY VERIFIED"


def compose_result(*, claimed: str, answers, evidence_items, duration_s, time_limit_s) -> dict:
    """Everything derived from raw answers + evidence. Deterministic."""
    a_score = weighted_score(answers)
    level, notes = demonstrated_level(a_score, answers)
    ev = evidence_scores(evidence_items)
    cons = consistency_score(claimed, a_score)
    conf = confidence(a_score, ev["evidence_score"], cons)
    integ = integrity_summary(answers, duration_s, time_limit_s)
    badge = badge_for(has_assessment=True, verified_evidence=ev["verified_evidence_score"], conf=conf,
                      claimed=claimed, demonstrated=level, integrity_ok=integ["server_checks_ok"])
    w = cfg()["weights"]
    cats = category_breakdown(answers)
    return {
        "claimed_level": claimed, "demonstrated_level": level, "level_notes": notes,
        "assessment_score": a_score, "evidence_score": ev["evidence_score"],
        "verified_evidence_score": ev["verified_evidence_score"], "consistency_score": cons,
        "confidence": conf, "badge": badge,
        "discrepancy": discrepancy(claimed, level, a_score),
        "formula": {"weights": w, "text": "confidence = %.0f%% assessment + %.0f%% evidence + %.0f%% consistency"
                                          % (100 * w["assessment"], 100 * w["evidence"], 100 * w["consistency"])},
        "breakdown": {"categories": cats, "difficulty": difficulty_breakdown(answers),
                      "questions_answered": len(answers),
                      "questions_correct": sum(1 for a in answers if is_correct(a["score"]))},
        "integrity": integ, "evidence_summary": evidence_summary(evidence_items),
    }


# ---------------------------------------------------------------------------
# Feeding the role-fit engine
# ---------------------------------------------------------------------------

def effective_value(demonstrated: str, conf: float) -> float:
    """Level value (0.4/0.7/1.0) scaled by certainty; Beginner never falls below 'partial'."""
    p = cfg()["profile"]
    base = C.LEVEL_VALUE[demonstrated]
    scaled = base * (p["certainty_floor"] + (1 - p["certainty_floor"]) * conf / 100.0)
    if demonstrated == "Beginner":
        scaled = max(scaled, p["beginner_floor"])
    return round(scaled, 4)


def unverified_value(declared_value: float) -> float:
    return round(declared_value * cfg()["profile"]["unverified_weight"], 4)
