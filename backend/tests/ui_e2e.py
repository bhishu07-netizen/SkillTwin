"""Headless-browser end-to-end test of the real UI against a running server (python app.py).
Usage: python tests/ui_e2e.py [accuracy 0..1] [shots_dir]"""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from verification.bank import questions_for
BANK = {q["id"]: q for q in questions_for("python")}
acc = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
shots = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/claude-0/shots"); shots.mkdir(exist_ok=True, parents=True)
rng = random.Random(5)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1000, "height": 1300})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: d.accept())
    pg.goto("http://localhost:5000/"); pg.click("text=Continue as Demo Candidate")
    pg.wait_for_selector("#claimSkill option >> nth=1", state="attached")
    pg.select_option("#claimSkill", "python"); pg.select_option("#claimLevel", "Advanced"); pg.click("#addSkills button:has-text('Add'):not(:has-text('Find'))")
    pg.fill("#resumeInput", "SQL, Excel"); pg.click("text=Find skills in text")
    pg.wait_for_selector("text=not verified yet"); pg.screenshot(path=str(shots / "1_my_skills.png"))
    pg.click("#skillsList button:has-text('Verify')"); pg.wait_for_selector("text=Start assessment")
    pg.screenshot(path=str(shots / "2_intro.png")); pg.click("text=Start assessment")
    n = 0
    while True:
        pg.wait_for_selector("#vSubmit"); n += 1
        prompt = pg.get_attribute(".qcard", "data-qid"); q = BANK[prompt]; good = rng.random() < acc
        if n == 4: pg.screenshot(path=str(shots / "3_question.png"))
        if q["type"] in ("mcq", "scenario"):
            ans = q["options"][q["answer"]] if good else next(o for o in q["options"] if o != q["options"][q["answer"]])
            pg.click(f".opt:has-text(\"{ans[:40]}\")" if False else f"label.opt >> nth={[o.inner_text().strip() for o in pg.query_selector_all('label.opt')].index(ans)}")
        elif q["type"] == "output":
            pg.fill("#vText", q["expected"] if good else "nope")
        else:
            pg.fill("#vCode", q["reference"] if good else q["starter"])
            if n == 5 or q["type"] == "debug":
                pg.click("#vRun"); pg.wait_for_selector("#vRunOut .note")
                if n == 5: pg.screenshot(path=str(shots / "3b_code_run.png"))
        pg.click("#vSubmit")
        try:
          pg.wait_for_function("""(prev) => { const t = document.body.innerText; if (t.includes('Evidence for') || t.includes('Assessment expired') || t.includes('Assessment abandoned')) return true;
            const el = document.querySelector('.qcard'); return el && el.dataset.qid !== prev; }""", arg=prompt, timeout=40000)
        except Exception:
          print("STUCK at Q", n, q["id"], q["type"], "\n", pg.inner_text("#verifyRoot")[:600]); pg.screenshot(path=str(shots / "stuck.png")); raise
        if pg.query_selector("text=Evidence for") or pg.query_selector("text=Assessment expired") or pg.query_selector("text=Assessment abandoned"): break
    print("answered", n)
    pg.select_option("#evType", "work_sample"); pg.fill("#evTitle", "My store")
    pg.fill("#evCode", "class Store:\n    \"\"\"d\"\"\"\n    def __init__(self):\n        self.d = {}\n    def put(self, k: str, v: int) -> None:\n        self.d[k] = v\n\ndef sq(n):\n    return [i*i for i in range(n)]\n\ndef g(n):\n    for i in range(n):\n        yield i\n\ndef test_a():\n    assert sq(2) == [0, 1]\n" + "z = 1\n"*40)
    pg.click("#evAdd"); pg.wait_for_selector("text=EVIDENCE VERIFIED"); pg.screenshot(path=str(shots / "4_evidence.png"))
    pg.click("text=Continue to result"); pg.wait_for_selector("text=How the confidence was calculated"); pg.wait_for_selector("#impactBox table")
    pg.screenshot(path=str(shots / "5_result.png"), full_page=True)
    print(pg.inner_text(".vgrid").replace("\n", " | "))
    pg.click("text=Explain my result"); pg.wait_for_selector("#explainOut .note"); pg.click("text=Review my answers"); pg.wait_for_selector("#reviewOut .card")
    pg.click("text=Generate roadmap for"); pg.wait_for_selector("text=Your roadmap"); pg.wait_for_selector("#roadmapCard .phase"); pg.screenshot(path=str(shots / "6_roadmap.png"))
    pg.click("[data-v=explorer]"); pg.wait_for_selector("#fitCard .fit"); pg.screenshot(path=str(shots / "7_fit.png"))
    print("JS errors:", errs); b.close()
