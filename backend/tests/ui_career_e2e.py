"""Headless UI test of the Reverse Engineer tab against a running server. Usage: python tests/ui_career_e2e.py [shots_dir]"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
shots = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/claude-0/shots"); shots.mkdir(exist_ok=True, parents=True)
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1000, "height": 1400})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://localhost:5000/"); pg.click("text=Continue as Demo Candidate")
    pg.click("[data-v=reverse]")
    pg.wait_for_selector("#reRole option >> nth=3", state="attached")
    assert "Reverse engineer a career" in pg.inner_text("#v-reverse")
    pg.fill("#reSearch", "security"); pg.wait_for_selector("#reChips .chip")
    assert "Cybersecurity Analyst" in pg.inner_text("#reChips")
    pg.click("text=Try demo profile")
    assert pg.input_value("#reRole") == "ML Engineer"
    pg.click("#v-reverse >> text=Reverse engineer my path"); pg.wait_for_selector("text=Roadmap compression")
    txt = pg.inner_text("#reBodyOut")
    assert "skills in the generic roadmap are skipped" in txt and "Path graph" in txt and "Generic AI vs SkillTwin" in txt
    pg.screenshot(path=str(shots / "r1_result.png"), full_page=True)
    pg.click("text=[View Evidence] >> nth=0"); pg.wait_for_selector(".ev.show")
    assert "market-demand index" in pg.inner_text(".ev.show")
    # what-if
    first = pg.query_selector_all(".simchk")[0].get_attribute("value")
    pg.check(".simchk >> nth=0"); pg.wait_for_selector("text=Fit after (projected)")
    assert "PROJECTION" in pg.inner_text("#reSim")
    pg.screenshot(path=str(shots / "r2_whatif.png"), full_page=True)
    before = pg.inner_text("#reBodyOut .fitnow")
    # reweight and recompute -> order changes
    order1 = [e.inner_text() for e in pg.query_selector_all("#reBodyOut .phase > b")]
    pg.fill("input[onchange*=\"'gap'\"]", "5"); pg.press("input[onchange*=\"'gap'\"]", "Tab")
    pg.fill("input[onchange*=\"'importance'\"]", "0"); pg.press("input[onchange*=\"'importance'\"]", "Tab")
    pg.click("button:has-text(\"Recompute\")"); pg.wait_for_timeout(800)
    order2 = [e.inner_text() for e in pg.query_selector_all("#reBodyOut .phase > b")]
    assert order1 != order2, "weights should change the ordering"
    # my own profile path (no demo)
    pg.click("text=Use my profile"); pg.select_option("#reRole", "Data Analyst"); pg.click("#v-reverse >> text=Reverse engineer my path")
    pg.wait_for_selector("text=Roadmap compression"); pg.wait_for_timeout(300)
    assert "Data Analyst" in pg.inner_text("#reBodyOut")
    pg.screenshot(path=str(shots / "r3_mine.png"), full_page=True)
    assert not errs, errs
    print("UI OK, js errors:", len(errs), "| demo path:", order1[:5])
    b.close()
