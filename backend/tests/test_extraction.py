import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa: E402


def test_whole_word_matching():
    assert "machine learning" not in core.extract_skills("Built an HTML and CSS website")
    assert "r" not in core.extract_skills("Worked in R&D")
    assert "r" in core.extract_skills("R programming for stats")


def test_negation_is_not_a_claim():
    assert core.extract_skills("I have never used Python or SQL") == {}
    r = core.extract_skills("Not experienced with AWS, but strong in statistics")
    assert "aws" not in r and r["statistics"] == 1.0


def test_level_cues_are_local():
    r = core.extract_skills("Advanced Python, basic SQL; familiar with Docker")
    assert r == {"python": 1.0, "sql": 0.4, "docker": 0.4}
    assert core.extract_skills("Machine learning (ML), deep learning")["machine learning"] == 0.7


def test_extracted_levels_are_only_claims():
    r = core.extract_skills("python")
    assert r == {"python": 0.7}
