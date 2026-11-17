"""
Readiness history: the REASSESS half of the loop.
A snapshot (profile + fit for every role) is stored whenever a candidate's effective profile actually changes
(new verification result, evidence change, claim edit). What-if runs on a real profile are logged as projections and
later resolved against the first snapshot in which the hypothesised skills are really at the required level, so the
app can show "projected X%, actual Y%" - the only honest test of a projection.
"""
import hashlib
import json

from verification import db as VDB, engine as VENG
from . import data as D, engine as E

TOL = 0.05


def _profile(db, cid):
    return E.build_profile(verification_profile=VENG.effective_profile(db, cid), trust_declared=False)


def _compact(profile):
    return {s: {"units": round(p["units"], 3), "level": p["level_label"], "basis": p["basis"],
                "confidence": p["confidence"]} for s, p in sorted(profile.items())}


def snapshot(db, cid, trigger):
    """Insert a snapshot iff the effective profile differs from the latest one. Returns snapshot id or None."""
    profile = _profile(db, cid)
    compact = _compact(profile)
    sig = hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest()[:16]
    last = db.execute("SELECT signature FROM readiness_snapshots WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if last and last["signature"] == sig:
        return None
    cur = db.execute("INSERT INTO readiness_snapshots(candidate_id, created_at, trigger, signature, profile_json, fits_json) VALUES (?,?,?,?,?,?)",
                     (cid, VDB.now(), trigger, sig, json.dumps(compact), json.dumps(E.fit_all(profile))))
    return cur.lastrowid


def record_projection(db, cid, role, sim):
    to_learn = sorted(set(sim["learn_requested"]) | set(sim["also_required_first"]))
    if not to_learn:
        return None
    return db.execute("INSERT INTO projections(candidate_id, role, learn_json, to_learn_json, fit_before, fit_projected, created_at) VALUES (?,?,?,?,?,?,?)",
                      (cid, role, json.dumps(sim["learn_requested"]), json.dumps(to_learn), sim["fit_before_pct"],
                       sim["fit_after_pct"], VDB.now())).lastrowid


def _required_units(role, skill):
    q = D.ROLES[role]["reqs"].get(skill)
    return E.REQ_UNITS[q["required"]] if q else E.CONFIG["implied_required_units"]


def _diff(prev, cur):
    out = []
    for s in sorted(set(prev) | set(cur)):
        a, b = prev.get(s), cur.get(s)
        if a is None:
            out.append({"skill": s, "change": "added", "to": b["level"], "basis": b["basis"]})
        elif b is None:
            out.append({"skill": s, "change": "removed", "from": a["level"]})
        elif abs(a["units"] - b["units"]) > 1e-6 or a["basis"] != b["basis"]:
            out.append({"skill": s, "change": "changed", "from": a["level"], "to": b["level"],
                        "from_basis": a["basis"], "basis": b["basis"]})
    return out


def _resolve_projections(db, cid, role):
    snaps = db.execute("SELECT * FROM readiness_snapshots WHERE candidate_id=? ORDER BY id", (cid,)).fetchall()
    for p in db.execute("SELECT * FROM projections WHERE candidate_id=? AND role=? AND resolved_at IS NULL", (cid, role)).fetchall():
        need = json.loads(p["to_learn_json"])
        for sn in snaps:
            if sn["created_at"] <= p["created_at"]:
                continue
            prof = json.loads(sn["profile_json"])
            if all(prof.get(s, {"units": 0})["units"] >= _required_units(role, s) - TOL for s in need):
                db.execute("UPDATE projections SET resolved_at=?, fit_actual=?, snapshot_id=? WHERE id=?",
                           (VDB.now(), json.loads(sn["fits_json"])[role], sn["id"], p["id"]))
                break


def history(db, cid, role=None):
    snaps = db.execute("SELECT * FROM readiness_snapshots WHERE candidate_id=? ORDER BY id", (cid,)).fetchall()
    series, prev = [], {}
    for sn in snaps:
        prof, fits = json.loads(sn["profile_json"]), json.loads(sn["fits_json"])
        series.append({"id": sn["id"], "at": sn["created_at"], "trigger": sn["trigger"], "fits": fits,
                       "fit": fits.get(role) if role else None, "changes": _diff(prev, prof),
                       "verified_skills": sum(1 for p in prof.values() if p["basis"] == "verified")})
        prev = prof
    out = {"snapshots": series, "role": role}
    if role in D.ROLES:
        _resolve_projections(db, cid, role)
        rows = db.execute("SELECT * FROM projections WHERE candidate_id=? AND role=? ORDER BY id", (cid, role)).fetchall()
        out["projections"] = [{"id": r["id"], "learn": json.loads(r["learn_json"]), "also_needed": sorted(set(json.loads(r["to_learn_json"])) - set(json.loads(r["learn_json"]))),
                               "fit_before": r["fit_before"], "fit_projected": r["fit_projected"], "created_at": r["created_at"],
                               "resolved": r["resolved_at"] is not None, "fit_actual": r["fit_actual"],
                               "error_pts": None if r["fit_actual"] is None else round(r["fit_actual"] - r["fit_projected"], 1)} for r in rows]
    if len(series) >= 2 and role in D.ROLES:
        out["net_change_pts"] = round(series[-1]["fits"][role] - series[0]["fits"][role], 1)
    return out
