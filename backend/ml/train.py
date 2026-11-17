"""Train the SkillTwin market models from the SAS 'Analytics Jobs.csv' postings and write ml/model.json.

Run from the backend/ folder (training needs pandas + scikit-learn; the running app does not):

    pip install -r ml/requirements-train.txt
    python -m ml.train --postings "path/to/Analytics Jobs.csv"

Two models, both logistic regression on the app's own 37-skill vocabulary:
  pay      P(posting is in the >= 15 LPA salary band | skills mentioned, minimum experience)   binary
  segment  which market segment a posting belongs to, from skills alone                          7 classes
Every claim in the model card comes from grouped 5-fold cross-validation: repeated postings (same content, different
row id) always sit in the same fold, so a model cannot score well by memorising a posting it has already seen.
The raw CSV is never copied into the app; only the fitted weights and the evaluation summary are saved.
"""
import argparse
import datetime
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from .features import SKILLS, parse_min_experience, skills_in_text

SEED = 42
MIN_SUPPORT = 50     # a skill needs at least this many postings to be a model feature; rarer ones would only add noise
BANDS = ["0to3", "3to6", "6to10", "10to15", "15to25", "25to50"]
HIGH_PAY_BANDS = {"15to25", "25to50"}
# Segment is decided from the DESIGNATION only, while the model sees only the KEY-SKILLS text, so the label never leaks
# into the features. Postings whose designation matches no segment are left out of the segment model.
SEGMENTS = [
    ("Data Science / ML", r"data scien|machine learning|\bml\b|\bai\b|deep learning|\bnlp\b|artificial intel"),
    ("Data Engineering / Big Data", r"data engineer|big data|hadoop|spark|\betl\b|data warehous|data architect|database|dba"),
    ("Data / BI Analyst", r"data analy|bi analyst|business intelligence|reporting|\bmis\b|insight|analytics|statistic|quantitative|research analyst"),
    ("Business / Product Analyst", r"business analy|product (manager|analy|owner)|functional|process analy|business consult|business develop"),
    ("Marketing & Digital Analytics", r"seo|sem\b|digital|marketing|social media|campaign|content|brand|e-?commerce"),
    ("Finance / Risk Analytics", r"financ|risk|credit|audit|account|bank|actuar|invest|equity|treasury|insurance|tax|compliance"),
    ("Software / IT", r"develop|engineer|software|java|oracle|sap\b|test|\bqa\b|devops|\.net|programmer|application|consultant|support|network|cloud|architect"),
]


def segment_of(designation):
    d = str(designation).lower()
    for name, pat in SEGMENTS:
        if re.search(pat, d):
            return name
    return None


def _reliability(y, p, bins=5):
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, bins):
        out.append({"mean_predicted": float(p[chunk].mean()), "observed_rate": float(y[chunk].mean()), "n": int(len(chunk))})
    return out


def _scale(train_col, col):
    mu, sd = float(train_col.mean()), float(train_col.std() or 1.0)
    return (col - mu) / sd, mu, sd


def cv_pay(X_sk, exp, y, groups):
    cv = StratifiedGroupKFold(5, shuffle=True, random_state=SEED)
    specs = {
        "exp_only": lambda: LogisticRegression(max_iter=3000),
        "skills_only": lambda: LogisticRegression(C=1.0, max_iter=3000),
        "logistic (served)": lambda: LogisticRegression(C=1.0, max_iter=3000),
        "gradient_boosting": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.06, max_iter=150, random_state=SEED),
    }
    oof = {k: np.zeros(len(y)) for k in specs}
    fold_auc = {k: [] for k in specs}
    for tr, te in cv.split(X_sk, y, groups):
        ex_tr, mu, sd = _scale(exp[tr], exp[tr])
        ex_te = (exp[te] - mu) / sd
        mats = {"exp_only": (ex_tr[:, None], ex_te[:, None]),
                "skills_only": (X_sk[tr], X_sk[te]),
                "logistic (served)": (np.c_[X_sk[tr], ex_tr], np.c_[X_sk[te], ex_te]),
                "gradient_boosting": (np.c_[X_sk[tr], ex_tr], np.c_[X_sk[te], ex_te])}
        for k, mk in specs.items():
            m = mk().fit(mats[k][0], y[tr])
            p = m.predict_proba(mats[k][1])[:, 1]
            oof[k][te] = p
            fold_auc[k].append(roc_auc_score(y[te], p))
    base_acc = float(max(y.mean(), 1 - y.mean()))
    res = {}
    for k in specs:
        res[k] = {"auc": float(roc_auc_score(y, oof[k])), "auc_fold_sd": float(np.std(fold_auc[k])),
                  "brier": float(brier_score_loss(y, oof[k])), "accuracy": float(accuracy_score(y, oof[k] >= 0.5)),
                  "majority_accuracy": base_acc}
    return res, _reliability(y, oof["logistic (served)"])


def stability(X_sk, exp, y, groups, reps=500):
    """Cluster bootstrap (whole posting groups are resampled): a 95% interval for every skill weight. A skill is only
    used for advice when its interval excludes zero, i.e. its direction is clear in the data."""
    rng = np.random.default_rng(SEED)
    ug = np.unique(groups)
    rows = {k: np.where(groups == k)[0] for k in ug}
    A = np.c_[X_sk, (exp - exp.mean()) / (exp.std() or 1.0)]
    B = []
    for _ in range(reps):
        idx = np.concatenate([rows[k] for k in rng.choice(ug, len(ug))])
        B.append(LogisticRegression(C=1.0, max_iter=3000).fit(A[idx], y[idx]).coef_[0][:-1])
    lo, hi = np.percentile(np.array(B), [2.5, 97.5], axis=0)
    return lo, hi


def permutation_auc(X_sk, exp, y, groups, reps=15):
    """Cross-validated AUC after shuffling the labels. It should sit near 0.5; anything higher would mean leakage."""
    rng = np.random.default_rng(SEED)
    out = []
    for _ in range(reps):
        yp = rng.permutation(y)
        cv = StratifiedGroupKFold(5, shuffle=True, random_state=SEED)
        P = np.zeros(len(yp))
        for tr, te in cv.split(X_sk, yp, groups):
            ex_tr, mu, sd = _scale(exp[tr], exp[tr])
            m = LogisticRegression(C=1.0, max_iter=3000).fit(np.c_[X_sk[tr], ex_tr], yp[tr])
            P[te] = m.predict_proba(np.c_[X_sk[te], (exp[te] - mu) / sd])[:, 1]
        out.append(roc_auc_score(yp, P))
    return float(np.mean(out)), float(np.max(out))


def cv_segment(X_sk, y, groups):
    cv = StratifiedGroupKFold(5, shuffle=True, random_state=SEED)
    specs = {"logistic (served)": lambda: LogisticRegression(C=1.0, max_iter=5000),
             "gradient_boosting": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.06, max_iter=120, random_state=SEED)}
    pred = {k: np.empty(len(y), dtype=object) for k in specs}
    for tr, te in cv.split(X_sk, y, groups):
        for k, mk in specs.items():
            pred[k][te] = mk().fit(X_sk[tr], y[tr]).predict(X_sk[te])
    vc = pd.Series(y).value_counts()
    res = {"majority_class": {"accuracy": float(vc.iloc[0] / len(y)), "class": str(vc.index[0])}}
    for k in specs:
        res[k] = {"accuracy": float(accuracy_score(y, pred[k])), "macro_f1": float(f1_score(y, pred[k], average="macro"))}
    served = pred["logistic (served)"]
    res["recall_by_segment"] = {str(c): float(np.mean(served[y == c] == c)) for c in vc.index}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--postings", required=True, help="path to 'Analytics Jobs.csv'")
    ap.add_argument("--out", default=str(Path(__file__).with_name("model.json")))
    a = ap.parse_args()

    raw = pd.read_csv(a.postings)
    content = [c for c in raw.columns if c != "s_no"]
    raw["group"] = raw.groupby(content, dropna=False, sort=False).ngroup()
    raw["exp_min"] = raw.experience.map(parse_min_experience)
    sk = raw.key_skills.fillna("").map(skills_in_text)
    X_full = np.array([[1.0 if s in row else 0.0 for s in SKILLS] for row in sk])
    support_all = {s: int(X_full[:, i].sum()) for i, s in enumerate(SKILLS)}
    USED = [s for s in SKILLS if support_all[s] >= MIN_SUPPORT]
    X_all = X_full[:, [SKILLS.index(s) for s in USED]]
    has_skill = X_all.sum(1) > 0

    # ---- pay model
    m_pay = has_skill & raw.exp_min.notna().values & raw.salary.isin(BANDS).values
    Xp, ep = X_all[m_pay], raw.exp_min.values[m_pay]
    yp = raw.salary.isin(HIGH_PAY_BANDS).values[m_pay].astype(int)
    gp = raw.group.values[m_pay]
    pay_cv, reliability = cv_pay(Xp, ep, yp, gp)
    ex_s, mu, sd = _scale(ep, ep)
    pay_m = LogisticRegression(C=1.0, max_iter=3000).fit(np.c_[Xp, ex_s], yp)
    support = support_all
    lo, hi = stability(Xp, ep, yp, gp)
    coef_ci = {s: [float(lo[i]), float(hi[i])] for i, s in enumerate(USED)}
    clear = [s for i, s in enumerate(USED) if lo[i] > 0 or hi[i] < 0]
    perm_mean, perm_max = permutation_auc(Xp, ep, yp, gp)

    # ---- segment model
    seg_lab = raw.job_desig.map(segment_of)
    m_seg = has_skill & seg_lab.notna().values
    Xs, ys, gs = X_all[m_seg], seg_lab.values[m_seg].astype(str), raw.group.values[m_seg]
    seg_cv = cv_segment(Xs, ys, gs)
    seg_m = LogisticRegression(C=1.0, max_iter=5000).fit(Xs, ys)

    model = {
        "name": "SkillTwin market models v1",
        "trained_at": datetime.date.today().isoformat(),
        "seed": SEED,
        "source": "SAS CU hackathon file 'Analytics Jobs.csv' (job postings). Raw rows are not stored in the app.",
        "data": {"postings_total": int(len(raw)), "repeat_groups_handled": int(raw.group.nunique()),
                 "postings_mentioning_an_app_skill": int(has_skill.sum()), "pay_rows": int(m_pay.sum()),
                 "segment_rows": int(m_seg.sum()), "skills_in_vocabulary": len(SKILLS), "skills_used_by_model": USED,
                 "min_postings_per_skill": MIN_SUPPORT},
        "target": {"high_pay_definition": "salary band 15 LPA or above (15to25 or 25to50)",
                   "segments": [s[0] for s in SEGMENTS]},
        "pay": {"intercept": float(pay_m.intercept_[0]), "exp_coef": float(pay_m.coef_[0][-1]), "exp_mean": mu, "exp_scale": sd,
                "skill_coef": {s: float(c) for s, c in zip(USED, pay_m.coef_[0][:-1])}, "support": support,
                "base_rate": float(yp.mean()), "cv": pay_cv, "reliability": reliability,
                "coef_ci95": coef_ci, "skills_with_clear_direction": clear,
                "shuffled_label_auc": {"mean": perm_mean, "max": perm_max}},
        "segment": {"classes": [str(c) for c in seg_m.classes_], "intercept": [float(v) for v in seg_m.intercept_],
                    "coef": [{s: float(c) for s, c in zip(USED, row)} for row in seg_m.coef_], "cv": seg_cv,
                    "class_counts": {k: int(v) for k, v in pd.Series(ys).value_counts().items()}},
        "why_logistic": ("Gradient boosting was tried on the same folds and did not do meaningfully better, so the simpler logistic "
                         "model is served: every weight can be read, explained to a judge, and exported without scikit-learn."),
        "limitations": [
            "Postings show what employers ask for and offer, not what a person can do. Applying the model to someone's skill mix "
            "describes how similar postings are paid; it does not predict that person's salary.",
            "Only about a third of postings mention a skill from the app's 37-skill vocabulary, and a skill needs at least 50 postings to be used; "
            "skills below that (for example numpy, git, docker) are ignored by the model rather than guessed.",
            "Skills add only a small amount on top of experience for the pay question (compare 'exp_only' with 'logistic').",
            "Salary is an employer-stated band and 'high pay' means the 15 LPA band or above; the file has no dates, so drift over time "
            "cannot be checked.",
            "Repeated postings are kept in the same cross-validation fold; reported scores are out-of-fold.",
            "Most single-skill weights are too uncertain to interpret. Skill advice is shown only for skills whose weight has a "
            "bootstrap 95% interval that excludes zero.",
        ],
    }

    # golden examples: model.py must reproduce these sklearn outputs exactly (checked by tests/test_ml.py)
    cases = [([], 2.0), (["python"], 1.0), (["python", "sql", "machine learning"], 3.0), (["sql", "excel", "tableau"], 5.0),
             (["java", "aws", "docker", "linux"], 8.0)]
    gold = []
    for present, e in cases:
        row = np.array([[1.0 if s in present else 0.0 for s in USED]])
        p = float(pay_m.predict_proba(np.c_[row, [[(e - mu) / sd]]])[0, 1])
        sp = seg_m.predict_proba(row)[0]
        gold.append({"skills": present, "experience_years": e, "p_high_pay": p,
                     "segment_probs": {str(c): float(v) for c, v in zip(seg_m.classes_, sp)}})
    model["golden"] = gold

    Path(a.out).write_text(json.dumps(model, indent=1))
    print("pay rows", int(m_pay.sum()), "| segment rows", int(m_seg.sum()))
    print("pay CV:", json.dumps({k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in pay_cv.items()}, indent=1))
    print("segment CV:", json.dumps(seg_cv, indent=1))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
