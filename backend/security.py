"""
Route protection for the SkillTwin API.

* Candidate ownership: a candidate_id alone is NOT enough. POST /api/candidates (and /api/profile) returns a `token`
  (HMAC-SHA256 of the id under a per-database server secret); every candidate-scoped request must send it in the
  `X-Candidate-Token` header. Attempts/results are resolved to their owning candidate before the check.
* Rate limiting: in-memory sliding window per client IP (cheap routes vs expensive routes).
* CORS: same-origin by default; extra origins via SKILLTWIN_CORS_ORIGINS (comma separated). No wildcard.
* Errors: JSON everywhere, no stack traces; request bodies capped.
"""
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

from flask import jsonify, request

from verification import db as VDB

HEADER = "X-Candidate-Token"
HEAVY_PREFIXES = ("/api/verification/attempts", "/api/verification/evidence", "/api/career/copilot", "/api/ai/")
LIMITS = {"general": (600, 60.0), "heavy": (120, 60.0)}     # (requests, window seconds)

_secret_cache = {}


def _secret():
    key = str(VDB.DB_PATH)
    if key not in _secret_cache:
        conn = VDB.connect()
        row = conn.execute("SELECT value FROM meta WHERE key='auth_secret'").fetchone()
        if not row:
            conn.execute("INSERT OR IGNORE INTO meta VALUES ('auth_secret', ?)", (secrets.token_hex(32),))
            row = conn.execute("SELECT value FROM meta WHERE key='auth_secret'").fetchone()
        conn.close()
        _secret_cache[key] = row["value"]
    return _secret_cache[key]


def token_for(candidate_id):
    return hmac.new(_secret().encode(), str(candidate_id).encode(), hashlib.sha256).hexdigest()


def _candidate_ids():
    ids = set()
    va = request.view_args or {}
    for k in ("cid", "candidate_id"):
        if va.get(k):
            ids.add(va[k])
    if request.args.get("candidate_id"):
        ids.add(request.args["candidate_id"])
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        body = request.get_json(silent=True)
        if isinstance(body, dict) and body.get("candidate_id") is not None:
            ids.add(body["candidate_id"])
    db = VDB.get_db()
    if va.get("rid"):
        r = db.execute("SELECT candidate_id FROM verification_results WHERE id=?", (va["rid"],)).fetchone()
        ids.add(r["candidate_id"] if r else "__unknown__")
    if va.get("aid"):
        r = db.execute("SELECT candidate_id FROM assessment_attempts WHERE id=?", (va["aid"],)).fetchone()
        ids.add(r["candidate_id"] if r else "__unknown__")
    return {i for i in ids if isinstance(i, str)} | ({"__invalid__"} if any(not isinstance(i, str) for i in ids) else set())


class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)

    def allow(self, ip, bucket):
        limit, window = LIMITS[bucket]
        q = self.hits[(ip, bucket)]
        now = time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False, max(1, int(window - (now - q[0])))
        q.append(now)
        return True, 0


def install(app):
    limiter = RateLimiter()
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
    allowed = {o.strip() for o in os.environ.get("SKILLTWIN_CORS_ORIGINS", "").split(",") if o.strip()}

    @app.before_request
    def _guard():
        path = request.path
        if not path.startswith("/api/"):
            return None
        if request.method == "OPTIONS":      # CORS preflight: answered here (headers added in _cors)
            return "", 204
        bucket = "heavy" if request.method != "GET" and path.startswith(HEAVY_PREFIXES) else "general"
        ok, retry = limiter.allow(request.remote_addr or "?", bucket)
        if not ok:
            r = jsonify({"error": "Too many requests - please slow down.", "retry_after_s": retry})
            r.status_code = 429
            r.headers["Retry-After"] = str(retry)
            return r
        ids = _candidate_ids()
        if not ids:
            return None
        sent = request.headers.get(HEADER, "")
        for cid in ids:
            if cid.startswith("__") or not hmac.compare_digest(sent, token_for(cid)):
                r = jsonify({"error": "Missing or invalid candidate token (send it as %s)." % HEADER})
                r.status_code = 401
                return r
        return None

    @app.after_request
    def _cors(resp):
        origin = request.headers.get("Origin")
        if origin and (origin == request.host_url.rstrip("/") or origin in allowed):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, " + HEADER
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    def _json_error(code, msg):
        def handler(e):
            return jsonify({"error": msg}), code
        return handler

    app.register_error_handler(404, _json_error(404, "not found"))
    app.register_error_handler(405, _json_error(405, "method not allowed"))
    app.register_error_handler(413, _json_error(413, "request too large"))
    app.register_error_handler(500, _json_error(500, "internal error - the request could not be completed"))
