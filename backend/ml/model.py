"""Pure-Python inference for the trained market models (reads ml/model.json written by ml/train.py)."""
import json
import math
from pathlib import Path

_PATH = Path(__file__).with_name("model.json")
_CACHE = {}
MIN_SUPPORT = 50          # a skill with fewer postings than this is not used for "biggest lift" advice


def _m():
    if "m" not in _CACHE:
        _CACHE["m"] = json.loads(_PATH.read_text(encoding="utf-8"))
    return _CACHE["m"]


def card():
    return _m()


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z)) if z >= 0 else math.exp(z) / (1.0 + math.exp(z))


def p_high_pay(present, exp_years):
    pay = _m()["pay"]
    z = pay["intercept"] + pay["exp_coef"] * ((float(exp_years) - pay["exp_mean"]) / pay["exp_scale"])
    z += sum(pay["skill_coef"].get(s, 0.0) for s in present)
    return _sigmoid(z)


def segment_probs(present):
    seg = _m()["segment"]
    zs = []
    for k in range(len(seg["classes"])):
        zs.append(seg["intercept"][k] + sum(seg["coef"][k].get(s, 0.0) for s in present))
    mx = max(zs)
    ex = [math.exp(z - mx) for z in zs]
    tot = sum(ex)
    return sorted(({"segment": c, "probability": e / tot} for c, e in zip(seg["classes"], ex)),
                  key=lambda x: -x["probability"])


def skill_lifts(present, exp_years, top=5):
    """Model-implied change in P(high pay) if one more skill were present. Only skills whose weight is clearly
    positive in the data (bootstrap 95% interval above zero), so the advice is never built on a noisy weight."""
    base = p_high_pay(present, exp_years)
    support = _m()["pay"]["support"]
    clear = set(_m()["pay"]["skills_with_clear_direction"])
    rows = []
    for s, n in support.items():
        if s in present or n < MIN_SUPPORT or s not in clear:
            continue
        p = p_high_pay(present | {s}, exp_years)
        rows.append({"skill": s, "delta_pts": round(100 * (p - base), 1), "new_probability": p, "postings": n})
    rows.sort(key=lambda r: -r["delta_pts"])
    return [r for r in rows if r["delta_pts"] > 0][:top]


def outlook(present, exp_years):
    present = set(present)
    pay = _m()["pay"]
    used = set(_m()["data"]["skills_used_by_model"])
    ignored = sorted(present - used)
    present = present & used
    p = p_high_pay(present, exp_years)
    return {
        "skills_used": sorted(present),
        "skills_without_enough_data": ignored,
        "experience_years": float(exp_years),
        "high_pay": {"probability": p, "base_rate": pay["base_rate"], "threshold": _m()["target"]["high_pay_definition"]},
        "segments": segment_probs(present)[:4] if present else [],
        "skill_lifts": skill_lifts(present, exp_years),
        "enough_skills": bool(present),
    }


def card_public():
    """The model card without the internal golden test cases."""
    m = dict(_m())
    m.pop("golden", None)
    return m


def summary():
    m = _m()
    cv = m["pay"]["cv"]
    return {"name": m["name"], "trained_at": m["trained_at"], "pay_rows": m["data"]["pay_rows"],
            "cv_auc": cv["logistic (served)"]["auc"], "cv_auc_experience_only": cv["exp_only"]["auc"],
            "segment_accuracy": m["segment"]["cv"]["logistic (served)"]["accuracy"],
            "segment_majority_accuracy": m["segment"]["cv"]["majority_class"]["accuracy"],
            "reliable_segments": [k for k, v in m["segment"]["cv"]["recall_by_segment"].items() if v >= 0.5],
            "skills_used_n": len(m["data"]["skills_used_by_model"]),
            "clear_positive_skills": [s for s in m["pay"]["skills_with_clear_direction"] if m["pay"]["skill_coef"][s] > 0]}
