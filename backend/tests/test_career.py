"""Career Path Optimization Engine tests: graph validity, algorithmic properties, determinism,
profile-dependence, verification integration, configurability. Run: python -m pytest tests/test_career.py -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from career import data as D, engine as E  # noqa: E402
from test_flow import client, new_candidate, run_attempt, correct_answer, wrong_answer  # noqa: E402,F401

DEMO = {"python": "Advanced", "statistics": "Intermediate", "sql": "Beginner", "machine learning": "Beginner"}


def prof(decl, trust=True):
    return E.build_profile(declared=decl, trust_declared=trust)


def test_dataset_meets_spec_and_is_a_dag():
    assert len(D.ROLES) >= 5 and len(D.SKILLS) >= 20
    D.validate()
    for s in D.SKILLS.values():
        assert 0 < s["demand"] <= 100 and s["hours"] > 0
    D.SKILLS["python"]["prereqs"].append("algorithms")
    try:
        with pytest.raises(AssertionError):
            D.validate()
    finally:
        D.SKILLS["python"]["prereqs"].remove("algorithms")


@pytest.mark.parametrize("role", list(D.ROLES))
@pytest.mark.parametrize("decl", [{}, DEMO, {"linux": "Intermediate", "git": "Advanced"}])
def test_path_is_a_valid_topological_order(role, decl):
    r = E.analyze(role, prof(decl))
    pos = {s["skill"]: i for i, s in enumerate(r["steps"])}
    for s in r["steps"]:
        for p in D.SKILLS[s["skill"]]["prereqs"]:
            if p in pos:
                assert pos[p] < pos[s["skill"]]
                assert next(x for x in r["steps"] if x["skill"] == p)["phase"] < s["phase"]
            else:  # an unneeded prerequisite must genuinely be satisfied
                assert any(k["skill"] == p for k in r["skipped"])


def test_mastered_skills_are_skipped_and_counted():
    r = E.analyze("ML Engineer", prof(DEMO))
    names = {s["skill"] for s in r["steps"]}
    assert "python" not in names and "statistics" not in names
    assert {"python", "statistics"} <= {s["skill"] for s in r["skipped"]}
    assert r["compression"]["skills_skipped"] == r["compression"]["generic_skill_count"] - len(r["steps"]) == 2


def test_nothing_hardcoded_path_depends_on_profile():
    a = E.analyze("ML Engineer", prof({}))
    b = E.analyze("ML Engineer", prof(DEMO))
    c = E.analyze("ML Engineer", prof({"linux": "Advanced", "networking": "Advanced", "git": "Advanced", "numpy": "Advanced"}))
    sa, sb, sc = ([s["skill"] for s in x["steps"]] for x in (a, b, c))
    assert len({len(sa), len(sb), len(sc)}) == 3 and sa != sb != sc
    assert a["total_hours"] > b["total_hours"] > 0
    assert "docker" in sb and E.analyze("ML Engineer", prof({"docker": "Advanced", "linux": "Advanced"}))["steps"] and \
        "docker" not in [s["skill"] for s in E.analyze("ML Engineer", prof({"docker": "Advanced", "linux": "Advanced"}))["steps"]]


def test_deterministic():
    assert E.analyze("Data Scientist", prof(DEMO)) == E.analyze("Data Scientist", prof(DEMO))


def test_full_profile_has_empty_path():
    full = {s: "Advanced" for s in D.SKILLS}
    r = E.analyze("ML Engineer", prof(full))
    assert r["steps"] == [] and r["fit_pct"] == 100.0 and r["total_hours"] == 0


def test_whatif_is_monotonic_and_unlocks():
    p = prof(DEMO)
    base = E.analyze("ML Engineer", p)
    s1 = E.simulate("ML Engineer", p, ["numpy"])
    s2 = E.simulate("ML Engineer", p, ["numpy", "linux"])
    assert s1["fit_after_pct"] > s1["fit_before_pct"] == base["fit_pct"]
    assert s2["fit_after_pct"] >= s1["fit_after_pct"]
    assert {u["skill"] for u in s1["newly_unlocked"]} >= {"pandas", "scikit-learn"}
    assert "PROJECTION" in s1["label"]
    d = E.simulate("ML Engineer", p, ["docker"])
    assert d["also_required_first"] == ["linux"]                      # prerequisites are pulled in, not skipped
    assert any(m["skill"] == "model deployment" for m in d["moved_closer"])
    assert E.simulate("ML Engineer", p, ["python"])["not_applicable"] == ["python"]   # already mastered


def test_priority_formula_and_configurable_weights():
    p = prof(DEMO)
    a = E.analyze("ML Engineer", p)
    st = next(s for s in a["steps"] if s["skill"] == "machine learning")
    c = st["components"]
    expect = 100 * (c["importance"] * c["demand"] * c["gap"] * c["criticality"]) ** 0.25
    assert abs(st["priority"] - expect) < 0.2
    only_gap = E.analyze("ML Engineer", p, E.cfg_with({"weights": {"importance": 0, "demand": 0, "criticality": 0, "gap": 1}}))
    assert [s["skill"] for s in a["steps"]] != [s["skill"] for s in only_gap["steps"]]
    assert E.analyze("ML Engineer", p, E.cfg_with({"hours_per_week": 20}))["weeks"] == round(a["total_hours"] / 20, 1)


def test_unverified_claims_are_not_equal_to_verified():
    decl = E.build_profile(declared={"python": "Advanced"}, trust_declared=False)
    face = E.build_profile(declared={"python": "Advanced"}, trust_declared=True)
    assert decl["python"]["units"] < face["python"]["units"]
    r = E.analyze("ML Engineer", face)
    assert "python" in r["needs_verification"]


def test_search_and_aliases():
    assert E.search_roles("security")[0]["role"] == "Cybersecurity Analyst"
    assert E.search_roles("mle")[0]["role"] == "ML Engineer"
    assert E.search_roles("zzzz") == []


def test_api_demo_flow_and_errors(client):
    d = client.get("/api/career/demo-profile").json
    r = client.post("/api/career/reverse-engineer", json={"role": d["role"], "declared": d["declared"], "trust_declared": True}).json
    assert r["role"] == "ML Engineer" and r["steps"] and r["explanation"]["source"] == "deterministic"
    assert "SkillTwin computes YOUR shortest path" in r["positioning"]["tagline"]
    ev = client.get("/api/career/evidence/ML Engineer/docker").json
    assert ev["role_importance"] == D.ROLES["ML Engineer"]["reqs"]["docker"]["importance"]
    assert client.post("/api/career/reverse-engineer", json={"role": "Astronaut"}).status_code == 400
    assert client.post("/api/career/reverse-engineer", json={"role": "ML Engineer", "declared": {"nope": "Advanced"}}).status_code == 400
    assert client.post("/api/career/reverse-engineer", json={"role": "ML Engineer", "candidate_id": "x"}).status_code == 401


def test_verification_feeds_reverse_engineering(client):
    strong = new_candidate(client, {"python": "Advanced"})
    weak = new_candidate(client, {"python": "Advanced"})
    run_attempt(client, strong, "python", correct_answer)
    run_attempt(client, weak, "python", wrong_answer)
    rs = client.post("/api/career/reverse-engineer", json={"role": "ML Engineer", "candidate_id": strong}).json
    rw = client.post("/api/career/reverse-engineer", json={"role": "ML Engineer", "candidate_id": weak}).json
    assert rs["meta"]["verified_count"] == 1 == rw["meta"]["verified_count"]
    assert rs["profile"]["python"]["basis"] == "verified"
    assert rs["fit_pct"] > rw["fit_pct"]
    assert "python" in [s["skill"] for s in rw["steps"]]            # a failed claim re-enters the path
    assert "python" not in [s["skill"] for s in rs["steps"]]        # a demonstrated skill is skipped
    legacy = client.post("/api/match", json={"role": "ML Engineer", "candidate_id": strong}).json
    assert legacy["fit_pct"] > 0
