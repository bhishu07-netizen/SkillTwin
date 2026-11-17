"""
Adaptive question selection (staircase with prerequisite probing) and the
early-stopping rule. Deterministic given (seed, position, history).

Policy
  * Start at medium difficulty.
  * Fully correct answer -> next target is one step harder (capped at hard).
  * Wrong answer         -> one step easier (floored at easy) AND, when possible, the next
                            question tests a PREREQUISITE concept of the one just missed.
  * Partial credit (between the cuts) -> hold the level.
  * Coverage: prefer the category asked least so far; avoid repeating a category back-to-back.
  * Prefer questions this candidate has not seen in recent attempts (retake = new variant).
  * Stop at max_questions, or - once min_questions are answered - when the running score is at
    least `stop_margin` points away from every level boundary and the level has been stable
    for the last two answers ("sufficient evidence to estimate the level").
"""
import random

from . import config as C
from . import scoring
from .bank import DIFFICULTIES, questions_for


def _cfg():
    return C.CONFIG["assessment"]


def next_target(answers) -> str:
    a = _cfg()
    idx = DIFFICULTIES.index(a["start_difficulty"])
    for ans in answers:
        if ans["score"] >= a["correct_cut"]:
            idx = min(idx + 1, len(DIFFICULTIES) - 1)
        elif ans["score"] < a["wrong_cut"]:
            idx = max(idx - 1, 0)
    return DIFFICULTIES[idx]


def should_stop(answers):
    """Returns (stop: bool, reason: str|None)."""
    a = _cfg()
    n = len(answers)
    if n >= a["max_questions"]:
        return True, "max_questions"
    if n < a["min_questions"]:
        return False, None
    score = scoring.weighted_score(answers)
    bounds = list(C.CONFIG["level_thresholds"].values())
    margin = min(abs(score - b) for b in bounds)
    if margin < a["stop_margin"]:
        return False, None
    level = scoring.level_from_score(score)
    if scoring.level_from_score(scoring.weighted_score(answers[:-2])) != level:
        return False, None
    if scoring.level_index(level) >= scoring.level_index("Advanced"):
        # an Advanced+ estimate is not 'sufficient' until the hard-question guard could be satisfied
        n_hard, _ = scoring.hard_stats(answers)
        if n_hard < C.CONFIG["level_guards"]["min_hard_for_advanced"]:
            return False, None
    return True, "sufficient_evidence"


def select_next(skill: str, answers, asked_ids, recent_seen_ids, seed: str):
    """
    answers: ordered list of answer dicts (difficulty, score, category, concept, qid)
    asked_ids: question ids already served in this attempt
    recent_seen_ids: ids seen in this candidate's recent attempts for the skill
    Returns (question_dict, reason_str).
    """
    bank = questions_for(skill)
    remaining = [q for q in bank if q["id"] not in asked_ids]
    if not remaining:
        raise RuntimeError("question bank exhausted")
    target = next_target(answers)
    rng = random.Random("%s:%d" % (seed, len(answers)))

    def tier(d):
        return sorted((q for q in remaining if q["difficulty"] == d), key=lambda q: q["id"])

    # difficulty with availability, nearest to target first
    order = sorted(DIFFICULTIES, key=lambda d: (abs(DIFFICULTIES.index(d) - DIFFICULTIES.index(target)),
                                                DIFFICULTIES.index(d)))
    pool, used_d = [], target
    for d in order:
        pool = tier(d)
        if pool:
            used_d = d
            break

    reason = "difficulty %s" % used_d
    last = answers[-1] if answers else None

    # prerequisite probing after a miss
    if last and last["score"] < _cfg()["wrong_cut"] and last["difficulty"] != "easy":
        last_q = next((q for q in bank if q["id"] == last["qid"]), None)
        prereqs = set(last_q["prereqs"]) if last_q else set()
        probe = [q for q in pool if q["concept"] in prereqs]
        if probe:
            pool = probe
            reason = "prerequisite probe after missing '%s'" % last["concept"]
        else:
            same_cat = [q for q in pool if q["category"] == last["category"]]
            if same_cat:
                pool = same_cat
                reason = "fundamentals check in %s after a miss" % C.CATEGORY_LABELS[last["category"]]

    # prefer unseen in recent attempts
    unseen = [q for q in pool if q["id"] not in recent_seen_ids]
    if unseen:
        pool = unseen

    # category coverage
    counts = {}
    for a in answers:
        counts[a["category"]] = counts.get(a["category"], 0) + 1
    if pool:
        least = min(counts.get(q["category"], 0) for q in pool)
        pool = [q for q in pool if counts.get(q["category"], 0) == least]
    if last and len(pool) > 1:
        varied = [q for q in pool if q["category"] != last["category"]]
        if varied:
            pool = varied

    return rng.choice(pool), reason
