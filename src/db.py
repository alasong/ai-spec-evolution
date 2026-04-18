"""SQLite persistence layer — single source of truth for all runtime data."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tweets (
    id              TEXT PRIMARY KEY,
    author_handle   TEXT NOT NULL,
    author_name     TEXT NOT NULL,
    text            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    metrics         TEXT NOT NULL DEFAULT '{}',
    source          TEXT NOT NULL DEFAULT 'collection',  -- collection | discovery | mock
    ingested_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS practices (
    id                  TEXT PRIMARY KEY,
    tweet_id            TEXT NOT NULL REFERENCES tweets(id),
    summary             TEXT NOT NULL,
    detail              TEXT NOT NULL,
    tags                TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.0,
    evidence            TEXT NOT NULL DEFAULT '',
    suggested_doc       TEXT NOT NULL DEFAULT '',
    suggested_section   TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'new',  -- new | deduped | verified | rejected | issued
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS verification_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id     TEXT NOT NULL REFERENCES practices(id),
    logic_verdict   TEXT NOT NULL,
    logic_reasoning TEXT NOT NULL DEFAULT '',
    project_verdict TEXT,
    project_evidence TEXT NOT NULL DEFAULT '',
    final_verdict   TEXT NOT NULL DEFAULT 'pending',
    verified_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS issue_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id     TEXT NOT NULL REFERENCES practices(id),
    github_issue_id INTEGER,
    github_url      TEXT,
    title           TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS account_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL,
    trust_score     REAL NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    changed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS discovery_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL,
    name            TEXT NOT NULL,
    tweet_text      TEXT NOT NULL,
    tweet_id        TEXT NOT NULL,
    keyword_matched TEXT NOT NULL DEFAULT '',
    likes           INTEGER NOT NULL DEFAULT 0,
    retweets        INTEGER NOT NULL DEFAULT 0,
    llm_score       REAL NOT NULL DEFAULT 0.0,
    llm_reason      TEXT NOT NULL DEFAULT '',
    expertise       TEXT NOT NULL DEFAULT '[]',
    promoted        INTEGER NOT NULL DEFAULT 0,
    discovered_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tweets_author ON tweets(author_handle);
CREATE INDEX IF NOT EXISTS idx_practices_status ON practices(status);
CREATE INDEX IF NOT EXISTS idx_verification_practice ON verification_log(practice_id);
CREATE INDEX IF NOT EXISTS idx_issue_practice ON issue_log(practice_id);
CREATE INDEX IF NOT EXISTS idx_account_history_handle ON account_history(handle);
CREATE INDEX IF NOT EXISTS idx_discovery_handle ON discovery_log(handle);
"""


class Database:
    """SQLite-backed persistence for the spec evolution pipeline."""

    def __init__(self, db_path: str = "data/spec_evolution.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
        logger.info("Database initialized at %s", self.db_path)

    # ─── Tweets ───────────────────────────────────────────────────────

    def tweet_exists(self, tweet_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM tweets WHERE id = ?", (tweet_id,)).fetchone()
            return row is not None

    def insert_tweet(self, tweet_id: str, author_handle: str, author_name: str,
                     text: str, created_at: str, metrics: dict, source: str = "collection") -> None:
        if self.tweet_exists(tweet_id):
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO tweets (id, author_handle, author_name, text, created_at, metrics, source) VALUES (?,?,?,?,?,?,?)",
                (tweet_id, author_handle, author_name, text, created_at, json.dumps(metrics), source),
            )

    def get_tweets_by_author(self, handle: str, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tweets WHERE author_handle = ? ORDER BY created_at DESC LIMIT ?",
                (handle, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def count_tweets(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]

    # ─── Practices ────────────────────────────────────────────────────

    def insert_practice(self, practice_id: str, tweet_id: str, summary: str,
                        detail: str, tags: list, confidence: float,
                        evidence: str = "", suggested_doc: str = "",
                        suggested_section: str = "") -> None:
        if self.practice_exists(practice_id):
            return
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO practices
                   (id, tweet_id, summary, detail, tags, confidence, evidence, suggested_doc, suggested_section)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (practice_id, tweet_id, summary, detail, json.dumps(tags),
                 confidence, evidence, suggested_doc, suggested_section),
            )

    def practice_exists(self, practice_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute("SELECT 1 FROM practices WHERE id = ?", (practice_id,)).fetchone() is not None

    def update_practice_status(self, practice_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE practices SET status = ? WHERE id = ?", (status, practice_id))

    def get_practices_by_status(self, status: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM practices WHERE status = ? ORDER BY created_at DESC", (status,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Verification ─────────────────────────────────────────────────

    def log_verification(self, practice_id: str, logic_verdict: str,
                         logic_reasoning: str = "", project_verdict: str | None = None,
                         project_evidence: str = "", final_verdict: str = "pending") -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO verification_log
                   (practice_id, logic_verdict, logic_reasoning, project_verdict, project_evidence, final_verdict)
                   VALUES (?,?,?,?,?,?)""",
                (practice_id, logic_verdict, logic_reasoning,
                 project_verdict, project_evidence, final_verdict),
            )

    def has_verification(self, practice_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM verification_log WHERE practice_id = ?", (practice_id,),
            ).fetchone() is not None

    # ─── Issues ───────────────────────────────────────────────────────

    def log_issue(self, practice_id: str, github_issue_id: int,
                  github_url: str, title: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO issue_log (practice_id, github_issue_id, github_url, title) VALUES (?,?,?,?)",
                (practice_id, github_issue_id, github_url, title),
            )

    def has_issue(self, practice_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM issue_log WHERE practice_id = ?", (practice_id,),
            ).fetchone() is not None

    def get_issue_count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM issue_log").fetchone()[0]

    # ─── Account History ──────────────────────────────────────────────

    def log_account_change(self, handle: str, trust_score: float, reason: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO account_history (handle, trust_score, reason) VALUES (?,?,?)",
                (handle, trust_score, reason),
            )

    def get_account_history(self, handle: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM account_history WHERE handle = ? ORDER BY changed_at DESC",
                (handle,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Discovery ────────────────────────────────────────────────────

    def log_discovery(self, handle: str, name: str, tweet_text: str, tweet_id: str,
                      keyword_matched: str = "", likes: int = 0, retweets: int = 0,
                      llm_score: float = 0.0, llm_reason: str = "",
                      expertise: list | None = None, promoted: bool = False) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO discovery_log
                   (handle, name, tweet_text, tweet_id, keyword_matched, likes, retweets,
                    llm_score, llm_reason, expertise, promoted)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (handle, name, tweet_text, tweet_id, keyword_matched, likes, retweets,
                 llm_score, llm_reason, json.dumps(expertise or []), int(promoted)),
            )

    def discovery_exists(self, tweet_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM discovery_log WHERE tweet_id = ?", (tweet_id,),
            ).fetchone() is not None

    def get_discovery_stats(self) -> dict:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM discovery_log").fetchone()[0]
            promoted = conn.execute(
                "SELECT COUNT(*) FROM discovery_log WHERE promoted = 1",
            ).fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(llm_score) FROM discovery_log",
            ).fetchone()[0] or 0.0
            return {"total_discovered": total, "promoted": promoted, "avg_llm_score": round(avg_score, 2)}

    # ─── Stats ────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self.connect() as conn:
            return {
                "tweets": conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0],
                "practices": conn.execute("SELECT COUNT(*) FROM practices").fetchone()[0],
                "practices_new": conn.execute(
                    "SELECT COUNT(*) FROM practices WHERE status = 'new'",
                ).fetchone()[0],
                "practices_verified": conn.execute(
                    "SELECT COUNT(*) FROM practices WHERE status = 'verified'",
                ).fetchone()[0],
                "issues_created": conn.execute("SELECT COUNT(*) FROM issue_log").fetchone()[0],
                "accounts_tracked": conn.execute(
                    "SELECT COUNT(DISTINCT handle) FROM account_history",
                ).fetchone()[0],
            }
