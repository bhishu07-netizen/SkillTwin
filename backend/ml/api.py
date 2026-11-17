"""HTTP API for the market ML models. The profile comes from the same place as every other engine (verified claims first)."""
from flask import Blueprint, jsonify, request

from career import data as D
from career.api import _err, _resolve
from . import model as M

bp = Blueprint("ml", __name__)


@bp.route("/api/ml/model-card")
def model_card():
    return jsonify(M.card_public())


@bp.route("/api/ml/market-outlook", methods=["POST"])
def market_outlook():
    body = request.get_json(force=True, silent=True) or {}
    exp = body.get("experience_years", 2)
    if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not 0 <= exp <= 30:
        return _err("experience_years must be a number from 0 to 30")
    r = _resolve({**body, "role": next(iter(D.ROLES))})
    if not isinstance(r, tuple) or len(r) != 4:
        return r
    _, profile, _, meta = r
    present = {s for s, p in profile.items() if p.get("units", 0) > 0}
    out = M.outlook(present, exp)
    out["profile_source"] = meta.get("source")
    out["model"] = M.summary()
    out["caveats"] = M.card()["limitations"][:3]
    return jsonify(out)
