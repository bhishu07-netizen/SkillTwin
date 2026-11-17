"""Shared Playwright helpers for the UI end-to-end tests (assessment runner for any bank-backed skill)."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verification.bank import questions_for  # noqa: E402


def take_assessment(pg, skill, accuracy, seed=5):
    """Answer the live assessment in the browser: correct with probability `accuracy`. Returns questions answered."""
    bank = {q["id"]: q for q in questions_for(skill)}
    rng = random.Random(seed)
    n = 0
    while True:
        pg.wait_for_selector("#vSubmit")
        n += 1
        qid = pg.get_attribute(".qcard", "data-qid")
        q = bank[qid]
        good = rng.random() < accuracy
        if q["type"] in ("mcq", "scenario"):
            right = q["options"][q["answer"]]
            ans = right if good else next(o for o in q["options"] if o != right)
            labels = [o.inner_text().strip() for o in pg.query_selector_all("label.opt")]
            pg.click("label.opt >> nth=%d" % labels.index(ans))
        elif q["type"] == "output":
            pg.fill("#vText", q["expected"] if good else "nope")
        else:
            pg.fill("#vCode", q["reference"] if good else q["starter"])
        pg.click("#vSubmit")
        pg.wait_for_function("""(prev) => { const t = document.body.innerText;
            if (t.includes('Evidence for') || t.includes('Assessment expired') || t.includes('Assessment abandoned')) return true;
            const el = document.querySelector('.qcard'); return el && el.dataset.qid !== prev; }""", arg=qid, timeout=40000)
        if pg.query_selector("text=Evidence for") or pg.query_selector("text=Assessment expired") or pg.query_selector("text=Assessment abandoned"):
            return n
