"""
The live judge demo, driven through the real UI against a running server (python app.py):
claim Python Advanced -> assessment -> demonstrated level & confidence -> ML Engineer -> fit & gaps -> Reverse Engineer ->
What-If Docker -> View Evidence -> Gap/Roadmap/Copilot agree -> readiness history.  Then repeats with an over-claimer.
Usage: python tests/ui_judge_demo.py [shots_dir]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.sync_api import sync_playwright
from ui_helpers import take_assessment

shots = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-0/shots"); shots.mkdir(exist_ok=True, parents=True)


def pct(text, label):
    m = re.search(label + r"\D{0,40}?(\d+(?:\.\d+)?)%", text)
    return float(m.group(1)) if m else None


def run(b, name, accuracy, tag):
    ctx = b.new_context(viewport={"width": 1000, "height": 1400}); pg = ctx.new_page()
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: d.accept())
    pg.goto("http://localhost:5000/"); pg.click("text=Continue as Demo Candidate")
    pg.wait_for_selector("#claimSkill option >> nth=1", state="attached")
    # 1. claim
    pg.select_option("#claimSkill", "python"); pg.select_option("#claimLevel", "Advanced"); pg.click("#addSkills button:has-text('Add'):not(:has-text('Find'))")
    pg.wait_for_selector("text=not verified yet")
    # 2-5. assessment -> demonstrated level & confidence
    pg.click("#skillsList button:has-text('Verify')"); pg.wait_for_selector("text=Start assessment"); pg.click("text=Start assessment")
    n = take_assessment(pg, "python", accuracy)
    pg.click("text=Continue to result"); pg.wait_for_selector("text=How the confidence was calculated")
    grid = pg.inner_text(".vgrid").replace("\n", " | ")
    print("[%s] answered %d questions | %s" % (name, n, grid))
    pg.screenshot(path=str(shots / ("%s_1_result.png" % tag)), full_page=True)
    # 6-8. ML Engineer: role fit & gaps
    pg.click("[data-v=explorer]"); pg.click(".rolecard:has-text('ML Engineer')"); pg.wait_for_selector("#fitCard .fit")
    fit = float(pg.inner_text("#fitCard .fit").replace("%", ""))
    pg.click("[data-v=gap]"); pg.wait_for_selector("#gapCard .skill"); gap_txt = pg.inner_text("#gapCard")
    assert "View evidence" in gap_txt and "ML Engineer" in gap_txt
    # 9-10. reverse engineer
    pg.click("[data-v=reverse]"); pg.click("#v-reverse button:has-text('Reverse engineer my path')"); pg.wait_for_selector("text=Roadmap compression", timeout=8000) if False else pg.wait_for_selector("text=Roadmap compression")
    body = pg.inner_text("#reBodyOut")
    steps = [e.inner_text() for e in pg.query_selector_all("#reBodyOut .phase > b") if re.match(r"\d+\. ", e.inner_text())]
    names = [re.sub(r"^\d+\.\s*", "", s).lower() for s in steps]
    print("[%s] fit %.1f%% | path (%d): %s" % (name, fit, len(names), ", ".join(names[:8])))
    assert f"{fit}%" in body or abs(float(pg.inner_text("#reBodyOut .fitnow").replace("%","")) - fit) < 0.05, "Explorer fit and engine fit disagree"
    pg.screenshot(path=str(shots / ("%s_2_path.png" % tag)), full_page=True)
    # 11-12. what-if docker
    before = float(pg.inner_text("#reBodyOut .fitnow").replace("%",""))
    pg.check(".simchk[value='docker']"); pg.wait_for_selector("text=Fit after (projected)")
    sim = pg.inner_text("#reSim"); after = float(re.search(r"Fit after \(projected\)\s*([\d.]+)%", sim).group(1))
    assert after > before and "PROJECTION" in sim and "linux" in sim.lower(), sim
    print("[%s] what-if docker: %.1f%% -> %.1f%% | %s" % (name, before, after, sim.replace("\n", " ")[:200]))
    pg.screenshot(path=str(shots / ("%s_3_whatif.png" % tag)), full_page=True)
    # 13-14. evidence
    docker = pg.query_selector(".phase:has(.simchk[value='docker'])"); docker.query_selector(".evbtn").click(); pg.wait_for_selector(".ev.show")
    ev = pg.inner_text(".ev.show"); assert "importance 72/100" in ev, ev
    # downstream tabs agree
    pg.click("[data-v=roadmap]"); pg.wait_for_selector("#roadmapCard .phase"); rm = pg.inner_text("#roadmapCard")
    assert "Your roadmap" in rm and "Phase 1" in rm
    hours = re.search(r"· ([\d.]+)h", rm).group(1)
    assert re.search(r"skills · " + re.escape(hours) + "h", body), "roadmap tab and reverse tab disagree on effort"
    pg.click("[data-v=copilot]"); pg.click("button:has-text('Learning')"); pg.wait_for_selector("text=computed from your profile")
    cop = pg.inner_text("#copFeed"); assert "Start with" in cop, cop
    # readiness history
    pg.click("[data-v=reverse]"); pg.click("#v-reverse button:has-text('Reverse engineer my path')"); pg.wait_for_selector("#reHist:has-text('Readiness over time')")
    pg.wait_for_function("() => document.querySelector('#reHist').innerText.includes('verification')")
    print("[%s] history: %s" % (name, pg.inner_text("#reHist").replace("\n", " | ")[:300]))
    assert not errs, errs
    ctx.close()
    return {"fit": fit, "python_in_path": "python" in names, "n_steps": len(names), "grid": grid}


with sync_playwright() as p:
    b = p.chromium.launch()
    strong = run(b, "strong candidate", 1.0, "strong")
    weak = run(b, "over-claimer", 0.0, "weak")
    b.close()
print("strong:", strong["fit"], "python on path:", strong["python_in_path"], "| weak:", weak["fit"], "python on path:", weak["python_in_path"])
assert strong["fit"] > weak["fit"] and not strong["python_in_path"] and weak["python_in_path"]
print("JUDGE DEMO OK")
