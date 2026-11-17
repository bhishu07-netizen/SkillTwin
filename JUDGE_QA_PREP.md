# Judge Q&A prep (team COGNIX)

Read the answers, then say them in your own words. If you cannot explain a line, open the file and read it together as a team before the event.

## Everyone should be able to answer

**1. What problem does SkillTwin solve?**
CVs claim skills but do not prove them. SkillTwin tests the skill, scores it with a confidence number, and then gives the shortest learning path to a target role.

**2. Why can't a user cheat the score?**
The browser sends answers, never scores. The server grades, keeps the clock, and locks answers. Code answers run against hidden tests. A self-declared level cannot raise the score; it is only compared against the test result (that comparison is the 10% consistency part). 70% is the measured test itself.

**3. Where does AI (Gemini) come in?**
Only for explanations and the Copilot chat. All numbers come from deterministic code, so the same input always gives the same result and we can explain every figure.

**4. Did you use AI tools to build this?**
Answer honestly and in line with the competition rules. A good way to say it: "We used AI tools to help us write and review code, the same way developers use any tool. The problem choice, the analysis findings and the design decisions are ours, and we can walk you through any file." Do not claim you wrote everything by hand if that is not true.

**5. What did the data analysis find?** (Approach Note)
Pick three: skills track traits; entry-level AI/ML postings pay a big premium (87% vs 40% above 3 lakh); senior success is a "zone" not a straight line (QDA AUC 0.9995 vs 0.964 linear). Also say the limits: 12 junior profiles have identical scores and opposite outcomes, which caps accuracy at 91.4%.

## Technical questions

**6. How is confidence calculated?** `0.70 x assessment + 0.20 x evidence + 0.10 x consistency`. Weights are in `verification/config.py`.

**7. Why those weights?** Measured performance is the strongest signal; evidence (certificates, projects) can be faked or inflated; consistency catches claim vs result mismatch. They are configurable in one file, so they can be tuned with real data.

**8. How do you stop malicious code in the code questions?** AST screen (allow-listed imports, no eval/exec/open), separate process, wall-clock timeout, process group kill, answers never given to the process.

**9. How is the learning path ordered?** Gap size, role importance, market demand and dependency criticality are combined into a priority; then a topological sort makes sure prerequisites come first.

**10. What if Gemini is down?** The app keeps working. Scores, gaps and roadmaps do not use Gemini. Explanations fall back to rule-based text.

**11. Why Flask + SQLite?** Small, simple, easy to deploy on Render's free plan, and enough for a prototype. For production we would move to PostgreSQL and add login.

**12. How is the data protected?** No secrets in code (key only in Render environment), rate limiting, same-origin CORS, and the scorecard runs fully in the browser.

## ML model questions

**M1. Where is the machine learning in SkillTwin?**
The Market ML tab. Two logistic-regression models trained on 15,841 real job postings: one estimates the chance a posting pays 15 LPA or more from its skills and experience, the other finds the closest market segment. They are served live from the backend.

**M2. How did you check it works?**
Grouped 5-fold cross-validation, so repeated postings never sit on both sides of a split. Pay AUC 0.81, compared against experience alone (0.80), skills alone (0.64) and gradient boosting (0.81).

**M3. Skills add only 0.01 AUC. Isn't that weak?**
Yes, and the app says so. Experience explains most of pay in this data. We report it rather than hide it.

**M4. Why logistic regression and not something fancier?**
Gradient boosting scored the same on the same folds, so we kept the simpler model: every weight can be read and explained.

**M5. Is the segment model good?**
Moderate. 60% accuracy against 40% for always guessing the biggest segment. It recognises three segments (Software / IT, Data Science / ML, Data / BI Analyst) and almost never the other four (macro-F1 0.29). The app says this on the screen.

**M5b. How do you know the score is not leakage or luck?**
Three checks: repeated postings never straddle folds; with shuffled labels the AUC falls to 0.50; and the result is the same across five different fold splits (0.808 to 0.810). The gain from skills is small but real: 0.013 AUC, bootstrap 95% interval 0.006 to 0.020.

**M5c. Which skills matter for pay in your data?**
Only a few have a clear direction: algorithms, machine learning, regression, statistics and R are positive; Power BI and networking are negative. For the other 14 the data cannot tell, so the app gives no advice on them.

**M6. Can the model predict my salary?**
No. It describes how postings asking for skills like yours are paid. It is an association in the data, not a promise.

## Hard questions (be honest)

**13. Is the dataset real?** The role/skill data inside the app is an illustrative sample (the footer says so). The scorecard models are fitted on the SAS hackathon files.

**14. What are the limitations?** In-memory rate limiting and SQLite do not scale across many servers; question bank is small; the free Render plan sleeps when idle; we ran the analysis in Python, and Appendix D maps each step to SAS.

**15. What would you build next?** More skills and question banks, proof via real project reviews, PostgreSQL, login, and employer-side views.

## 10-minute presentation split (suggested)

1. Problem and idea (Bhavishay): 1.5 min
2. Data findings (Taranjot, Shourya): 3 min
3. Live demo of SkillTwin: verify -> fit -> path (Sunny): 3 min
4. Impact, limits, next steps (Joshua): 1.5 min
5. Q&A: everyone, pass the question to whoever knows that part.

## Before the event

- Each member opens at least two files from `backend/` and explains them aloud to the others.
- Run the app locally once, with no internet, in case the venue Wi-Fi fails.
- Check `/api/ai/status?test=1` on the Render link the day before.
