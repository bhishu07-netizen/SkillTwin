"""
SkillTwin core dataset + deterministic role-fit engine.

Moved out of app.py so the verification package can reuse it without a circular
import. Logic is unchanged: sample dataset (5 roles, ~18 skills), weighted fit score,
gap priority and prerequisite-ordered learning path. Every number is computed live.
"""
import re


# ---------------------------------------------------------------------------
# Derived from career/data.py (single source of truth: skill graph + role requirement graphs).
# ---------------------------------------------------------------------------
from career import data as _D

TAXONOMY = {s: list(d["aliases"]) for s, d in _D.SKILLS.items()}
PREREQS = {s: list(d["prereqs"]) for s, d in _D.SKILLS.items() if d["prereqs"]}
PROJECTS = {s: d["project"] for s, d in _D.SKILLS.items()}
DW = {"High": 3, "Med": 2, "Low": 1}
REQ_VALUE = {"Beginner": 0.4, "Intermediate": 0.7, "Advanced": 1.0}


def _demand_band(d):
    return "High" if d >= 75 else "Med" if d >= 60 else "Low"


# legacy 3-tuple view: skill -> [importance 1-5, demand band, posting frequency %]
ROLES = {r: {"skills": {s: [max(1, round(q["importance"] / 20)), _demand_band(_D.SKILLS[s]["demand"]), q["freq"]]
                        for s, q in d["reqs"].items()},
             "required": {s: REQ_VALUE[q["required"]] for s, q in d["reqs"].items()}}
         for r, d in _D.ROLES.items()}


LEVEL_LABEL = {0: "None", 0.4: "Beginner", 0.7: "Intermediate", 1.0: "Advanced"}



# ---------------------------------------------------------------------------
# Scoring engine (mirrors extract/fitScore/renderGap/renderRoadmap in JS)
# ---------------------------------------------------------------------------

_NEG = re.compile(r"\b(never|no|not|without|none|zero|lack|lacking|haven't|havent|don't|dont|didn't|didnt|cannot|can't|cant|unfamiliar)\b")
_NEG_STOP = re.compile(r"\b(but|however|although|though|except|while|whereas)\b")
_LOW = re.compile(r"\b(basic|basics|beginner|novice|familiar|familiarity|exposure|introductory|intro|fundamentals|elementary)\b")
_HIGH = re.compile(r"\b(advanced|expert|expertise|proficient|proficiency|senior|extensive|mastery|strong)\b")
_AMBIGUOUS = {"dl", "cloud"}   # too ambiguous to infer a skill from (kept out of extraction)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s#+.\-/,;']", " ", text.lower())


def _alias_regex(alias):
    a = alias.strip()
    return re.compile(r"(?<![a-z0-9+#])" + re.escape(a) + r"(?![a-z0-9+#])")


_ALIAS_RX = {}


def extract_skills(text: str) -> dict:
    """
    Deterministic taxonomy + alias matcher. Returns {canonical_skill: claimed level value}.
    Whole-word matching (so "HTML" is not "ML"), negation-aware ("never used Python" is not a claim) and
    level cues next to the mention (basic/familiar -> Beginner, advanced/expert -> Advanced; default Intermediate).
    Whatever is extracted is only a CLAIM - it still has to be verified.
    """
    norm = normalize(text)
    found = {}
    # split into sentences/lines, keep clause-local context
    for sent in re.split(r"[.;\n]+(?!\d)", norm):
        if not sent.strip():
            continue
        for canon, aliases in TAXONOMY.items():
            if canon in found:
                continue
            for alias in aliases:
                if alias.strip() in _AMBIGUOUS:
                    continue
                rx = _ALIAS_RX.setdefault(alias, _alias_regex(alias))
                m = rx.search(sent)
                if not m:
                    continue
                before = sent[:m.start()]
                stops = list(_NEG_STOP.finditer(before))
                if stops:
                    before = before[stops[-1].end():]
                if _NEG.search(before):
                    break          # negated mention -> not a claim
                window = sent[max(0, m.start() - 18): m.end() + 12]
                if _HIGH.search(window):
                    found[canon] = 1.0
                elif _LOW.search(window):
                    found[canon] = 0.4
                else:
                    found[canon] = 0.7
                break
    return found


def classify(level: float) -> str:
    if level >= 0.85:
        return "Strong Match"
    if level >= 0.4:
        return "Partial Match"
    return "Skill Gap"


def fit_score(role_name: str, candidate_skills: dict):
    """Requirement-aware fit on the engine's level-unit scale (identical to career.engine.role_fit)."""
    if role_name not in ROLES:
        return None
    from career import engine as _E  # local import keeps core importable from the engine's own dependencies
    skills = ROLES[role_name]["skills"]
    req = ROLES[role_name]["required"]
    num = sum(imp * min(1.0, _E.value_to_units(candidate_skills.get(name, 0)) / _E.value_to_units(req[name]))
              for name, (imp, dem, pct) in skills.items())
    den = sum(imp for imp, dem, pct in skills.values())
    return round(num / den, 4) if den else 0.0


def gap_priority(imp, dem, level):
    return imp * DW[dem] * (1 - level)


def role_gaps(role_name: str, candidate_skills: dict):
    skills = ROLES[role_name]["skills"]
    gaps = []
    for name, (imp, dem, pct) in skills.items():
        level = candidate_skills.get(name, 0)
        if level < 0.85:
            gaps.append({
                "skill": name, "importance": imp, "demand": dem,
                "sample_frequency_pct": pct, "candidate_level": level,
                "status": classify(level),
                "priority_score": round(gap_priority(imp, dem, level), 3),
            })
    gaps.sort(key=lambda x: x["priority_score"], reverse=True)
    return gaps


def shortest_path(role_name: str, candidate_skills: dict):
    """Priority-ordered path respecting inferred prerequisites within the gap set."""
    gaps = role_gaps(role_name, candidate_skills)
    remaining = {g["skill"] for g in gaps}
    by_skill = {g["skill"]: g for g in gaps}
    placed = []
    while remaining:
        eligible = [s for s in remaining if all(p not in remaining for p in PREREQS.get(s, []))]
        if not eligible:
            eligible = list(remaining)  # break any cycle defensively
        nxt = max(eligible, key=lambda s: by_skill[s]["priority_score"])
        placed.append(by_skill[nxt])
        remaining.discard(nxt)
    return placed
