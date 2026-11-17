"""
Evidence intake. Nothing is trusted blindly: every item is machine-checked where
technically possible and labelled either "verified" (an objective check passed) or
"provided" (recorded, but could not be checked - it counts at a heavy discount).

"Verified" means the artefact EXISTS and is RELEVANT to the skill. It does NOT prove
authorship - there is no login/ownership proof in this prototype - and every item
carries that limitation explicitly.
"""
import ast
import base64
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import config as C

EVIDENCE_TYPES = ["github", "project", "certification", "coursework", "work_sample"]

SKILL_SIGNALS = {
    "python": {"languages": ["Python", "Jupyter Notebook"], "keywords": ["python", "py", "pandas", "flask", "django"]},
    "sql": {"languages": ["PLpgSQL", "TSQL", "PLSQL", "SQL"], "keywords": ["sql", "mysql", "postgres", "sqlite"]},
    "java": {"languages": ["Java", "Kotlin"], "keywords": ["java", "spring", "maven"]},
    "javascript": {"languages": ["JavaScript", "TypeScript"], "keywords": ["javascript", "node", "react", "typescript"]},
    "r": {"languages": ["R"], "keywords": ["rstats", "ggplot", "tidyverse"]},
    "docker": {"languages": ["Dockerfile"], "keywords": ["docker", "container", "compose"]},
    "machine learning": {"languages": [], "keywords": ["machine learning", "ml", "classification", "regression", "sklearn", "model"]},
    "deep learning": {"languages": [], "keywords": ["deep learning", "neural", "pytorch", "tensorflow", "keras"]},
    "scikit-learn": {"languages": [], "keywords": ["scikit", "sklearn"]},
    "pandas": {"languages": [], "keywords": ["pandas", "dataframe"]},
    "statistics": {"languages": [], "keywords": ["statistic", "hypothesis", "regression", "probability"]},
    "excel": {"languages": [], "keywords": ["excel", "spreadsheet", "pivot"]},
    "power bi": {"languages": [], "keywords": ["power bi", "powerbi", "dax"]},
    "tableau": {"languages": [], "keywords": ["tableau"]},
    "aws": {"languages": [], "keywords": ["aws", "ec2", "s3", "lambda", "cloud"]},
    "git": {"languages": [], "keywords": ["git", "version control"]},
    "data visualization": {"languages": [], "keywords": ["visualization", "dashboard", "chart", "matplotlib"]},
    "communication": {"languages": [], "keywords": ["presentation", "communication", "stakeholder"]},
}

CERT_ISSUER_DOMAINS = {
    "credly.com": "Credly", "www.credly.com": "Credly", "coursera.org": "Coursera", "www.coursera.org": "Coursera",
    "udemy.com": "Udemy", "www.udemy.com": "Udemy", "freecodecamp.org": "freeCodeCamp",
    "www.freecodecamp.org": "freeCodeCamp", "hackerrank.com": "HackerRank", "www.hackerrank.com": "HackerRank",
    "edx.org": "edX", "www.edx.org": "edX", "verify.nptel.ac.in": "NPTEL", "nptel.ac.in": "NPTEL",
    "credential.net": "Credential.net", "www.credential.net": "Credential.net", "pythoninstitute.org": "Python Institute",
    "www.pythoninstitute.org": "Python Institute", "verify.skilljar.com": "Skilljar", "www.kaggle.com": "Kaggle",
}

MAX_TEXT = 4000
MAX_CODE = 20000


class EvidenceError(Exception):
    pass


# ---------------------------------------------------------------------------
# network (single choke point so tests can mock it)
# ---------------------------------------------------------------------------

def http_get(url: str, accept="application/json"):
    """GET with timeout and size cap. Raises on any failure. Only called with URLs WE construct
    (GitHub API) or https URLs on the certificate-issuer allow-list."""
    headers = {"User-Agent": "SkillTwin-Verifier/1.0", "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token and urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=C.CONFIG["evidence"]["http_timeout_s"]) as r:
        return r.status, r.read(600_000).decode("utf-8", "replace")


def _get_json(url):
    status, body = http_get(url)
    return json.loads(body)


# ---------------------------------------------------------------------------
# relevance helpers
# ---------------------------------------------------------------------------

def _text_relevance(skill: str, text: str) -> float:
    sig = SKILL_SIGNALS.get(skill, {"keywords": [skill]})
    t = (text or "").lower()
    hits = sum(1 for k in set(sig["keywords"] + [skill]) if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", t))
    return min(1.0, hits / 2.0) if hits else 0.0


def _result(status, strength, relevance, checks, limitations, title=None, extra=None):
    return {"status": status, "strength": round(max(0.0, min(1.0, strength)), 4),
            "relevance": round(max(0.0, min(1.0, relevance)), 4), "checks": checks, "limitations": limitations,
            "title": title, "extra": extra or {}}


def _provided(skill, text, checks, why):
    """Unverifiable: counts only at provided_factor of its text relevance."""
    rel = _text_relevance(skill, text)
    f = C.CONFIG["evidence"]["provided_factor"]
    checks = checks + [{"check": why, "ok": False}]
    return _result("provided", rel * f, rel, checks,
                   "Recorded but not machine-verified; counts at %d%% of its potential value." % round(f * 100))


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

GH_RE = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/.*)?$")


def parse_github(url: str):
    m = GH_RE.match((url or "").strip())
    return (m.group(1), m.group(2)) if m else None


def verify_github(skill, url, description, github_username=None):
    parsed = parse_github(url)
    if not parsed:
        return _provided(skill, description, [{"check": "URL is a github.com/<owner>/<repo> link", "ok": False}],
                         "could not parse a repository from the URL")
    owner, repo = parsed
    g = C.CONFIG["evidence"]["github"]
    checks = [{"check": "URL is a github.com/<owner>/<repo> link (%s/%s)" % (owner, repo), "ok": True}]
    try:
        meta = _get_json("https://api.github.com/repos/%s/%s" % (owner, repo))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return _result("provided", 0.0, 0.0, checks + [{"check": "repository exists and is public", "ok": False}],
                           "GitHub reports that this repository does not exist or is private.")
        return _provided(skill, description, checks, "GitHub API unavailable (HTTP %s) - could not verify" % e.code)
    except Exception as e:  # noqa: BLE001 - network failure of any kind
        return _provided(skill, description, checks, "GitHub could not be reached (%s) - could not verify" % type(e).__name__)
    checks.append({"check": "repository exists and is public", "ok": True})
    try:
        langs = _get_json("https://api.github.com/repos/%s/%s/languages" % (owner, repo)) or {}
    except Exception:  # noqa: BLE001
        langs = {}
    sig = SKILL_SIGNALS.get(skill, {"languages": [], "keywords": [skill]})
    total = sum(langs.values()) or 0
    skill_bytes = sum(b for l, b in langs.items() if l in sig["languages"])
    text_blob = " ".join([meta.get("description") or "", " ".join(meta.get("topics") or []), meta.get("name") or ""])
    try:
        rd = _get_json("https://api.github.com/repos/%s/%s/readme" % (owner, repo))
        text_blob += " " + base64.b64decode(rd.get("content", "")).decode("utf-8", "replace")[:6000]
    except Exception:  # noqa: BLE001
        pass
    if sig["languages"]:
        share = (skill_bytes / total) if total else 0.0
        relevance = min(1.0, share / g["full_relevance_share"])
        checks.append({"check": "%s code share is %d%% of the repository (%s bytes)" % (skill, round(100 * share), skill_bytes),
                       "ok": relevance >= 0.3})
        substance = min(1.0, skill_bytes / g["full_substance_bytes"])
    else:
        relevance = _text_relevance(skill, text_blob)
        checks.append({"check": "repository description/topics/README mention '%s'" % skill, "ok": relevance > 0})
        substance = min(1.0, (meta.get("size") or 0) / 500.0)
    checks.append({"check": "contains substantial %s content" % skill, "ok": substance >= 0.3})
    originality = g["fork_factor"] if meta.get("fork") else 1.0
    checks.append({"check": "original repository (not a fork)", "ok": not meta.get("fork")})
    recency = 1.0
    pushed = meta.get("pushed_at")
    if pushed:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days
            recency = g["stale_factor"] if age > g["stale_after_days"] else 1.0
            checks.append({"check": "updated within the last %d days" % g["stale_after_days"], "ok": age <= g["stale_after_days"]})
        except ValueError:
            pass
    strength = (g["relevance"] * relevance + g["substance"] * substance + g["originality"] * originality +
                g["recency"] * recency)
    # a repo with no relevant content must not earn "originality/recency" points
    strength *= min(1.0, relevance * 2) if relevance < 0.3 else 1.0
    if github_username:
        if github_username.lower() != owner.lower():
            strength *= g["owner_mismatch_factor"]
            checks.append({"check": "repository owner matches your GitHub username (%s)" % github_username, "ok": False})
        else:
            checks.append({"check": "repository owner matches your GitHub username (%s)" % github_username, "ok": True})
    status = "verified" if relevance >= 0.3 else "provided"
    return _result(status, strength, relevance, checks,
                   "Existence and content were checked via the GitHub API. Authorship is not proven (no login/ownership "
                   "challenge in this prototype).", title="%s/%s" % (owner, repo),
                   extra={"languages": langs, "stars": meta.get("stargazers_count"), "fork": meta.get("fork")})


# ---------------------------------------------------------------------------
# Certification / coursework with a URL on a known issuer
# ---------------------------------------------------------------------------

def verify_credential_url(skill, title, url, description):
    text = " ".join([title or "", description or ""])
    u = urlparse((url or "").strip())
    checks = []
    if not url:
        return _provided(skill, text, checks, "no credential URL supplied")
    if u.scheme != "https" or not u.hostname:
        return _provided(skill, text, checks, "credential link must be an https URL")
    issuer = CERT_ISSUER_DOMAINS.get(u.hostname.lower())
    checks.append({"check": "link is on a recognised credential host (%s)" % (issuer or u.hostname), "ok": bool(issuer)})
    if not issuer:
        return _provided(skill, text, checks, "host is not on the recognised-issuer list - not fetched")
    try:
        status, body = http_get(url, accept="text/html")
    except Exception as e:  # noqa: BLE001
        return _provided(skill, text, checks, "credential page could not be fetched (%s)" % type(e).__name__)
    checks.append({"check": "credential page is reachable (HTTP %s)" % status, "ok": status == 200})
    page_rel = _text_relevance(skill, body[:200000])
    checks.append({"check": "page content mentions '%s'" % skill, "ok": page_rel > 0})
    if status == 200 and page_rel > 0:
        return _result("verified", 0.6 + 0.4 * page_rel, max(page_rel, _text_relevance(skill, text)), checks,
                       "Page existence and topic were checked. The page is not matched to your identity, so authorship is not proven.",
                       extra={"issuer": issuer})
    return _provided(skill, text, checks, "page did not clearly relate to the skill")


# ---------------------------------------------------------------------------
# Work sample (pasted source) - static analysis
# ---------------------------------------------------------------------------

def analyse_python(source: str) -> dict:
    tree = ast.parse(source)
    f = {"functions": 0, "classes": 0, "comprehensions": 0, "try_except": 0, "with_blocks": 0, "decorators": 0,
         "generators": 0, "type_hints": 0, "docstrings": 0, "asserts_or_tests": 0, "recursion": 0, "imports": set()}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            f["functions"] += 1
            f["decorators"] += len(n.decorator_list)
            f["type_hints"] += bool(n.returns) + sum(1 for a in n.args.args if a.annotation)
            f["docstrings"] += bool(ast.get_docstring(n))
            if n.name.startswith("test"):
                f["asserts_or_tests"] += 1
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == n.name for c in ast.walk(n)):
                f["recursion"] += 1
        elif isinstance(n, ast.ClassDef):
            f["classes"] += 1
            f["docstrings"] += bool(ast.get_docstring(n))
        elif isinstance(n, (ast.ListComp, ast.DictComp, ast.SetComp)):
            f["comprehensions"] += 1
        elif isinstance(n, ast.GeneratorExp):
            f["generators"] += 1
        elif isinstance(n, (ast.Yield, ast.YieldFrom)):
            f["generators"] += 1
        elif isinstance(n, ast.Try):
            f["try_except"] += 1
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            f["with_blocks"] += 1
        elif isinstance(n, ast.Assert):
            f["asserts_or_tests"] += 1
        elif isinstance(n, ast.Import):
            f["imports"].update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            f["imports"].add(n.module.split(".")[0])
    loc = sum(1 for l in source.splitlines() if l.strip() and not l.strip().startswith("#"))
    f["imports"] = sorted(f["imports"])
    f["loc"] = loc
    return f


FEATURE_KEYS = ["functions", "classes", "comprehensions", "try_except", "with_blocks", "decorators", "generators",
                "type_hints", "docstrings", "asserts_or_tests", "recursion"]


def verify_work_sample(skill, title, code, description):
    text = " ".join([title or "", description or ""])
    if not code or not code.strip():
        return _provided(skill, text, [], "no source code pasted")
    if skill != "python":
        return _provided(skill, text + " " + code[:2000], [], "automatic code analysis is only implemented for Python")
    try:
        f = analyse_python(code)
    except SyntaxError as e:
        return _result("provided", 0.0, 0.0, [{"check": "sample parses as valid Python", "ok": False}],
                       "SyntaxError on line %s: %s" % (e.lineno, e.msg))
    w = C.CONFIG["evidence"]["work_sample"]
    present = [k for k in FEATURE_KEYS if f[k]]
    diversity = min(1.0, len(present) / w["feature_target"])
    size = min(1.0, f["loc"] / w["full_loc"])
    has_logic = f["functions"] + f["classes"] > 0
    strength = (w["feature_weight"] * diversity + w["size_weight"] * size) * (1.0 if has_logic else 0.3)
    checks = [{"check": "sample parses as valid Python", "ok": True},
              {"check": "defines functions/classes (%d functions, %d classes)" % (f["functions"], f["classes"]), "ok": has_logic},
              {"check": "%d lines of code" % f["loc"], "ok": size >= 0.3},
              {"check": "uses %d distinct language features: %s" % (len(present), ", ".join(present) or "none"),
               "ok": diversity >= 0.3}]
    return _result("verified", strength, 1.0 if has_logic else 0.3, checks,
                   "Static analysis of the pasted code only. Copying someone else's code cannot be detected, so authorship is not proven.",
                   extra={"features": {k: f[k] for k in FEATURE_KEYS}, "imports": f["imports"], "loc": f["loc"]})


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def evaluate(skill, etype, title, url, description, code, github_username=None):
    if etype not in EVIDENCE_TYPES:
        raise EvidenceError("type must be one of: " + ", ".join(EVIDENCE_TYPES))
    title = (title or "").strip()[:200]
    description = (description or "").strip()[:MAX_TEXT]
    url = (url or "").strip()[:500]
    code = (code or "")[:MAX_CODE]
    if not title:
        raise EvidenceError("Please give the evidence a title.")
    text = title + " " + description
    gh = parse_github(url) if url else None
    if etype == "github" or (etype == "project" and gh):
        res = verify_github(skill, url, text, github_username)
    elif etype == "work_sample":
        res = verify_work_sample(skill, title, code, description)
    elif etype in ("certification", "coursework") and url:
        res = verify_credential_url(skill, title, url, description)
    else:
        res = _provided(skill, text, [], "no verifiable link or code supplied")
    # the headline strength already includes the provided discount for unverifiable items
    return {**res, "title": title, "url": url, "description": description}
