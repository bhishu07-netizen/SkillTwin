"""
SQLite storage for SkillTwin (candidates + the verification entities).

Entities (spec STEP 12): User (candidates), Skill, SkillClaim, Assessment, Question,
AssessmentAttempt, Answer, Evidence, SkillVerificationResult.
"""
import json
import secrets
import sqlite3
import time
from pathlib import Path

from flask import g

DB_PATH = Path(__file__).resolve().parent.parent / "skilltwin.db"


def now() -> float:
    """Single clock for the whole engine (tests monkeypatch this)."""
    return time.time()


def set_db_path(path):
    global DB_PATH
    DB_PATH = Path(path)


def connect():
    # autocommit mode: multi-statement operations opt in via tx() below (BEGIN IMMEDIATE),
    # which serialises concurrent writers (e.g. a double-submitted answer).
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    skills_json TEXT NOT NULL DEFAULT '{}',
    name TEXT,
    github_username TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS readiness_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    trigger TEXT NOT NULL,
    signature TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    fits_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_cand ON readiness_snapshots(candidate_id, id);
CREATE TABLE IF NOT EXISTS projections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    learn_json TEXT NOT NULL,
    to_learn_json TEXT NOT NULL,
    fit_before REAL NOT NULL,
    fit_projected REAL NOT NULL,
    created_at REAL NOT NULL,
    resolved_at REAL,
    fit_actual REAL,
    snapshot_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_proj_cand ON projections(candidate_id, role);
CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY,
    assessable INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS skill_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    claimed_level TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(candidate_id, skill)
);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    skill TEXT NOT NULL,
    category TEXT NOT NULL,
    concept TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    skill TEXT NOT NULL,
    claimed_level TEXT NOT NULL,
    variant_seed TEXT NOT NULL,
    time_limit_s INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assessment_attempts (
    id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL REFERENCES assessments(id),
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    claimed_level TEXT NOT NULL,
    status TEXT NOT NULL,                -- in_progress | completed | expired | abandoned
    started_at REAL NOT NULL,
    deadline REAL NOT NULL,
    completed_at REAL,
    duration_s REAL,
    state_json TEXT NOT NULL,
    answered_count INTEGER NOT NULL DEFAULT 0,
    assessment_score REAL,
    stop_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempt_cand ON assessment_attempts(candidate_id, skill);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id),
    position INTEGER NOT NULL,
    difficulty TEXT NOT NULL,
    category TEXT NOT NULL,
    concept TEXT NOT NULL,
    served_at REAL NOT NULL,
    answered_at REAL NOT NULL,
    time_taken_s REAL NOT NULL,
    candidate_answer TEXT,
    expected_answer TEXT,
    is_correct INTEGER NOT NULL,
    score REAL NOT NULL,
    details_json TEXT,
    client_meta_json TEXT,
    selection_reason TEXT,
    UNIQUE(attempt_id, question_id)
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    description TEXT,
    status TEXT NOT NULL,                -- provided | verified | unverifiable
    strength REAL NOT NULL,
    relevance REAL NOT NULL,
    checks_json TEXT NOT NULL,
    limitations TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_cand ON evidence(candidate_id, skill);
CREATE TABLE IF NOT EXISTS verification_results (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    claimed_level TEXT NOT NULL,
    demonstrated_level TEXT NOT NULL,
    assessment_score REAL NOT NULL,
    evidence_score REAL NOT NULL,
    verified_evidence_score REAL NOT NULL,
    consistency_score REAL NOT NULL,
    confidence REAL NOT NULL,
    badge TEXT NOT NULL,
    discrepancy_json TEXT NOT NULL,
    breakdown_json TEXT NOT NULL,
    weaknesses_json TEXT NOT NULL,
    integrity_json TEXT NOT NULL,
    evidence_summary_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_result_cand ON verification_results(candidate_id, skill);
"""


def _ensure_columns(conn):
    """Migrate databases created by the pre-verification backend."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(candidates)")}
    for col in ("name", "github_username"):
        if col not in cols:
            conn.execute("ALTER TABLE candidates ADD COLUMN %s TEXT" % col)


def init_db(taxonomy=None):
    from .bank import questions_for, supported_skills

    conn = connect()
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    # secret used to mint opaque per-attempt option tokens
    if not conn.execute("SELECT 1 FROM meta WHERE key='option_secret'").fetchone():
        conn.execute("INSERT INTO meta VALUES ('option_secret', ?)", (secrets.token_hex(32),))
    assessable = set(supported_skills())
    for name in (taxonomy or []):
        conn.execute("INSERT INTO skills(name, assessable) VALUES (?,?) "
                     "ON CONFLICT(name) DO UPDATE SET assessable=excluded.assessable",
                     (name, 1 if name in assessable else 0))
    # sync the question bank into the questions table (answer key stays server-side)
    for skill in assessable:
        for q in questions_for(skill):
            payload = {k: v for k, v in q.items()
                       if k not in ("id", "skill", "category", "concept", "difficulty", "type", "prompt")}
            conn.execute(
                "INSERT INTO questions(id, skill, category, concept, difficulty, type, prompt, payload_json) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET prompt=excluded.prompt, "
                "payload_json=excluded.payload_json, category=excluded.category, concept=excluded.concept, "
                "difficulty=excluded.difficulty, type=excluded.type",
                (q["id"], q["skill"], q["category"], q["concept"], q["difficulty"], q["type"], q["prompt"],
                 json.dumps(payload)))
    conn.commit()
    conn.close()


class tx:
    """with tx(db): ...  -> BEGIN IMMEDIATE ... COMMIT (ROLLBACK on error)."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        self.db.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def option_secret(db) -> str:
    return db.execute("SELECT value FROM meta WHERE key='option_secret'").fetchone()["value"]


def jloads(s, default=None):
    if s is None or s == "":
        return default
    return json.loads(s)
