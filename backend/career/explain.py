"""
Explanation layer. The roadmap is computed by engine.py; this module only *words* it.
Deterministic text is always available. With GEMINI_API_KEY set an LLM may rephrase it, but it is
given only the finished facts, and its output is discarded if it contains any number not in those facts.
"""
import json
import os
import re
import urllib.request


def deterministic(result, best_moves=None):
    steps = result["steps"]
    if not steps:
        return {"source": "deterministic", "summary": "Your profile already meets every requirement for %s in the dataset." % result["role"], "bullets": []}
    top = sorted(steps, key=lambda s: (-s["priority"], s["skill"]))[:3]
    c = result["compression"]
    summary = ("Your fit for %s is %s%%. The shortest path from your current profile has %d skills (about %s hours, ~%s weeks at the configured pace). "
               "%s. The top priorities are %s." % (
                   result["role"], result["fit_pct"], len(steps), result["total_hours"], result["weeks"], c["statement"],
                   ", ".join("%s (priority %s)" % (s["skill"], s["priority"]) for s in top)))
    bullets = ["%s: %s." % (s["skill"], s["why"]) for s in top]
    if result["needs_verification"]:
        bullets.append("Skipped on your word only (verify to lock them in): " + ", ".join(result["needs_verification"]) + ".")
    if best_moves:
        m = best_moves[0]
        bullets.append("Best first move by fit gain per effort: %s (+%s%% fit for %s hours)." % (m["skill"], m["fit_gain_pct"], m["hours"]))
    return {"source": "deterministic", "summary": summary.replace("..", "."), "bullets": bullets}


def _numbers(obj, acc):
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        acc.add(str(int(obj)) if float(obj).is_integer() else str(obj))
        acc.add(str(round(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _numbers(v, acc)
    return acc


def ai(result, best_moves=None):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    base = deterministic(result, best_moves)
    facts = {"role": result["role"], "fit_pct": result["fit_pct"], "total_hours": result["total_hours"], "weeks": result["weeks"],
             "compression": result["compression"], "path": [{"skill": s["skill"], "priority": s["priority"], "why": s["why"]} for s in result["steps"][:8]]}
    prompt = ("You are a career coach inside SkillTwin. Explain this COMPUTED roadmap in 4-5 plain sentences using ONLY these facts. "
              "Do not add, change or estimate any number, skill or ordering. Facts: " + json.dumps(facts))
    import llm                      # the single place that talks to Gemini: certifi SSL, model fallback, thought parts skipped
    text = llm.generate(prompt, timeout=20)
    if not text:
        return None
    model = llm.last_model()
    allowed = _numbers(facts, set())
    for num in re.findall(r"\d+(?:\.\d+)?", text):
        if num not in allowed:
            return None
    return {**base, "source": "ai:" + model, "summary": text}
