"""
"Analytics first, AI to explain."

The narrative is ALWAYS available deterministically (templated from the computed result and the
authored per-question explanations). If GEMINI_API_KEY is set, an LLM may rephrase it into friendlier
feedback - but it receives only the finished numbers, is told not to change them, and its output is
discarded if it contradicts them. The LLM never produces or alters a score, level or confidence.
"""
import json
import os
import re
import urllib.request


def deterministic(result: dict, review: list) -> dict:
    d = result["discrepancy"]
    lines = [
        "%s: you declared %s and demonstrated %s with %d%% confidence (%s)." % (
            result["skill"].title(), result["claimed_level"], result["demonstrated_level"],
            round(result["confidence"]), result["badge"]),
        "%s - %s" % (d["label"], d["message"]),
        "Confidence = %s. Assessment %.0f, evidence %.0f, claim consistency %.0f." % (
            result["breakdown"]["formula"]["text"], result["assessment_score"], result["evidence_score"],
            result["consistency_score"]),
    ]
    lines += result["breakdown"].get("level_notes", [])
    w = result["weaknesses"]
    if w["weak_categories"]:
        lines.append("Weakest areas: " + ", ".join("%s (%d%%)" % (c["label"], round(c["score"])) for c in w["weak_categories"]) + ".")
    mistakes = [{"question": r["prompt"][:140], "your_answer": (r["candidate_answer"] or "")[:160],
                 "why": r["explanation"], "concept": r["concept"].replace("_", " ")}
                for r in review if not r["correct"]]
    nxt = ["Study: " + m["study"] for m in w["missed_concepts"][:5]]
    if result["evidence_score"] < 40:
        nxt.append("Add verifiable evidence (a public GitHub repo, or pasted code) to raise your evidence score.")
    return {"source": "deterministic", "summary": " ".join(lines), "mistakes": mistakes[:8], "next_steps": nxt}


def _facts(result, base):
    return {"skill": result["skill"], "claimed": result["claimed_level"], "demonstrated": result["demonstrated_level"],
            "confidence": round(result["confidence"]), "assessment": round(result["assessment_score"]),
            "evidence": round(result["evidence_score"]), "badge": result["badge"],
            "claim_check": result["discrepancy"]["label"], "weak": [c["label"] for c in result["weaknesses"]["weak_categories"]],
            "missed": [m["study"] for m in result["weaknesses"]["missed_concepts"][:6]]}


def ai(result: dict, review: list):
    """Returns an enriched explanation or None (no key / any failure / contradicts numbers)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    base = deterministic(result, review)
    facts = _facts(result, base)
    prompt = ("You are a supportive career coach inside SkillTwin. Using ONLY these computed facts, write 3-4 short, "
              "encouraging, non-judgemental sentences explaining the result and what to learn next. Never say the person "
              "lied or cheated. Do not change, recompute or invent any number, level or badge. Facts: " + json.dumps(facts))
    import llm                      # the single place that talks to Gemini: certifi SSL, model fallback, thought parts skipped
    text = llm.generate(prompt, timeout=20)
    if not text:
        return None
    model = llm.last_model()
    allowed = {str(facts["confidence"]), str(facts["assessment"]), str(facts["evidence"])}
    for num in re.findall(r"\d+", text):
        if num not in allowed and int(num) > 10:
            return None  # contradicts / invents numbers -> discard
    if re.search(r"\b(lied|lying|cheat|fraud)", text, re.I):
        return None
    return {**base, "source": "ai:" + model, "summary": text}
