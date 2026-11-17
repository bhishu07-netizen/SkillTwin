"""
Question-bank registry.

To add a skill, create `<skill>_bank.py` exposing SKILL, QUESTIONS and
CONCEPT_ADVICE (same shape as python_bank.py), import it below, and run
tests/test_bank.py - it proves every question is answerable and every
unit-test suite discriminates between right and wrong solutions.

Skills without a bank are reported as "assessment not available yet"; the
engine never fabricates questions for them (LLM-drafted questions would need a
human-reviewed answer key before they could be served).
"""
from . import python_bank, sql_bank

_BANKS = {
    python_bank.SKILL: {"questions": python_bank.QUESTIONS, "advice": python_bank.CONCEPT_ADVICE},
    sql_bank.SKILL: {"questions": sql_bank.QUESTIONS, "advice": sql_bank.CONCEPT_ADVICE},
}

_BY_ID = {q["id"]: q for b in _BANKS.values() for q in b["questions"]}

DIFFICULTIES = ["easy", "medium", "hard"]


def supported_skills():
    return sorted(_BANKS)


def is_supported(skill: str) -> bool:
    return skill in _BANKS


def questions_for(skill: str):
    return _BANKS[skill]["questions"]


def advice_for(skill: str):
    return _BANKS[skill]["advice"]


def get_question(qid: str):
    return _BY_ID[qid]


def bank_stats(skill: str) -> dict:
    qs = questions_for(skill)
    by_diff = {d: sum(1 for q in qs if q["difficulty"] == d) for d in DIFFICULTIES}
    cats = sorted({q["category"] for q in qs})
    return {"total": len(qs), "by_difficulty": by_diff, "categories": cats}
