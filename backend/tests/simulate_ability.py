"""Monte-Carlo check: simulated candidates of known ability (logistic model) take the real adaptive assessment
through the API. Prints mean score / level distribution per ability so thresholds can be sanity-checked.
Run: python tests/simulate_ability.py"""
import math, random, sys, tempfile
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verification import db as D, config as C
D.set_db_path(tempfile.mktemp(suffix=".db"))
import app as A
from test_flow import correct_answer, wrong_answer, run_attempt, result_of, new_candidate
A.init_db(); c = A.app.test_client()
B = {"easy": -1.5, "medium": 0.0, "hard": 1.5}
from verification.bank import get_question
for theta in (-3, -1.5, -0.5, 0.5, 1.5, 3, 5):
    rng = random.Random(theta * 7 + 1); scores = []; lv = Counter()
    for _ in range(12):
        cid = new_candidate(c, {"python": "Intermediate"})
        def ch(pub):
            p = 1 / (1 + math.exp(-(theta - B[get_question(pub["id"])["difficulty"]])))
            return correct_answer(pub) if rng.random() < p else wrong_answer(pub)
        v, n = run_attempt(c, cid, "python", ch)
        r = result_of(c, v); scores.append(r["assessment_score"]); lv[r["demonstrated_level"]] += 1
    print("ability %+.1f  mean score %5.1f  (min %4.0f max %4.0f)  levels %s" % (theta, sum(scores)/len(scores), min(scores), max(scores), dict(lv)))
