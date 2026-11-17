"""Single place that talks to an LLM. The key comes only from the environment (GEMINI_API_KEY) and is never
returned to a client or logged. Every caller must treat the result as optional wording: engines never depend on it."""
import hashlib
import json
import os
import time
import urllib.error
import ssl
import urllib.request
from pathlib import Path



def _ssl_context():
    """Mac python.org builds ship without CA certs (CERTIFICATE_VERIFY_FAILED). Prefer certifi's bundle when present;
    verification is never disabled."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

def _load_dotenv():
    """Tiny .env loader (no extra dependency). Looks for backend/.env then the project-root .env.
    Real environment variables always win; the key is never printed or returned to a client."""
    here = Path(__file__).resolve().parent
    for f in (here / ".env", here.parent / ".env"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass


_load_dotenv()


_last_error = {"msg": None}
_last_model = {"name": None}
DEFAULT_MODEL = "gemini-3.6-flash"
# tried in this order when the configured model is missing (404), over its quota (429) or overloaded (503).
# Each model has its own quota, so a lighter model often still answers when the first one is exhausted.
FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
RETRY_WITH_NEXT_MODEL = (404, 429, 503)
COOLDOWN_S = 60          # a model that just said "quota" is skipped for this long, so later requests are not slowed down
CACHE_TTL_S = 600        # identical prompts within 10 minutes reuse the earlier answer and spend no quota
CACHE_MAX = 200
_cooldown = {}           # model -> unix time until which it is skipped
_cache = {}              # sha256(prompt) -> (expires_at, text, model)


def _norm(name):
    """Accepts what people actually type ('Gemini 3.6 Flash', 'models/gemini-3.6-flash', '3.6 flash') and returns the API id."""
    n = (name or "").strip().strip('"').strip("'").strip().lower()
    if n.startswith("models/"):
        n = n[7:]
    n = "-".join(n.replace("_", " ").split())
    if n and n[0].isdigit():
        n = "gemini-" + n
    return n


def _key():
    # tolerate stray spaces / quotes / newlines pasted into .env or a dashboard
    return (os.environ.get("GEMINI_API_KEY") or "").strip().strip('"').strip("'").strip()


def configured():
    return bool(_key())


def model_name():
    return _norm(os.environ.get("GEMINI_MODEL")) or DEFAULT_MODEL


def last_model():
    """The model that produced the most recent answer (differs from model_name() only after a fallback)."""
    return _last_model["name"] or model_name()


def last_error():
    """Short, key-free reason for the most recent failure (shown to the operator, never contains the key)."""
    return _last_error["msg"]


def _call(model, prompt, key, timeout):
    base = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models")
    req = urllib.request.Request("%s/%s:generateContent" % (base, model),
                                 data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        data = json.loads(r.read())
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "empty response"
        raise ValueError("Gemini returned no answer (%s)" % reason)
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise ValueError("Gemini returned empty text (finishReason=%s)" % cands[0].get("finishReason"))
    return text


def _describe(e):
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        hint = {400: "bad request or invalid API key", 403: "key not allowed / API not enabled", 404: "model not found",
                429: "quota or rate limit exceeded"}.get(e.code, "")
        return ("HTTP %s %s %s" % (e.code, hint, detail[:160])).strip()
    return "%s: %s" % (type(e).__name__, str(e)[:160])


def generate(prompt, timeout=25, max_chars=6000, cache=True):
    """Returns generated text or None on missing key / any failure. The reason is kept in last_error().
    Quota-friendly: identical prompts are cached for a few minutes (cache=False to bypass), and a model that
    just returned HTTP 429 is skipped for COOLDOWN_S seconds."""
    key = _key()
    if not key:
        _last_error["msg"] = "GEMINI_API_KEY is not set on the server"
        return None
    if not isinstance(prompt, str) or len(prompt) > 20000:
        return None
    now = time.time()
    ck = hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()
    if cache and ck in _cache and _cache[ck][0] > now:
        _last_error["msg"] = None
        _last_model["name"] = _cache[ck][2]
        return _cache[ck][1][:max_chars]
    models = [model_name()] + [m for m in FALLBACK_MODELS if m != model_name()]
    ready = [m for m in models if _cooldown.get(m, 0) <= now]
    for m in (ready or models):          # if every model is cooling down, try them all anyway
        try:
            text = _call(m, prompt, key, timeout)[:max_chars]
            _last_error["msg"] = None
            _last_model["name"] = m
            if cache:
                if len(_cache) >= CACHE_MAX:
                    _cache.clear()
                _cache[ck] = (now + CACHE_TTL_S, text, m)
            return text
        except urllib.error.HTTPError as e:
            _last_error["msg"] = "model %s: %s" % (m, _describe(e))
            if e.code == 429:
                _cooldown[m] = time.time() + COOLDOWN_S
            if e.code not in RETRY_WITH_NEXT_MODEL:   # e.g. 400/403 (bad key) will not improve with another model
                return None
        except Exception as e:  # noqa: BLE001 - network/format errors degrade to "no AI wording"
            _last_error["msg"] = "model %s: %s" % (m, _describe(e))
            return None
    return None
