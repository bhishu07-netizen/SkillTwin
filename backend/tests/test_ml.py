"""Market ML: inference reproduces scikit-learn exactly, behaves sensibly, and the API validates input."""
import json
import math

import pytest

from ml import model as M
from test_flow import client  # noqa: F401  (shared app fixture)


def _gold():
    return M.card()["golden"]


@pytest.mark.parametrize("i", range(5))
def test_inference_matches_sklearn_reference(i):
    g = _gold()[i]
    assert M.p_high_pay(set(g["skills"]), g["experience_years"]) == pytest.approx(g["p_high_pay"], abs=1e-9)
    if g["skills"]:
        got = {r["segment"]: r["probability"] for r in M.segment_probs(set(g["skills"]))}
        for k, v in g["segment_probs"].items():
            assert got[k] == pytest.approx(v, abs=1e-9)


def test_probabilities_are_valid_and_experience_helps():
    assert 0 < M.p_high_pay({"python"}, 0) < 1
    assert M.p_high_pay({"python"}, 10) > M.p_high_pay({"python"}, 1)
    assert sum(r["probability"] for r in M.segment_probs({"sql", "excel"})) == pytest.approx(1.0)


def test_skill_lifts_sorted_positive_and_supported():
    lifts = M.skill_lifts({"python"}, 2, top=5)
    assert lifts == sorted(lifts, key=lambda r: -r["delta_pts"])
    assert all(r["delta_pts"] > 0 and r["postings"] >= M.MIN_SUPPORT and r["skill"] != "python" for r in lifts)
    clear = set(M.card()["pay"]["skills_with_clear_direction"])
    assert lifts and all(r["skill"] in clear for r in lifts)     # advice only from weights with a clear direction


def test_stability_checks_are_recorded():
    pay = M.card()["pay"]
    assert abs(pay["shuffled_label_auc"]["mean"] - 0.5) < 0.03          # shuffled labels -> chance, so no leakage
    for s in pay["skills_with_clear_direction"]:
        lo, hi = pay["coef_ci95"][s]
        assert lo > 0 or hi < 0


def test_model_card_reports_honest_metrics():
    c = M.card_public()
    assert "golden" not in c and c["limitations"]
    cv = c["pay"]["cv"]
    assert 0.5 < cv["logistic (served)"]["auc"] < 1 and cv["exp_only"]["auc"] > 0.5
    assert c["data"]["pay_rows"] > 1000


def test_api_outlook(client):
    r = client.post("/api/ml/market-outlook", json={"declared": {"python": "Intermediate", "sql": "Beginner"}, "experience_years": 3})
    assert r.status_code == 200
    d = r.get_json()
    assert 0 < d["high_pay"]["probability"] < 1 and d["segments"] and d["model"]["cv_auc"] > 0.5 and d["caveats"]


def test_api_empty_profile_and_bad_input(client):
    r = client.post("/api/ml/market-outlook", json={"declared": {}})
    assert r.status_code == 200 and r.get_json()["enough_skills"] is False
    for bad in ({"experience_years": -1}, {"experience_years": "x"}, {"experience_years": True}, {"declared": {"nope": "Beginner"}}):
        assert client.post("/api/ml/market-outlook", json=bad).status_code == 400


def test_api_model_card(client):
    r = client.get("/api/ml/model-card")
    assert r.status_code == 200 and "golden" not in r.get_json()
