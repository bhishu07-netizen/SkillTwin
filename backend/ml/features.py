"""Turns posting text into the same 37 skill indicators the app uses, so training and the live app share one vocabulary."""
import re

from career import data as D

SKILLS = list(D.SKILLS)


def _pattern(skill):
    names = sorted({skill, *D.SKILLS[skill]["aliases"]}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9+#])(?:" + "|".join(re.escape(n.lower()) for n in names) + r")(?![a-z0-9+#])")


_PATTERNS = {s: _pattern(s) for s in SKILLS}


def skills_in_text(text):
    """Set of app skills mentioned in a posting's key-skills text (lower-cased, comma separated)."""
    t = (text or "").lower()
    return {s for s, p in _PATTERNS.items() if p.search(t)}


def parse_min_experience(text):
    """'3-8 yrs' -> 3.0 ; anything else -> None."""
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)", str(text or ""))
    return float(m.group(1)) if m else None
