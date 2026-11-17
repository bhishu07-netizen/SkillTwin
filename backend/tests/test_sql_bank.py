"""SQL bank self-test: every keyed option is proven by executing it with sqlite3."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verification.bank import sql_bank as sb, questions_for, is_supported, advice_for  # noqa: E402

QS = questions_for("sql")


def test_shape_and_coverage():
    assert is_supported("sql") and len(QS) >= 36
    assert len({q["id"] for q in QS}) == len(QS)
    d = {x: sum(q["difficulty"] == x for q in QS) for x in ("easy", "medium", "hard")}
    assert all(v >= 10 for v in d.values()), d
    for c in {"fundamentals", "code_reading", "debugging", "problem_solving", "implementation"}:
        for x in ("easy", "medium", "hard"):
            assert any(q["category"] == c and q["difficulty"] == x for q in QS), (c, x)
    assert {q["concept"] for q in QS} <= set(advice_for("sql"))
    assert {q["type"] for q in QS} <= {"mcq", "scenario", "output"}


@pytest.mark.parametrize("q", [q for q in QS if q["type"] != "output"], ids=lambda q: q["id"])
def test_mcq_shape(q):
    assert 0 <= q["answer"] < len(q["options"]) and len(set(q["options"])) == len(q["options"]) >= 3


@pytest.mark.parametrize("q", [q for q in QS if q["type"] == "output"], ids=lambda q: q["id"])
def test_output_key_is_real_sql_result(q):
    assert q["expected"].strip(), "empty key"
    query = q["code"].split("\n\n", 1)[1]
    assert sb.run(query) == q["expected"]


@pytest.mark.parametrize("q", [q for q in QS if "_verify" in q], ids=lambda q: q["id"])
def test_pick_the_query_keyed_option_is_the_only_one_matching_target(q):
    target = sb.run(q["_verify"]["target"])
    for i, opt in enumerate(q["options"]):
        try:
            got = sb.run(opt)
        except sqlite3.Error:
            got = None
        if i == q["answer"]:
            assert got == target, (opt, got, target)
        else:
            assert got != target, "distractor %d returns the same rows as the target: %s" % (i, opt)


def test_no_hidden_fields_leak_to_client():
    from verification import engine
    pub = engine._public_question(QS[0], 1) if hasattr(engine, "_public_question") else None
    if pub:
        assert "_verify" not in pub and "answer" not in pub and "expected" not in pub
