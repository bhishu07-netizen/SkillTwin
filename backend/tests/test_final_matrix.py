"""
Final scenario matrix (spec section 12): every scenario asserts that results actually CHANGE with the inputs, and that
bad inputs / failures degrade safely. Everything goes through the real HTTP API (Flask test client with token handling).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm  # noqa: E402
import security  # noqa: E402
from test_flow import client, new_candidate, run_attempt, correct_answer, wrong_answer, result_of  # noqa: E402,F401


def re_(c, role, cid, **kw):
    r = c.post("/api/career/reverse-engineer", json={"role": role, "candidate_id": cid, **kw})
    assert r.status_code == 200, r.json
    return r.json


def new_user(c):
    return c.post("/api/candidates", json={}).json["candidate_id"]


# ---------------------------------------------------------------- profiles
def test_new_user_with_no_skills_does_not_crash_and_gets_the_full_path(client):
    cid = new_user(client)
    r = re_(client, "ML Engineer", cid)
    assert r["fit_pct"] == 0 and r["compression"]["skills_skipped"] == 0 and len(r["steps"]) == r["compression"]["generic_skill_count"]
    assert client.post("/api/match", json={"role": "ML Engineer", "candidate_id": cid}).json["fit_pct"] == 0
    cop = client.post("/api/career/copilot", json={"candidate_id": cid, "message": "What are my biggest gaps?", "role": "ML Engineer"}).json
    assert cop["intent"] == "no_profile"
    assert client.get("/api/career/history/%s" % cid).json["snapshots"][0]["fits"]["ML Engineer"] == 0
    assert client.post("/api/career/fit-all", json={"candidate_id": cid}).status_code == 200


def test_self_declared_is_credited_less_than_verified_and_flagged(client):
    cid = new_candidate(client, {"python": "Advanced"})
    face = re_(client, "ML Engineer", cid, trust_declared=True)
    cautious = re_(client, "ML Engineer", cid)
    assert "python" in face["needs_verification"] and "python" not in [s["skill"] for s in face["steps"]]
    assert "python" in [s["skill"] for s in cautious["steps"]]          # 80% credit is not 'mastered'
    assert face["fit_pct"] > cautious["fit_pct"]
    assert cautious["profile"]["python"]["basis"] == "self-declared" and cautious["profile"]["python"]["badge"] == "SELF-DECLARED"


def test_overestimated_and_underestimated_skills_move_everything_downstream(client):
    over = new_candidate(client, {"python": "Advanced"})
    under = new_candidate(client, {"python": "Beginner"})
    base_under = re_(client, "ML Engineer", under)["fit_pct"]
    run_attempt(client, over, "python", wrong_answer)
    run_attempt(client, under, "python", correct_answer)
    ro, ru = (result_of(client, client.get("/api/verification/results?candidate_id=%s&skill=python" % c).json["latest"]) for c in (over, under))
    assert ro["discrepancy"]["code"] == "overestimation" and "does not attempt to detect lies" in ro["discrepancy"]["disclaimer"]
    assert ru["discrepancy"]["code"] == "skill_underestimated"
    assert re_(client, "ML Engineer", under)["fit_pct"] > base_under                       # demonstrating more raises fit
    assert "python" in [s["skill"] for s in re_(client, "ML Engineer", over)["steps"]]       # a failed claim re-enters the path
    assert "python" not in [s["skill"] for s in re_(client, "ML Engineer", under)["steps"]]


def test_changed_claims_and_target_role_recalculate(client):
    cid = new_candidate(client, {"python": "Beginner"})
    a = re_(client, "ML Engineer", cid)
    client.put("/api/candidates/%s/claims" % cid, json={"claims": {"python": "Advanced", "sql": "Advanced"}})
    b = re_(client, "ML Engineer", cid)
    assert b["fit_pct"] > a["fit_pct"] and b["total_hours"] < a["total_hours"]
    other = re_(client, "Cybersecurity Analyst", cid)
    assert [s["skill"] for s in other["steps"]][:3] != [s["skill"] for s in b["steps"]][:3] and other["role"] != b["role"]
    fits = client.post("/api/career/fit-all", json={"candidate_id": cid}).json["fits"]
    assert len(set(fits.values())) > 3
    assert fits["ML Engineer"] == b["fit_pct"]


def test_every_surface_agrees_on_the_numbers(client):
    cid = new_candidate(client, {"python": "Advanced", "sql": "Intermediate"})
    r = re_(client, "Data Scientist", cid)
    assert client.post("/api/match", json={"role": "Data Scientist", "candidate_id": cid}).json["fit_pct"] == pytest.approx(r["fit_pct"], abs=0.1)
    legacy_gap = client.post("/api/gap-analysis", json={"role": "Data Scientist", "candidate_id": cid}).json
    assert legacy_gap["fit_pct"] == r["fit_pct"] and legacy_gap["engine"] == "career-path-optimization"
    legacy_road = client.post("/api/roadmap", json={"role": "Data Scientist", "candidate_id": cid}).json
    assert legacy_road["total_hours"] == r["total_hours"]
    sim = client.post("/api/simulate", json={"role": "Data Scientist", "candidate_id": cid, "learn_skills": ["statistics"]}).json
    assert "PROJECTION" in sim["label"] and sim["after"]["fit_pct"] > sim["before"]["fit_pct"]


# ---------------------------------------------------------------- verification flows
def test_sql_assessment_end_to_end_and_no_key_leak(client):
    cid = new_candidate(client, {"sql": "Advanced"})
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "sql"}).json
    blob = json.dumps(v)
    assert "_verify" not in blob and '"expected"' not in blob and '"answer"' not in blob
    strong, _ = run_attempt(client, new_candidate(client, {"sql": "Advanced"}), "sql", correct_answer)
    weak, _ = run_attempt(client, new_candidate(client, {"sql": "Advanced"}), "sql", wrong_answer)
    rs, rw = result_of(client, strong), result_of(client, weak)
    assert rs["assessment_score"] > 85 > 20 > rw["assessment_score"] and rw["discrepancy"]["code"] == "overestimation"


def test_missing_and_unverifiable_evidence_never_inflates_confidence(client):
    cid = new_candidate(client, {"python": "Intermediate"})
    v, _ = run_attempt(client, cid, "python", correct_answer)
    base = result_of(client, v)
    assert base["evidence_score"] == 0 and base["badge"] == "PARTIALLY VERIFIED"
    r = client.post("/api/verification/evidence", json={"candidate_id": cid, "skill": "python", "type": "certification",
                                                         "title": "Cert", "url": "http://insecure.example/cert"})
    assert r.status_code in (200, 201)
    after = client.get("/api/verification/results?candidate_id=%s&skill=python" % cid).json["latest"]
    assert after["confidence"] <= base["confidence"] + 0.01 and after["badge"] != "VERIFIED"       # provided != verified


def test_retake_and_projection_vs_actual_loop(client):
    cid = new_candidate(client, {"sql": "Beginner"})
    sim = client.post("/api/career/simulate", json={"role": "Data Analyst", "candidate_id": cid, "learn": ["sql"]}).json
    assert sim["projection_id"] and sim["fit_after_pct"] > sim["fit_before_pct"]
    run_attempt(client, cid, "sql", wrong_answer)
    h1 = client.get("/api/career/history/%s?role=Data Analyst" % cid).json
    assert h1["projections"][0]["resolved"] is False                    # skill not yet at the required level
    run_attempt(client, cid, "sql", correct_answer)                      # retake, new variant
    h2 = client.get("/api/career/history/%s?role=Data Analyst" % cid).json
    p = h2["projections"][0]
    assert p["resolved"] and p["fit_actual"] is not None and abs(p["error_pts"]) < 15
    assert len(h2["snapshots"]) >= 3 and h2["snapshots"][-1]["fit"] > h2["snapshots"][1]["fit"]
    assert any(c["skill"] == "sql" for c in h2["snapshots"][-1]["changes"])


def test_history_dedupes_unchanged_profiles(client):
    cid = new_candidate(client, {"python": "Advanced"})
    for _ in range(3):
        client.get("/api/career/history/%s" % cid)
        re_(client, "ML Engineer", cid)
    assert len(client.get("/api/career/history/%s" % cid).json["snapshots"]) == 1


# ---------------------------------------------------------------- invalid input & failures
@pytest.mark.parametrize("body", [
    {"role": ["ML Engineer"]}, {"role": 5}, {"role": "Nope"}, {"role": "ML Engineer", "declared": [1]},
    {"role": "ML Engineer", "declared": {"python": "Godlike"}}, {"role": "ML Engineer", "declared": {"cobol": "Advanced"}},
    {"role": "ML Engineer", "weights": "x"}, {"role": "ML Engineer", "candidate_id": 5},
])
def test_invalid_inputs_are_rejected_not_crashed(client, body):
    r = client.post("/api/career/reverse-engineer", json=body)
    assert r.status_code in (400, 401) and "error" in r.json


def test_absurd_config_is_clamped_not_trusted(client):
    r = client.post("/api/career/reverse-engineer", json={"role": "ML Engineer", "declared": {"python": "Beginner"},
                                                           "weights": {"importance": 0, "demand": 0, "gap": 0, "criticality": 0, "x": 9},
                                                           "hours_per_week": -5}).json
    assert r["config"]["hours_per_week"] == 10 and sum(r["config"]["weights"].values()) > 0 and r["steps"]


def test_other_bad_requests(client):
    assert client.post("/api/career/simulate", json={"role": "ML Engineer", "declared": {}, "learn": "docker"}).status_code == 400
    assert client.post("/api/career/copilot", json={"message": "x" * 600}).status_code == 400
    assert client.post("/api/career/copilot", json={"message": ""}).status_code == 400
    assert client.post("/api/gap-analysis", json={"role": ["x"]}).status_code == 400
    assert client.post("/api/roadmap", data="not json", content_type="application/json").status_code == 400
    assert client.get("/api/nope").status_code == 404 and client.get("/api/nope").json["error"]
    assert client.post("/api/ai/generate", json={"kind": "shell"}).status_code == 400
    cid = new_user(client)
    assert client.put("/api/candidates/%s/claims" % cid, json={"claims": {"cobol": "Advanced"}}).status_code == 400
    assert client.put("/api/candidates/%s/claims" % cid, json={"claims": {"python": "Wizard"}}).status_code == 400


def test_ai_failure_and_misbehaviour_fall_back_to_the_computed_answer(client, monkeypatch):
    cid = new_candidate(client, {"python": "Advanced"})
    ask = lambda: client.post("/api/career/copilot", json={"candidate_id": cid, "role": "ML Engineer", "message": "What should I learn next?"}).json  # noqa: E731
    monkeypatch.setattr(llm, "generate", lambda *a, **k: None)             # outage / quota / timeout
    plain = ask()
    assert plain["source"] == "deterministic" and plain["text"]
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "You are 99% ready and should learn Kubernetes.")   # invents a number
    assert ask()["source"] == "deterministic"
    nums = " ".join(__import__("re").findall(r"\d+(?:\.\d+)?", plain["text"]))
    monkeypatch.setattr(llm, "generate", lambda *a, **k: "Reworded: " + plain["text"])                       # faithful rewording is accepted
    assert ask()["source"].startswith("ai:") and nums
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert client.post("/api/ai/generate", json={"kind": "future_watch"}).status_code == 503


def test_llm_helper_survives_network_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("network down")))
    assert llm.generate("hi") is None


# ---------------------------------------------------------------- security
def test_candidate_routes_require_the_owner_token(client):
    from flask.testing import FlaskClient
    cid = new_candidate(client, {"python": "Advanced"})
    tok = client.tokens[cid] if hasattr(client, "tokens") else None
    other = new_user(client)
    bad = {"X-Candidate-Token": "nope"}
    for method, url, kw in [("get", "/api/candidates/%s" % cid, {}), ("put", "/api/candidates/%s/claims" % cid, {"json": {"claims": {}}}),
                            ("post", "/api/career/reverse-engineer", {"json": {"role": "ML Engineer", "candidate_id": cid}}),
                            ("get", "/api/career/history/%s" % cid, {}), ("post", "/api/verification/attempts", {"json": {"candidate_id": cid, "skill": "python"}}),
                            ("get", "/api/candidates/%s/impact" % cid, {})]:
        assert getattr(client, method)(url, headers=bad, **kw).status_code == 401, url
    wrong_owner = {"X-Candidate-Token": client.tokens[other]}
    assert client.get("/api/candidates/%s" % cid, headers=wrong_owner).status_code == 401
    assert client.get("/api/candidates/%s" % cid, headers={"X-Candidate-Token": tok}).status_code == 200
    # attempts/results are resolved to their owner
    v, _ = run_attempt(client, cid, "python", correct_answer)
    assert client.get("/api/verification/results/%s" % v["result_id"], headers=wrong_owner).status_code == 401
    assert client.get("/api/verification/results/%s" % v["result_id"], headers={"X-Candidate-Token": tok}).status_code == 200
    assert client.get("/api/verification/attempts/%s?candidate_id=%s" % (v["attempt_id"], cid), headers=wrong_owner).status_code == 401
    # public, non-personal routes stay open
    assert client.get("/api/career/roles", headers=bad).status_code == 200


def test_rate_limit_and_body_cap_and_cors(client, monkeypatch):
    monkeypatch.setitem(security.LIMITS, "general", (5, 60.0))
    codes = [client.get("/api/health").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and set(codes[5:]) == {429}
    monkeypatch.setitem(security.LIMITS, "general", (600, 60.0))
    assert client.post("/api/career/copilot", data="x" * 300_000, content_type="application/json").status_code == 413
    ok = client.get("/api/health", headers={"Origin": "http://localhost"})
    evil = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in evil.headers and evil.headers["X-Content-Type-Options"] == "nosniff"
    same = client.get("/api/health", headers={"Origin": "http://localhost"})
    assert same.headers.get("Access-Control-Allow-Origin") == "http://localhost"


def test_api_key_never_appears_in_responses(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-KEY-123")
    for url in ("/api/health", "/api/career/config", "/api/verification/config", "/api/career/demo-profile"):
        assert "SECRET-KEY-123" not in client.get(url).get_data(as_text=True)
