"""
Question-bank self-test. Proves, for every question, that:
  * MCQ answers are valid indices and options are unique
  * every `output` question's expected text equals what the snippet REALLY prints
  * every code/debug question's reference solution passes 100% of its tests in the sandbox
  * the starter code (and each deliberately wrong solution) FAILS at least one test
  * each coding question has >=2 visible and >=2 hidden tests
Run:  python -m pytest tests/test_bank.py -q
"""
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from verification import sandbox
from verification.bank import python_bank as pb
from verification.bank import questions_for

QS = questions_for("python")
IDS = [q["id"] for q in QS]


def norm(text):
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def test_bank_shape():
    assert len(QS) >= 36
    assert len(IDS) == len(set(IDS))
    diffs = {d: sum(q["difficulty"] == d for q in QS) for d in ("easy", "medium", "hard")}
    assert all(v >= 10 for v in diffs.values()), diffs
    cats = {q["category"] for q in QS}
    assert cats == {"fundamentals", "code_reading", "debugging", "problem_solving", "implementation"}
    # every category must exist at every difficulty so the adaptive engine can always find a question
    for c in cats:
        for d in ("easy", "medium", "hard"):
            assert any(q["category"] == c and q["difficulty"] == d for q in QS), (c, d)
    types = {q["type"] for q in QS}
    assert {"mcq", "scenario", "output", "code", "debug"} <= types


@pytest.mark.parametrize("q", [q for q in QS if q["type"] in ("mcq", "scenario")], ids=lambda q: q["id"])
def test_mcq(q):
    assert 0 <= q["answer"] < len(q["options"])
    assert len(set(q["options"])) == len(q["options"]) >= 3
    assert q["explanation"]


@pytest.mark.parametrize("q", [q for q in QS if q["type"] == "output"], ids=lambda q: q["id"])
def test_output_matches_real_execution(q):
    r = subprocess.run([sys.executable, "-c", q["code"]], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    assert norm(r.stdout) == norm(q["expected"])
    # the snippet must also be valid for the sandbox screen (so selftest == what a learner could run)
    sandbox.screen_source(q["code"])


@pytest.mark.parametrize("q", [q for q in QS if q["type"] in ("code", "debug")], ids=lambda q: q["id"])
def test_code_question(q):
    tests = q["tests"]
    visible = [t for t in tests if t.get("visible")]
    hidden = [t for t in tests if not t.get("visible")]
    assert len(visible) >= 2 and len(hidden) >= 2, "need >=2 visible and >=2 hidden tests"

    t0 = time.time()
    ref = sandbox.run_function_tests(q["reference"], q["func"], tests)
    elapsed = time.time() - t0
    assert ref["passed"] == ref["total"], [r for r in ref["results"] if not r["passed"]] or ref["fatal"]
    assert elapsed < 8, "reference too slow: %.1fs" % elapsed

    starter = sandbox.run_function_tests(q["starter"], q["func"], tests)
    assert starter["passed"] < starter["total"], "starter already passes everything"
    if q["type"] == "debug":
        # a debug task must visibly fail on a visible test so the learner can see the bug
        assert any(not r["passed"] for r in starter["results"] if r["visible"]), "bug not exposed by visible tests"

    for w in q.get("wrong", []):
        res = sandbox.run_function_tests(w, q["func"], tests)
        assert res["passed"] < res["total"], "a wrong solution passes all tests -> tests too weak"


def test_hidden_tests_never_leak():
    q = next(q for q in QS if q["id"] == "py-p-m2")
    res = sandbox.run_function_tests(q["starter"], q["func"], q["tests"])
    for r in res["results"]:
        if not r["visible"]:
            assert set(r) <= {"index", "visible", "passed", "error"}
