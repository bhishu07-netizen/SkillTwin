"""
Career Path Optimization Engine  (deterministic - no LLM anywhere in this file).

Pipeline:  verified profile -> role requirement graph -> gap -> priority -> dependency-aware
           topological ordering -> phases / effort -> compression vs generic roadmap -> what-if.

Units: every level is mapped onto a continuous "level unit" scale  0 (none) .. 3 (Advanced)
via the piecewise-linear map  value 0.4->1, 0.7->2, 1.0->3  so gaps have a size, not just a label.

priority(skill) = 100 * weighted-geometric-mean( importance, market demand, gap, dependency criticality )
  importance  = role importance / 100              (dataset)
  demand      = market-demand index / 100          (dataset)
  gap         = (required_units - current_units) / required_units
  criticality = importance share of the *other* needed skills that transitively depend on it
Weights, hours/week and trust policy are configurable (CONFIG / per-request overrides).
"""
import copy
import math

from . import data as D

CONFIG = {
    "weights": {"importance": 1.0, "demand": 1.0, "gap": 1.0, "criticality": 1.0},
    "hours_per_week": 10,
    "mastered_tolerance": 0.05,           # gap (units) at or below this counts as mastered
    "implied_importance_factor": 0.8,     # prerequisite-only skills inherit this x max dependent importance
    "implied_required_units": 1.0,        # prerequisites outside the role list are needed at Beginner
    "unverified_credit": 0.8,             # self-declared claims count for this share of declared level
    "confidence_full": 70,                # verified credit is scaled down below this confidence
    "confidence_min_factor": 0.6,
    "floor": 0.02,                        # keeps the geometric mean defined when a factor is ~0
}

LEVEL_VALUE = {"None": 0.0, "Beginner": 0.4, "Intermediate": 0.7, "Advanced": 1.0, "Expert": 1.0}
_PTS = [(0.0, 0.0), (0.4, 1.0), (0.7, 2.0), (1.0, 3.0)]
REQ_UNITS = {"Beginner": 1.0, "Intermediate": 2.0, "Advanced": 3.0}
UNIT_LABEL = [(2.75, "Advanced"), (1.75, "Intermediate"), (0.75, "Beginner")]


def cfg_with(overrides=None):
    c = copy.deepcopy(CONFIG)
    for k, v in (overrides or {}).items():
        if k == "weights" and isinstance(v, dict):
            for wk, wv in v.items():
                if wk in c["weights"] and isinstance(wv, (int, float)) and not isinstance(wv, bool) and 0 <= wv <= 100:
                    c["weights"][wk] = float(wv)
        elif k == "hours_per_week" and isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v <= 80:
            c[k] = v
    if not any(c["weights"].values()):          # all-zero weights would make the formula undefined
        c["weights"] = dict(CONFIG["weights"])
    return c


def value_to_units(v):
    v = max(0.0, min(1.0, float(v)))
    for (x0, y0), (x1, y1) in zip(_PTS, _PTS[1:]):
        if v <= x1:
            return y0 + (y1 - y0) * (v - x0) / (x1 - x0)
    return 3.0


def units_label(u):
    for t, name in UNIT_LABEL:
        if u >= t:
            return name
    return "None" if u < 0.25 else "Beginner (emerging)"


# ---------------------------------------------------------------- profile -------------

def build_profile(verification_profile=None, declared=None, trust_declared=False, cfg=None):
    """
    verification_profile: output of verification.engine.effective_profile (verified / self-declared rows)
    declared: optional {skill: level name} for inline profiles (always self-declared)
    Returns {skill: {units, basis, confidence, badge, level_label, note}}.
    """
    cfg = cfg or CONFIG
    out = {}
    for skill, e in (verification_profile or {}).items():
        if skill not in D.SKILLS:
            continue
        if e["basis"] == "verified":
            conf = e["confidence"] or 0
            full = cfg["confidence_full"]
            f = 1.0 if conf >= full else cfg["confidence_min_factor"] + (1 - cfg["confidence_min_factor"]) * conf / full
            val = LEVEL_VALUE.get(e["demonstrated_level"], 0) * f
            out[skill] = {"basis": "verified", "confidence": conf, "badge": e.get("badge"),
                          "level_label": e["demonstrated_level"], "units": value_to_units(val),
                          "declared_label": e["declared_level"],
                          "note": "verified %s at %s%% confidence" % (e["demonstrated_level"], conf)}
        else:
            dv = e["declared_value"]
            val = dv if trust_declared else dv * cfg["unverified_credit"]
            out[skill] = {"basis": "self-declared", "confidence": None, "badge": "SELF-DECLARED",
                          "level_label": e["declared_level"], "declared_label": e["declared_level"],
                          "units": value_to_units(val),
                          "note": "self-declared %s - %s" % (
                              e["declared_level"],
                              "taken at face value (demo mode)" if trust_declared else
                              "credited at %d%% until verified" % round(cfg["unverified_credit"] * 100))}
    for skill, lvl in (declared or {}).items():
        if skill not in D.SKILLS or skill in out or lvl in (None, "None"):
            continue
        dv = LEVEL_VALUE[lvl]
        val = dv if trust_declared else dv * cfg["unverified_credit"]
        out[skill] = {"basis": "self-declared", "confidence": None, "badge": "SELF-DECLARED", "level_label": lvl,
                      "declared_label": lvl, "units": value_to_units(val),
                      "note": "self-declared %s - %s" % (lvl, "taken at face value (demo mode)" if trust_declared else
                                                          "credited at %d%% until verified" % round(cfg["unverified_credit"] * 100))}
    return out


# ---------------------------------------------------------------- graph helpers -------

def _ancestors(skill):
    seen, stack = set(), list(D.SKILLS[skill]["prereqs"])
    while stack:
        p = stack.pop()
        if p not in seen:
            seen.add(p)
            stack.extend(D.SKILLS[p]["prereqs"])
    return seen


def _closure(skills):
    out = set(skills)
    for s in skills:
        out |= _ancestors(s)
    return out


def _cur(profile, s):
    return profile.get(s, {}).get("units", 0.0)


# ---------------------------------------------------------------- core analysis -------

def role_fit(role, profile):
    reqs = D.ROLES[role]["reqs"]
    num = den = 0.0
    for s, q in reqs.items():
        ru = REQ_UNITS[q["required"]]
        num += q["importance"] * min(1.0, _cur(profile, s) / ru)
        den += q["importance"]
    return round(100 * num / den, 1) if den else 0.0


def analyze(role, profile, cfg=None, assume_learned=None):
    """Compute the needed-skill graph, priorities and ordered path. Pure function of its inputs."""
    cfg = cfg or CONFIG
    reqs = D.ROLES[role]["reqs"]
    profile = {k: dict(v) for k, v in profile.items()}
    tol = cfg["mastered_tolerance"]

    # requirement per node: role skills at their level; prerequisites of anything needed at implied level
    required = {s: REQ_UNITS[q["required"]] for s, q in reqs.items()}
    importance = {s: float(q["importance"]) for s, q in reqs.items()}
    implied = set()
    for s in list(reqs):
        for a in _ancestors(s):
            if a not in required:
                required[a] = cfg["implied_required_units"]
                implied.add(a)
    for a in implied:
        deps = [importance[d] for d in importance if a in _ancestors(d)]
        importance[a] = cfg["implied_importance_factor"] * max(deps) if deps else 0.0

    cur = {s: _cur(profile, s) for s in required}
    for s in (assume_learned or []):
        if s in required:
            cur[s] = max(cur[s], required[s])
    gap_units = {s: max(0.0, required[s] - cur[s]) for s in required}

    # a skill is "needed" if it has a gap, OR it is a prerequisite of a needed skill and is itself unmet
    needed = {s for s, g in gap_units.items() if g > tol}
    # a mastered prerequisite is skipped; an unmet prerequisite of a needed skill is already in `needed`
    # because every ancestor of a role skill is in `required` (and so was tested for a gap above).

    # criticality: importance share of other needed skills that transitively depend on s
    tot_imp = sum(importance[s] for s in needed) or 1.0
    crit = {}
    for s in needed:
        down = [t for t in needed if t != s and s in _ancestors(t)]
        crit[s] = sum(importance[t] for t in down) / tot_imp

    w = cfg["weights"]
    wsum = sum(w.values()) or 1.0
    fl = cfg["floor"]
    comps, prio = {}, {}
    for s in needed:
        c = {"importance": max(fl, importance[s] / 100.0),
             "demand": max(fl, D.SKILLS[s]["demand"] / 100.0),
             "gap": max(fl, gap_units[s] / required[s]),
             "criticality": max(fl, crit[s])}
        comps[s] = c
        prio[s] = round(100 * math.exp(sum(w[k] * math.log(c[k]) for k in w) / wsum), 1)

    # Kahn topological order, ties broken by priority (desc) then name
    indeg = {s: sum(1 for p in D.SKILLS[s]["prereqs"] if p in needed) for s in needed}
    ready = sorted([s for s in needed if indeg[s] == 0], key=lambda s: (-prio[s], s))
    order, depth = [], {}
    while ready:
        s = ready.pop(0)
        order.append(s)
        depth[s] = 1 + max([depth[p] for p in D.SKILLS[s]["prereqs"] if p in needed] or [0])
        for t in needed:
            if s in D.SKILLS[t]["prereqs"]:
                indeg[t] -= 1
                if indeg[t] == 0:
                    ready.append(t)
        ready.sort(key=lambda x: (-prio[x], x))
    assert len(order) == len(needed), "dependency cycle in needed set"  # impossible: dataset is validated DAG

    steps = []
    for i, s in enumerate(order, 1):
        sk, rq = D.SKILLS[s], reqs.get(s)
        hrs = round(sk["hours"] * gap_units[s], 1)
        p = profile.get(s)
        unmet_pre = [x for x in sk["prereqs"] if x in needed]
        steps.append({
            "order": i, "phase": depth[s], "skill": s, "implied_prerequisite": s in implied,
            "category": sk["category"],
            "current_level": units_label(cur[s]), "current_units": round(cur[s], 2),
            "required_level": rq["required"] if rq else "Beginner", "required_units": required[s],
            "gap_units": round(gap_units[s], 2), "effort_hours": hrs,
            "priority": prio[s], "components": {k: round(v, 3) for k, v in comps[s].items()},
            "basis": p["basis"] if p else "none", "basis_note": p["note"] if p else "no evidence of this skill",
            "badge": p["badge"] if p else None,
            "blocked_by": unmet_pre, "unlocks": sorted(t for t in needed if s in D.SKILLS[t]["prereqs"]),
            "project": sk["project"],
            "why": _why(s, rq, sk, importance[s], gap_units[s], crit[s], implied),
            "evidence": evidence_for(role, s),
        })

    # already-satisfied skills (skipped) with their trust basis
    skipped = []
    for s in sorted(required, key=lambda x: (-importance[x], x)):
        if s in needed:
            continue
        p = profile.get(s)
        skipped.append({"skill": s, "required_level": reqs[s]["required"] if s in reqs else "Beginner",
                        "current_level": units_label(cur[s]),
                        "basis": p["basis"] if p else "none", "badge": p["badge"] if p else None,
                        "needs_verification": bool(p and p["basis"] != "verified"),
                        "hours_saved": round(D.SKILLS[s]["hours"] * required[s], 1),
                        "note": p["note"] if p else "satisfied as a prerequisite credit"})

    role_skills = []
    for sname, q in sorted(reqs.items(), key=lambda kv: (-kv[1]["importance"], kv[0])):
        att = min(1.0, cur[sname] / required[sname])
        p = profile.get(sname)
        role_skills.append({
            "skill": sname, "importance": q["importance"], "required_level": q["required"], "freq": q["freq"],
            "demand": D.SKILLS[sname]["demand"], "current_level": units_label(cur[sname]),
            "attainment_pct": round(100 * att), "status": "meets" if gap_units[sname] <= tol else ("partial" if cur[sname] >= 0.25 else "gap"),
            "gap_units": round(gap_units[sname], 2), "priority": prio.get(sname), "basis": p["basis"] if p else "none",
            "badge": p["badge"] if p else None, "on_path": sname in needed})
    total_h = round(sum(x["effort_hours"] for x in steps), 1)
    phases = {}
    for st in steps:
        phases.setdefault(st["phase"], []).append(st["skill"])
    gen = generic_roadmap(role)
    return {
        "role": role, "fit_pct": role_fit(role, {s: {"units": v} for s, v in cur.items()}),
        "steps": steps, "skipped": skipped, "role_skills": role_skills,
        "phases": [{"phase": k, "skills": v,
                    "hours": round(sum(x["effort_hours"] for x in steps if x["phase"] == k), 1)}
                   for k, v in sorted(phases.items())],
        "total_hours": total_h, "weeks": round(total_h / cfg["hours_per_week"], 1) if cfg["hours_per_week"] else None,
        "critical_gaps": [x["skill"] for x in sorted(steps, key=lambda x: (-x["priority"], x["skill"]))[:3]],
        "compression": compression(steps, skipped, gen, total_h),
        "needs_verification": [s["skill"] for s in skipped if s["needs_verification"]],
    }


def _why(s, rq, sk, imp, gap, crit, implied):
    bits = []
    if s in implied:
        bits.append("prerequisite for skills this role needs")
    else:
        bits.append("required at %s (importance %d/100, seen in %d%% of sampled postings)" %
                    (rq["required"], rq["importance"], rq["freq"]))
    bits.append("market-demand index %d/100" % sk["demand"])
    bits.append("gap of %.1f level unit(s)" % gap)
    if crit > 0:
        bits.append("unlocks %d%% of the remaining weighted path" % round(crit * 100))
    return "; ".join(bits)


def evidence_for(role, s):
    """Everything the UI's [View Evidence] needs - each value is a row of the dataset."""
    sk, rq = D.SKILLS[s], D.ROLES[role]["reqs"].get(s)
    ev = {"skill": s, "role": role, "category": sk["category"], "market_demand_index": sk["demand"],
          "hours_per_level": sk["hours"], "prerequisites": sk["prereqs"],
          "dependents_in_role": sorted(t for t in D.ROLES[role]["reqs"] if s in D.SKILLS[t]["prereqs"]),
          "dataset": D.DATASET_NOTE}
    if rq:
        ev.update({"role_importance": rq["importance"], "required_level": rq["required"],
                   "posting_frequency_pct": rq["freq"]})
    else:
        ev["role_importance"] = None
        ev["note"] = "Not listed for this role; included because it is a prerequisite in the skill graph."
    return ev


# ---------------------------------------------------------------- compression ---------

def generic_roadmap(role):
    """What a one-size-fits-all roadmap contains: every role skill + full prerequisite closure, from zero."""
    reqs = D.ROLES[role]["reqs"]
    allsk = _closure(reqs)
    hours = 0.0
    for s in allsk:
        units = REQ_UNITS[reqs[s]["required"]] if s in reqs else CONFIG["implied_required_units"]
        hours += D.SKILLS[s]["hours"] * units
    return {"skills": sorted(allsk), "count": len(allsk), "hours": round(hours, 1)}


def compression(steps, skipped, gen, total_h):
    n_skip = gen["count"] - len(steps)
    saved = round(gen["hours"] - total_h, 1)
    pct = round(100 * saved / gen["hours"], 1) if gen["hours"] else 0.0
    verified_skips = [s["skill"] for s in skipped if s["basis"] == "verified"]
    unv = [s["skill"] for s in skipped if s["needs_verification"]]
    parts = ["%d of %d skills in the generic roadmap are skipped because your profile already meets the requirement"
             % (n_skip, gen["count"])]
    return {"generic_skill_count": gen["count"], "personalized_skill_count": len(steps), "skills_skipped": n_skip,
            "generic_hours": gen["hours"], "personalized_hours": total_h, "hours_saved": saved, "compression_pct": pct,
            "skipped_verified": verified_skips, "skipped_unverified": unv,
            "statement": "%s (%s)." % (parts[0], "%d verified, %d still self-declared" % (len(verified_skips), len(unv)))}


# ---------------------------------------------------------------- what-if -------------

def simulate(role, profile, learn, cfg=None):
    """PROJECTION: re-run the engine as if `learn` skills (and their unmet prerequisites) were learned."""
    cfg = cfg or CONFIG
    base = analyze(role, profile, cfg)
    base_needed = {s["skill"]: s for s in base["steps"]}
    learn = [s for s in dict.fromkeys(learn) if s in D.SKILLS]
    invalid = [s for s in learn if s not in base_needed]
    effective = [s for s in learn if s in base_needed]
    to_learn = {s for s in effective} | {a for s in effective for a in _ancestors(s) if a in base_needed}
    after = analyze(role, profile, cfg, assume_learned=sorted(to_learn))
    after_needed = {s["skill"]: s for s in after["steps"]}

    def ready(a, s):  # all prerequisites of s satisfied in analysis `a`
        return all(p not in a for p in D.SKILLS[s]["prereqs"])

    unlocked = sorted(s for s in after_needed if s not in to_learn and ready(after_needed, s)
                      and not ready(base_needed, s))
    def unmet(a, s):
        return [p for p in D.SKILLS[s]["prereqs"] if p in a]

    closer = [{"skill": s, "unmet_before": len(unmet(base_needed, s)), "unmet_after": len(unmet(after_needed, s)),
               "still_needs": unmet(after_needed, s)}
              for s in sorted(after_needed) if s not in to_learn and s not in unlocked
              and len(unmet(after_needed, s)) < len(unmet(base_needed, s))]
    return {
        "label": "PROJECTION - computed by re-running the engine on a hypothetical profile, not a prediction of outcomes",
        "learn_requested": learn, "also_required_first": sorted(to_learn - set(learn)),
        "not_applicable": invalid,
        "fit_before_pct": base["fit_pct"], "fit_after_pct": after["fit_pct"],
        "fit_delta_pct": round(after["fit_pct"] - base["fit_pct"], 1),
        "effort_hours_spent": round(sum(base_needed[s]["effort_hours"] for s in to_learn), 1),
        "hours_remaining_after": after["total_hours"], "hours_remaining_before": base["total_hours"],
        "newly_unlocked": [{"skill": s, "was_blocked_by": [p for p in D.SKILLS[s]["prereqs"] if p in base_needed]}
                           for s in unlocked],
        "moved_closer": closer,
        "remaining_critical_gaps": [{"skill": s["skill"], "priority": s["priority"]} for s in
                                    sorted(after["steps"], key=lambda x: (-x["priority"], x["skill"]))[:3]],
        "next_steps_after": [s["skill"] for s in after["steps"][:5]],
    }


def best_next_moves(role, profile, cfg=None, top=3):
    """Rank single-skill what-ifs by fit gain per effort hour - 'what should I learn first?' computed, not guessed."""
    base = analyze(role, profile, cfg)
    out = []
    for st in base["steps"]:
        if st["blocked_by"]:
            continue
        sim = simulate(role, profile, [st["skill"]], cfg)
        hrs = sim["effort_hours_spent"] or 1
        out.append({"skill": st["skill"], "fit_gain_pct": sim["fit_delta_pct"],
                    "hours": sim["effort_hours_spent"], "gain_per_10h": round(sim["fit_delta_pct"] / hrs * 10, 2),
                    "unlocks": [u["skill"] for u in sim["newly_unlocked"]]})
    out.sort(key=lambda x: (-x["gain_per_10h"], x["skill"]))
    return out[:top]


# ---------------------------------------------------------------- search --------------

def search_roles(q):
    q = (q or "").strip().lower()
    res = []
    for r, d in D.ROLES.items():
        names = [r.lower()] + [a.lower() for a in d["aliases"]]
        if not q:
            score = 1
        elif q == r.lower() or q in names:
            score = 100
        elif any(q in n or n in q for n in names):
            score = 60
        else:
            toks = set(q.split())
            score = 10 * len(toks & set(" ".join(names).split()))
        if score:
            res.append({"role": r, "summary": d["summary"], "skills": len(d["reqs"]), "score": score})
    res.sort(key=lambda x: (-x["score"], x["role"]))
    return res


def roles_overview():
    return [{"role": r, "summary": d["summary"], "aliases": d["aliases"], "skills": len(d["reqs"])}
            for r, d in D.ROLES.items()]


def profile_from_values(values, basis="as-supplied"):
    """{skill: 0..1 level value} -> engine profile (used by legacy inline-skills requests)."""
    out = {}
    for s, v in (values or {}).items():
        if s in D.SKILLS and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            v = max(0.0, min(1.0, float(v)))
            out[s] = {"basis": basis, "confidence": None, "badge": None, "level_label": units_label(value_to_units(v)),
                      "declared_label": None, "units": value_to_units(v), "note": "level supplied by the caller"}
    return out


def fit_all(profile):
    return {r: role_fit(r, profile) for r in D.ROLES}
