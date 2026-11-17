"""
Configuration for the Skill Verification & Confidence Engine.

Every number that influences a score, a level or a badge lives here so it can
be tuned without touching engine code. Override any value by pointing the
SKILLTWIN_VERIFY_CONFIG environment variable at a JSON file containing a
(partial) copy of DEFAULT_CONFIG - it is deep-merged over the defaults.
"""
import copy
import json
import os
from pathlib import Path

LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]
CLAIMABLE_LEVELS = ["Beginner", "Intermediate", "Advanced"]

# Numeric scale used by the existing role-fit engine (0.4 / 0.7 / 1.0).
# Advanced and Expert both map to 1.0 because the legacy engine tops out there.
LEVEL_VALUE = {"Beginner": 0.4, "Intermediate": 0.7, "Advanced": 1.0, "Expert": 1.0}
LEGACY_TO_LEVEL = {0.4: "Beginner", 0.7: "Intermediate", 1.0: "Advanced"}

CATEGORY_LABELS = {
    "fundamentals": "Fundamentals",
    "code_reading": "Code Reading",
    "debugging": "Debugging",
    "problem_solving": "Problem Solving",
    "implementation": "Implementation",
}

DEFAULT_CONFIG = {
    # Final confidence = weighted sum of three 0-100 signals (auto-normalised).
    "weights": {"assessment": 0.70, "evidence": 0.20, "consistency": 0.10},

    # Lower bound (inclusive) of each demonstrated level, on the 0-100 assessment score.
    "level_thresholds": {"Intermediate": 40, "Advanced": 70, "Expert": 85},

    # Score a candidate "typically" earns at each claimed level (band midpoints).
    "claim_midpoints": {"Beginner": 20, "Intermediate": 55, "Advanced": 77, "Expert": 92},

    # Claim-consistency = 100 - penalty. Over-claiming (performance below the claim)
    # is penalised harder than under-claiming; under-claiming is capped because a
    # modest candidate who performs well should not lose confidence in a real skill.
    "consistency": {
        "over_claim_factor": 2.0,
        "under_claim_factor": 0.5,
        "under_claim_max_penalty": 20,
    },

    "difficulty_weights": {"easy": 1, "medium": 2, "hard": 3},

    "assessment": {
        "min_questions": 8,
        "max_questions": 12,
        "time_limit_s": 2100,          # whole assessment, enforced server-side
        "start_difficulty": "medium",
        "stop_margin": 12,             # early stop when score is this far from any level boundary
        "sample_run_limit": 6,         # "Run sample tests" calls per coding question
        "correct_cut": 0.99,           # score >= cut counts as "correct" for the staircase
        "wrong_cut": 0.5,              # score <  cut counts as "wrong"; in between = hold
        "recent_attempt_window": 3,    # prefer questions not seen in the last N attempts
    },

    # A level above Intermediate must be backed by enough hard-question evidence.
    "level_guards": {
        "min_hard_for_advanced": 2,
        "min_hard_for_expert": 3,
        "min_hard_accuracy_for_expert": 0.70,
    },

    "evidence": {
        "type_weights": {
            "github": 1.0, "work_sample": 0.8, "project": 0.6,
            "certification": 0.6, "coursework": 0.4,
        },
        # Evidence that could not be machine-checked still counts, but at this fraction.
        "provided_factor": 0.25,
        # An item must reach this strength to count towards the VERIFIED evidence score.
        "verified_min_strength": 0.30,
        "github": {
            "relevance": 0.45, "substance": 0.35, "originality": 0.10, "recency": 0.10,
            "full_relevance_share": 0.40,      # share of repo bytes in the skill's language for full marks
            "full_substance_bytes": 30000,     # bytes of skill-language code for full marks
            "fork_factor": 0.4,
            "stale_after_days": 1095,
            "stale_factor": 0.7,
            "owner_mismatch_factor": 0.6,
        },
        "work_sample": {"feature_weight": 0.5, "size_weight": 0.5, "full_loc": 80, "feature_target": 7},
        "http_timeout_s": 6,
        "max_items_per_skill": 8,
    },

    "badges": {
        "evidence_backed_min_verified_evidence": 40,   # verified-evidence score (0-100)
        "verified_min_confidence": 85,
        "rapid_answer_seconds": {"mcq": 3, "output": 4, "code": 20},
        "verified_max_rapid_answers": 2,
    },

    "discrepancy": {"near_margin": 5},

    # How skills feed the legacy role-fit engine.
    "profile": {
        "unverified_weight": 0.8,   # self-declared, unverified claims count at this fraction
        "certainty_floor": 0.6,     # verified level is scaled by floor + (1-floor)*confidence
        "beginner_floor": 0.4,      # a demonstrated Beginner never drops below "partial"
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    path = os.environ.get("SKILLTWIN_VERIFY_CONFIG")
    if path and Path(path).is_file():
        _deep_merge(cfg, json.loads(Path(path).read_text()))
    w = cfg["weights"]
    total = sum(w.values()) or 1.0
    cfg["weights"] = {k: v / total for k, v in w.items()}
    return cfg


CONFIG = load_config()


def reload_config() -> dict:
    """Re-read config (used by tests that override weights/thresholds)."""
    global CONFIG
    CONFIG = load_config()
    return CONFIG
