"""
Grounded Copilot. The ANSWER is composed deterministically from the engine's result; an LLM (if configured) may only
reword it, and its text is discarded if it contains a number that is not in the deterministic answer.
"""
import re

import llm
from . import data as D, engine as E

FALLBACK = ("I don't have enough verified data in SkillTwin to answer that accurately. I can answer about: "
            "which role fits you, your biggest gaps, what to learn next, your roadmap, why a skill was prioritised, "
            "market demand for a role, and how you compare with a role.")


def _find_role(msg, default):
    low = msg.lower()
    for r, d in D.ROLES.items():
        if r.lower() in low or any(a in low for a in d["aliases"] if len(a) > 3):
            return r
    return default


def _find_skill(msg):
    low = msg.lower()
    best = None
    for s, d in D.SKILLS.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", low) or any(
                re.search(r"(?<![a-z0-9])" + re.escape(a.strip()) + r"(?![a-z0-9])", low) for a in d["aliases"] if len(a.strip()) > 2):
            if best is None or len(s) > len(best):
                best = s
    return best


def answer(message, role, profile, cfg=None):
    msg = (message or "").strip()
    low = msg.lower()
    role = _find_role(msg, role)
    fits = sorted(E.fit_all(profile).items(), key=lambda kv: (-kv[1], kv[0]))
    if not profile and not any(k in low for k in ("market", "demand")):
        return {"intent": "no_profile", "role": role, "facts": {},
                "text": "Your profile is empty, so every fit is 0%. Add or verify some skills in My Skills / Verification first."}

    def need_role():
        return {"intent": "need_role", "role": None, "facts": {},
                "text": "Pick a target role first (Career Explorer or Reverse Engineer) or name one in your question."}

    if re.search(r"which role|what role|suits|best fit|fit across|roles", low) and not _find_skill(msg) and "gap" not in low:
        top = fits[:3]
        return {"intent": "role_fit", "role": top[0][0], "facts": {"fits": dict(fits)},
                "text": "Your best-fitting roles right now: " + "; ".join("%s %s%%" % kv for kv in top) +
                        ". Fit = importance-weighted attainment of each role's required levels using your verified levels."}
    if re.search(r"market|demand|most demanded|in demand", low):
        r = role or fits[0][0]
        sk = sorted(D.ROLES[r]["reqs"].items(), key=lambda kv: (-D.SKILLS[kv[0]]["demand"], kv[0]))[:4]
        return {"intent": "market", "role": r, "facts": {s: D.SKILLS[s]["demand"] for s, _ in sk},
                "text": "Highest market-demand skills for %s (sample dataset, index out of 100): " % r +
                        ", ".join("%s %d" % (s, D.SKILLS[s]["demand"]) for s, _ in sk) + ". " + D.DATASET_NOTE}
    if not role:
        return need_role()
    res = E.analyze(role, profile, cfg)
    steps = res["steps"]
    sk = _find_skill(msg)
    if re.search(r"why|evidence|explain|reason", low) and (sk or steps):
        st = next((s for s in steps if s["skill"] == sk), steps[0] if steps else None)
        if not st:
            return {"intent": "why", "role": role, "facts": {}, "text": "No gaps remain for %s, so there is nothing to prioritise." % role}
        ev = st["evidence"]
        return {"intent": "why", "role": role, "skill": st["skill"], "facts": {"priority": st["priority"], **st["components"]},
                "text": "%s is #%d on your %s path with priority %s: %s. Dataset row: importance %s, posting frequency %s%%, demand index %s. "
                        "Use [View Evidence] on the Reverse Engineer tab for the full calculation." % (
                            st["skill"], st["order"], role, st["priority"], st["why"], ev.get("role_importance"),
                            ev.get("posting_frequency_pct"), ev["market_demand_index"])}
    if re.search(r"gap|missing|weak|lack", low):
        top = sorted(steps, key=lambda s: (-s["priority"], s["skill"]))[:3]
        return {"intent": "gaps", "role": role, "facts": {s["skill"]: s["priority"] for s in top},
                "text": "Biggest gaps for %s: " % role + "; ".join("%s (%s -> %s, priority %s)" % (
                    s["skill"], s["current_level"], s["required_level"], s["priority"]) for s in top) +
                        ". Fit is %s%%." % res["fit_pct"] if top else "You meet every requirement for %s in the dataset." % role}
    if re.search(r"next|first|start|learn", low):
        mv = E.best_next_moves(role, profile, cfg, top=1)
        if not steps:
            return {"intent": "next", "role": role, "facts": {}, "text": "No gaps remain for %s." % role}
        m = mv[0] if mv else None
        first = steps[0]
        t = "Start with %s (first on the dependency-ordered path, %sh)." % (first["skill"], first["effort_hours"])
        if m:
            t += " By fit gain per effort the best single move is %s: +%s%% fit for %sh." % (m["skill"], m["fit_gain_pct"], m["hours"])
        return {"intent": "next", "role": role, "facts": {"first": first["skill"], **({"best": m["skill"]} if m else {})}, "text": t}
    if re.search(r"roadmap|path|plan|phase|order", low):
        return {"intent": "roadmap", "role": role, "facts": {"hours": res["total_hours"]},
                "text": "%s roadmap: " % role + "; ".join("Phase %d: %s" % (p["phase"], ", ".join(p["skills"])) for p in res["phases"][:5]) +
                        ". About %sh total. %s" % (res["total_hours"], res["compression"]["statement"])}
    if re.search(r"compare|requirement|versus|vs", low):
        met = [s["skill"] for s in res["role_skills"] if s["status"] == "meets"]
        return {"intent": "compare", "role": role, "facts": {"fit": res["fit_pct"]},
                "text": "Against %s you are at %s%% fit. Requirements met: %s. Still needed: %d skills (~%sh)." % (
                    role, res["fit_pct"], ", ".join(met) or "none yet", len(steps), res["total_hours"])}
    return {"intent": "unknown", "role": role, "facts": {}, "text": FALLBACK}


def respond(message, role, profile, cfg=None):
    out = answer(message, role, profile, cfg)
    out["source"] = "deterministic"
    if out["intent"] in ("unknown", "no_profile", "need_role"):
        return out
    prompt = ("Reword the answer below in 2-4 friendly sentences. Use ONLY the information in it; do not add, change or "
              "estimate any number, skill, role or ordering.\nQUESTION: %s\nANSWER: %s" % (message[:300], out["text"]))
    text = llm.generate(prompt)
    if text:
        allowed = set(re.findall(r"\d+(?:\.\d+)?", out["text"]))
        if all(n in allowed for n in re.findall(r"\d+(?:\.\d+)?", text)):
            out["text_deterministic"] = out["text"]
            out["text"], out["source"] = text, "ai:" + llm.last_model()
    return out
