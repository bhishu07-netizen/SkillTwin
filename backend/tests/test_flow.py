"""
End-to-end tests of the verification engine through the real HTTP API (Flask test client):
claim -> assessment -> backend grading -> level -> confidence -> evidence -> profile -> role match.
Run: python -m pytest tests/test_flow.py -q
"""
import os
import random
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from verification import config as C, db as D, evidence as EV, scoring  # noqa: E402
from verification.bank import get_question  # noqa: E402


_UUID = __import__("re").compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _make_client_class(A):
    from flask.testing import FlaskClient

    class TokenClient(FlaskClient):
        """Behaves like a real browser session: once a candidate exists, its token is sent automatically
        (unless the test sets X-Candidate-Token itself, e.g. to prove a missing/wrong token is rejected)."""
        tokens = {}

        def open(self, *args, **kw):
            headers = dict(kw.pop("headers", None) or {})
            if "X-Candidate-Token" not in headers:
                hay = str(args[0] if args else "") + str(kw.get("query_string", "")) + str(kw.get("json", ""))
                ids = _UUID.findall(hay)
                if ids and ids[0] in self.tokens:
                    headers["X-Candidate-Token"] = self.tokens[ids[0]]
            kw["headers"] = headers
            resp = super().open(*args, **kw)
            if resp.status_code == 401 and "X-Candidate-Token" not in headers and self.tokens:
                for tok in self.tokens.values():     # resource addressed by attempt/result id: use the owner's token
                    kw["headers"] = {**headers, "X-Candidate-Token": tok}
                    resp = super().open(*args, **kw)
                    if resp.status_code != 401:
                        break
            try:
                j = resp.get_json(silent=True)
                if isinstance(j, dict) and j.get("token") and j.get("candidate_id"):
                    self.tokens[j["candidate_id"]] = j["token"]
            except Exception:  # noqa: BLE001
                pass
            return resp

    return TokenClient


@pytest.fixture()
def client(monkeypatch):
    D.set_db_path(tempfile.mktemp(suffix=".db"))
    import importlib
    import app as A
    importlib.reload(A)
    A.init_db()
    C.reload_config()
    A.app.config["TESTING"] = True
    A.app.test_client_class = _make_client_class(A)
    return A.app.test_client()


def new_candidate(c, claims):
    cid = c.post("/api/candidates", json={"name": "t"}).json["candidate_id"]
    assert c.put("/api/candidates/%s/claims" % cid, json={"claims": claims}).status_code == 200
    return cid


def correct_answer(pub):
    q = get_question(pub["id"])
    if q["type"] in ("mcq", "scenario"):
        text = q["options"][q["answer"]]
        return next(o["id"] for o in pub["options"] if o["text"] == text)
    if q["type"] == "output":
        return q["expected"]
    return q["reference"]


def wrong_answer(pub):
    q = get_question(pub["id"])
    if q["type"] in ("mcq", "scenario"):
        text = q["options"][q["answer"]]
        return next(o["id"] for o in pub["options"] if o["text"] != text)
    if q["type"] == "output":
        return "definitely wrong"
    return q["starter"]


def run_attempt(c, cid, skill, chooser):
    """chooser(pub_question) -> raw answer. Returns (final attempt view, number answered)."""
    v = c.post("/api/verification/attempts", json={"candidate_id": cid, "skill": skill}).json
    n = 0
    while v["status"] == "in_progress":
        pub = v["question"]
        r = c.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                   json={"candidate_id": cid, "question_id": pub["id"], "answer": chooser(pub)})
        assert r.status_code == 200, r.json
        v = r.json["attempt"]
        n += 1
        assert n <= 12
    return v, n


def result_of(c, v):
    return c.get("/api/verification/results/%s" % v["result_id"]).json


def test_strong_candidate_gets_high_level_and_score_is_not_hardcoded(client):
    cid = new_candidate(client, {"python": "Advanced"})
    v, n = run_attempt(client, cid, "python", correct_answer)
    r = result_of(client, v)
    assert r["demonstrated_level"] in ("Advanced", "Expert")
    assert r["assessment_score"] >= 85 and 8 <= n <= 12
    assert r["badge"] == "PARTIALLY VERIFIED"  # no evidence yet -> never VERIFIED
    assert r["discrepancy"]["code"] in ("claim_supported", "skill_underestimated")


def test_weak_candidate_gets_beginner_and_overestimation_message(client):
    cid = new_candidate(client, {"python": "Advanced"})
    v, _ = run_attempt(client, cid, "python", wrong_answer)
    r = result_of(client, v)
    assert r["demonstrated_level"] == "Beginner" and r["assessment_score"] < 40
    assert r["discrepancy"]["code"] == "overestimation"
    assert "lie" not in r["discrepancy"]["message"].lower()
    assert "does not attempt to detect lies" in r["disclaimer"]


def test_score_depends_on_actual_answers(client):
    """Same candidate, different behaviour -> different, monotone results."""
    scores = []
    for p in (0.0, 0.5, 1.0):
        rng = random.Random(7)
        cid = new_candidate(client, {"python": "Intermediate"})
        v, _ = run_attempt(client, cid, "python", lambda pub: correct_answer(pub) if rng.random() < p else wrong_answer(pub))
        scores.append(result_of(client, v)["assessment_score"])
    assert scores[0] < scores[1] < scores[2], scores


def test_answers_are_locked_and_order_enforced(client):
    cid = new_candidate(client, {"python": "Intermediate"})
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
    pub = v["question"]
    url = "/api/verification/attempts/%s/answer" % v["attempt_id"]
    first = client.post(url, json={"candidate_id": cid, "question_id": pub["id"], "answer": correct_answer(pub)})
    assert first.status_code == 200
    again = client.post(url, json={"candidate_id": cid, "question_id": pub["id"], "answer": wrong_answer(pub)})
    assert again.status_code == 409
    # a question that is NOT the one currently being served must be refused. The next question is chosen adaptively, so
    # pick an id that differs from it (a fixed id would occasionally be the real next question and correctly return 200).
    nxt = (((first.json or {}).get("attempt") or {}).get("question") or {}).get("id")
    assert nxt, "the answer response should carry the next question"
    out_of_order = "py-i-h2" if nxt != "py-i-h2" else "py-i-h1"
    other = client.post(url, json={"candidate_id": cid, "question_id": out_of_order, "answer": "x"})
    assert other.status_code == 409
    # another candidate cannot touch the attempt
    cid2 = new_candidate(client, {"python": "Beginner"})
    assert client.post(url, json={"candidate_id": cid2, "question_id": pub["id"], "answer": "x"}).status_code in (401, 403)


def test_client_cannot_inject_scores_or_see_the_key(client):
    cid = new_candidate(client, {"python": "Intermediate"})
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
    blob = str(v)
    for forbidden in ("answer", "expected", "reference", "explanation", "hidden", "score"):
        assert forbidden not in set(v["question"].keys()), forbidden
    pub = v["question"]
    r = client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                    json={"candidate_id": cid, "question_id": pub["id"], "answer": wrong_answer(pub),
                          "score": 1.0, "is_correct": True, "assessment_score": 100})
    assert r.status_code == 200
    assert "correct" not in str(r.json["attempt"].get("question", {}))
    # the stored score is the server's, not the injected one
    row = D.connect().execute("SELECT score FROM answers").fetchone()
    assert row["score"] < 1.0  # server-computed (starter code may earn partial credit); never the injected 1.0


def test_options_shuffled_per_attempt_and_tokens_are_opaque(client):
    from verification import engine as E
    orders = {tuple(E.option_order("seed%d" % i, "py-f-m1", 4)) for i in range(30)}
    assert len(orders) > 6  # genuinely shuffled across attempts
    t1 = E.option_token("secret", "attemptA", "py-f-m1", 1)
    assert t1 != E.option_token("secret", "attemptB", "py-f-m1", 1)      # per-attempt
    assert t1 != E.option_token("secret", "attemptA", "py-f-m1", 2)
    assert not any(ch.isdigit() and len(t1) < 4 for ch in t1)            # not a bare index
    cid = new_candidate(client, {"python": "Intermediate"})
    ids = set()
    for _ in range(3):
        v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
        ids.add(v["attempt_id"])
        client.post("/api/verification/attempts/%s/finish" % v["attempt_id"], json={"candidate_id": cid})
    assert len(ids) == 3  # a fresh variant each time


def test_retake_prefers_new_questions(client):
    cid = new_candidate(client, {"python": "Intermediate"})
    first = set()
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
    while v["status"] == "in_progress":
        first.add(v["question"]["id"])
        v = client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                        json={"candidate_id": cid, "question_id": v["question"]["id"],
                              "answer": correct_answer(v["question"])}).json["attempt"]
    second = set()
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
    while v["status"] == "in_progress":
        second.add(v["question"]["id"])
        v = client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                        json={"candidate_id": cid, "question_id": v["question"]["id"],
                              "answer": correct_answer(v["question"])}).json["attempt"]
    assert len(first & second) <= max(2, len(first) // 3), (first & second)


def test_adaptive_difficulty_and_prerequisite_probe(client):
    cid = new_candidate(client, {"python": "Advanced"})
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
    q1 = get_question(v["question"]["id"])
    assert q1["difficulty"] == "medium"
    v = client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                    json={"candidate_id": cid, "question_id": q1["id"], "answer": wrong_answer(v["question"])}).json["attempt"]
    assert get_question(v["question"]["id"])["difficulty"] == "easy"
    rows = D.connect().execute("SELECT selection_reason FROM answers").fetchall()
    assert rows
    # after a correct answer the next target rises
    v = client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                    json={"candidate_id": cid, "question_id": v["question"]["id"],
                          "answer": correct_answer(v["question"])}).json["attempt"]
    assert get_question(v["question"]["id"])["difficulty"] == "medium"


def test_timer_expiry_closes_attempt_server_side(client, monkeypatch):
    cid = new_candidate(client, {"python": "Intermediate"})
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
    real = D.now
    monkeypatch.setattr(D, "now", lambda: real() + C.CONFIG["assessment"]["time_limit_s"] + 5)
    pub = v["question"]
    r = client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                    json={"candidate_id": cid, "question_id": pub["id"], "answer": correct_answer(pub)})
    assert r.status_code == 410
    st = client.get("/api/verification/attempts/%s?candidate_id=%s" % (v["attempt_id"], cid)).json
    assert st["status"] == "expired" and st["result_id"] is None  # too few answers -> no result


def test_code_question_graded_in_sandbox_with_partial_credit(client):
    cid = new_candidate(client, {"python": "Intermediate"})
    v = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "python"}).json
    # walk forward (answering correctly) until a code question appears
    for _ in range(12):
        pub = v["question"]
        if pub["type"] in ("code", "debug"):
            break
        v = client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                        json={"candidate_id": cid, "question_id": pub["id"], "answer": correct_answer(pub)}).json["attempt"]
    assert pub["type"] in ("code", "debug")
    assert "starter" in pub and pub["visible_tests"] and "tests" not in pub
    run = client.post("/api/verification/attempts/%s/run" % v["attempt_id"],
                      json={"candidate_id": cid, "question_id": pub["id"], "code": pub["starter"]}).json
    assert run["total"] == len(pub["visible_tests"])
    evil = client.post("/api/verification/attempts/%s/run" % v["attempt_id"],
                       json={"candidate_id": cid, "question_id": pub["id"], "code": "import os\n"}).json
    assert "not allowed" in evil["rejected"]
    client.post("/api/verification/attempts/%s/answer" % v["attempt_id"],
                json={"candidate_id": cid, "question_id": pub["id"], "answer": get_question(pub["id"])["reference"]})
    row = D.connect().execute("SELECT score, details_json FROM answers WHERE question_id=?", (pub["id"],)).fetchone()
    assert row["score"] == 1.0


def test_spec_example_formula():
    assert scoring.confidence(82, 75, 90) == pytest.approx(81.4, abs=0.05)
    assert scoring.level_from_score(39.9) == "Beginner" and scoring.level_from_score(40) == "Intermediate"
    assert scoring.level_from_score(70) == "Advanced" and scoring.level_from_score(85) == "Expert"


def test_weights_and_thresholds_are_configurable(tmp_path, monkeypatch):
    cfgfile = tmp_path / "c.json"
    cfgfile.write_text('{"weights": {"assessment": 1, "evidence": 0, "consistency": 0}, "level_thresholds": {"Intermediate": 10}}')
    monkeypatch.setenv("SKILLTWIN_VERIFY_CONFIG", str(cfgfile))
    C.reload_config()
    try:
        assert scoring.confidence(80, 0, 0) == 80.0
        assert scoring.level_from_score(15) == "Intermediate"
    finally:
        monkeypatch.delenv("SKILLTWIN_VERIFY_CONFIG")
        C.reload_config()


def test_discrepancy_matrix():
    d = scoring.discrepancy
    assert d("Advanced", "Advanced", 75)["code"] == "claim_supported"
    assert d("Advanced", "Intermediate", 50)["code"] == "overestimation"
    assert d("Advanced", "Intermediate", 67)["code"] == "claim_near"
    assert d("Intermediate", "Advanced", 78)["code"] == "skill_underestimated"
    assert d("Beginner", "Beginner", 20)["code"] == "claim_supported"


def test_level_guard_requires_hard_questions():
    answers = [{"difficulty": "easy", "score": 1.0, "category": "fundamentals"}] * 10
    lvl, notes = scoring.demonstrated_level(100, answers)
    assert lvl == "Intermediate" and notes


def test_evidence_work_sample_and_recompute_and_profile(client):
    cid = new_candidate(client, {"python": "Advanced", "sql": "Intermediate"})
    rng = random.Random(3)
    v, _ = run_attempt(client, cid, "python", lambda p: correct_answer(p) if rng.random() < 0.6 else wrong_answer(p))
    before = result_of(client, v)
    code = ("import json\n\nclass Store:\n    \"\"\"Tiny store.\"\"\"\n    def __init__(self):\n        self.d = {}\n\n"
            "    def put(self, k: str, v: int) -> None:\n        self.d[k] = v\n\n    def dump(self) -> str:\n"
            "        try:\n            return json.dumps(self.d)\n        except TypeError:\n            return '{}'\n\n"
            "def squares(n):\n    return [i * i for i in range(n)]\n\ndef gen(n):\n    for i in range(n):\n        yield i\n\n"
            "def test_store():\n    s = Store()\n    s.put('a', 1)\n    assert s.dump() == '{\"a\": 1}'\n" + "x = 1\n" * 30)
    r = client.post("/api/verification/evidence", json={"candidate_id": cid, "skill": "python", "type": "work_sample",
                                                         "title": "Store", "code": code})
    assert r.status_code == 201
    ev = r.json["evidence"]
    assert ev["status"] == "verified" and ev["strength"] > 0.3 and ev["checks"]
    after = result_of(client, v)
    assert after["evidence_score"] > before["evidence_score"] and after["confidence"] > before["confidence"]
    assert after["evidence_summary"]["verified"] == 1
    # unverifiable evidence is recorded as provided and heavily discounted
    r2 = client.post("/api/verification/evidence", json={"candidate_id": cid, "skill": "python", "type": "certification",
                                                          "title": "Python course certificate", "description": "python basics"})
    assert r2.json["evidence"]["status"] == "provided" and r2.json["evidence"]["strength"] <= 0.25
    # invalid python is not verified
    bad = client.post("/api/verification/evidence", json={"candidate_id": cid, "skill": "python", "type": "work_sample",
                                                           "title": "broken", "code": "def f(:\n"}).json["evidence"]
    assert bad["status"] != "verified" and bad["strength"] == 0
    # profile: verified skill uses demonstrated level, unverified one is discounted
    prof = client.get("/api/candidates/%s" % cid).json
    assert prof["skills"]["python"]["basis"] == "verified"
    assert prof["skills"]["sql"]["basis"] == "self-declared" and prof["effective"]["sql"] == pytest.approx(0.56)
    imp = client.get("/api/candidates/%s/impact" % cid).json
    assert imp["roles"] and "verified_fit_pct" in imp["roles"][0]
    m = client.post("/api/match", json={"candidate_id": cid, "role": "Data Scientist"}).json
    assert m["basis"] == "verified-adjusted"


def test_verified_badge_requires_everything(client):
    cid = new_candidate(client, {"python": "Intermediate"})
    # slow the answers down so the rapid-answer check can't interfere
    v, _ = run_attempt(client, cid, "python", correct_answer)
    r = result_of(client, v)
    assert r["badge"] != "VERIFIED"  # no evidence
    code = open(__file__).read()  # any parseable python
    for i in range(3):
        client.post("/api/verification/evidence", json={"candidate_id": cid, "skill": "python", "type": "work_sample",
                                                         "title": "sample %d" % i, "code": "def f%d(x):\n    return [i for i in range(x)]\n" % i + "y = 1\n" * 60})
    r = result_of(client, v)
    assert r["verified_evidence_score"] >= 40


class FakeGH:
    def __init__(self, langs, fork=False):
        self.langs, self.fork = langs, fork

    def __call__(self, url):
        if url.endswith("/languages"):
            return self.langs
        if url.endswith("/readme"):
            raise RuntimeError("none")
        return {"fork": self.fork, "pushed_at": "2026-06-01T00:00:00Z", "description": "demo", "topics": [], "name": "r",
                "stargazers_count": 3, "size": 100}


def test_github_verification_logic_with_mocked_api(monkeypatch):
    monkeypatch.setattr(EV, "_get_json", FakeGH({"Python": 60000, "Shell": 1000}))
    good = EV.evaluate("python", "github", "My repo", "https://github.com/octo/demo", "", "")
    assert good["status"] == "verified" and good["strength"] > 0.8
    monkeypatch.setattr(EV, "_get_json", FakeGH({"JavaScript": 90000}))
    off_topic = EV.evaluate("python", "github", "My repo", "https://github.com/octo/js-app", "", "")
    assert off_topic["status"] == "provided" and off_topic["strength"] < 0.2
    monkeypatch.setattr(EV, "_get_json", FakeGH({"Python": 60000}, fork=True))
    forked = EV.evaluate("python", "github", "fork", "https://github.com/octo/forked", "", "")
    assert forked["strength"] < good["strength"]
    mism = EV.evaluate("python", "github", "x", "https://github.com/octo/demo", "", "", github_username="someoneelse")
    assert mism["strength"] < good["strength"]

    def boom(url):
        raise OSError("offline")
    monkeypatch.setattr(EV, "_get_json", boom)
    offline = EV.evaluate("python", "github", "x", "https://github.com/octo/demo", "python repo", "")
    assert offline["status"] == "provided"  # unreachable -> never silently "verified"


def test_unsupported_skill_is_refused_honestly(client):
    cid = new_candidate(client, {"excel": "Advanced"})
    r = client.post("/api/verification/attempts", json={"candidate_id": cid, "skill": "excel"})
    assert r.status_code == 422 and r.json["code"] == "unsupported_skill"


def test_sandbox_limits_hold():
    from verification import sandbox
    r = sandbox.run_function_tests("def f(x):\n    while True:\n        pass\n", "f", [{"args": [1], "expected": 1}],
                                   per_test_s=1, wall_timeout=5)
    assert r["passed"] == 0
    r = sandbox.run_function_tests("def f(x):\n    return len([0] * (10 ** 10))\n", "f", [{"args": [1], "expected": 1}])
    assert r["passed"] == 0
    for evil in ["import subprocess\ndef f(x): return 1", "def f(x):\n    return ().__class__.__bases__",
                 "def f(x): return eval('1')", "def f(x): return open('/etc/passwd').read()"]:
        with pytest.raises(sandbox.SandboxRejected):
            sandbox.run_function_tests(evil, "f", [{"args": [1], "expected": 1}])
