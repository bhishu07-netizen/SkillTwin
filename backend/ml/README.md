# Market ML (trained on real postings)

Two logistic-regression models trained on the SAS file `Analytics Jobs.csv` (15,841 job postings):

| Model | Question | Out-of-fold result (grouped 5-fold CV) |
|---|---|---|
| pay | Is a posting in the 15 LPA+ band, given the skills it lists and its minimum experience? | AUC 0.81 (experience alone 0.80, skills alone 0.64) |
| segment | Which market segment does a skill mix look like (7 segments)? | accuracy 60% vs 40% for always guessing the biggest segment; macro-F1 0.29; it finds 3 of the 7 segments (Software / IT 91%, Data Science / ML 68%, Data / BI Analyst 58%) and almost never the other four |

Reading it honestly: for the pay question, skills add only a little on top of experience. The segment model is useful
for the big segments and weak for the small ones. Both statements are in the in-app model card.

- Features: the app's own skill vocabulary; a skill needs 50+ postings to be used (rarer skills are ignored, not guessed).
- Repeated postings are kept in one fold (no memorising). Segment labels come from the designation only; the model sees only key-skills.
- Checks stored in `model.json`: shuffled-label AUC 0.50 (no leakage); AUC gain from skills 0.013 (bootstrap 95% CI 0.006 to 0.020); only 7 of 21 skill weights have a clear direction, and skill advice uses only those.
- Gradient boosting was compared and did not do meaningfully better, so the transparent logistic model is served.
- Runtime is pure Python (`model.py` + `model.json`); scikit-learn is needed only to retrain.

Retrain (from `backend/`): `pip install -r ml/requirements-train.txt` then
`python -m ml.train --postings "path/to/Analytics Jobs.csv"`. The raw CSV is never stored in the app.

API: `POST /api/ml/market-outlook` (same profile body as the other engines plus `experience_years`), `GET /api/ml/model-card`.
