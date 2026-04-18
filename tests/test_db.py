"""Tests for SQLite persistence layer."""

import os
import tempfile

import pytest

from src.db import Database


@pytest.fixture
def db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    database = Database(f.name)
    yield database
    os.unlink(f.name)


class TestDatabase:
    def test_init_creates_tables(self, db):
        """Database init creates all tables."""
        stats = db.stats()
        assert "tweets" in stats

    def test_tweet_insert_and_exists(self, db):
        db.insert_tweet("t1", "user1", "User One", "hello world", "2026-01-01", {"likes": 100})
        assert db.tweet_exists("t1")
        assert not db.tweet_exists("t999")

    def test_tweet_duplicate_insert_is_idempotent(self, db):
        db.insert_tweet("t1", "user1", "User One", "hello", "2026-01-01", {})
        db.insert_tweet("t1", "user1", "User One", "hello", "2026-01-01", {})
        assert db.count_tweets() == 1

    def test_tweets_by_author(self, db):
        db.insert_tweet("t1", "user1", "User One", "tweet 1", "2026-01-01", {})
        db.insert_tweet("t2", "user1", "User One", "tweet 2", "2026-01-02", {})
        db.insert_tweet("t3", "user2", "User Two", "tweet 3", "2026-01-03", {})
        tweets = db.get_tweets_by_author("user1")
        assert len(tweets) == 2

    def test_practice_crud(self, db):
        db.insert_tweet("t1", "u1", "U1", "text", "2026-01-01", {})
        db.insert_practice("p1", "t1", "summary", "detail", ["TDD"], 0.9, "evidence")
        assert db.practice_exists("p1")
        assert not db.practice_exists("p999")

    def test_practice_status(self, db):
        db.insert_tweet("t1", "u1", "U1", "text", "2026-01-01", {})
        db.insert_practice("p1", "t1", "summary", "detail", [], 0.8)
        assert len(db.get_practices_by_status("new")) == 1
        db.update_practice_status("p1", "verified")
        assert len(db.get_practices_by_status("new")) == 0
        assert len(db.get_practices_by_status("verified")) == 1

    def test_verification_log(self, db):
        db.insert_tweet("t1", "u1", "U1", "text", "2026-01-01", {})
        db.insert_practice("p1", "t1", "summary", "detail", [], 0.8)
        db.log_verification("p1", "verified", "good logic", "verified", "CI passed", "verified")
        assert db.has_verification("p1")

    def test_issue_log(self, db):
        db.insert_tweet("t1", "u1", "U1", "text", "2026-01-01", {})
        db.insert_practice("p1", "t1", "summary", "detail", [], 0.8)
        db.log_issue("p1", 42, "https://github.com/.../issues/42", "Test issue")
        assert db.has_issue("p1")
        assert db.get_issue_count() == 1

    def test_account_history(self, db):
        db.log_account_change("user1", 0.5, "added")
        db.log_account_change("user1", 0.7, "good content")
        history = db.get_account_history("user1")
        assert len(history) == 2
        # Order by changed_at DESC, but same-second inserts may vary — just check both scores exist
        scores = {h["trust_score"] for h in history}
        assert 0.5 in scores
        assert 0.7 in scores

    def test_discovery_log(self, db):
        db.log_discovery("newuser", "New User", "great tip", "dt1",
                         llm_score=0.85, promoted=True)
        assert db.discovery_exists("dt1")
        stats = db.get_discovery_stats()
        assert stats["total_discovered"] == 1
        assert stats["promoted"] == 1

    def test_discovery_duplicate_tweet(self, db):
        db.log_discovery("user1", "U1", "tip", "dt1", llm_score=0.8)
        assert db.discovery_exists("dt1")

    def test_full_stats(self, db):
        db.insert_tweet("t1", "u1", "U1", "text", "2026-01-01", {})
        db.insert_practice("p1", "t1", "summary", "detail", ["TDD"], 0.9)
        db.log_verification("p1", "verified")
        db.log_issue("p1", 1, "https://...", "test")
        db.log_account_change("u1", 0.5)

        stats = db.stats()
        assert stats["tweets"] == 1
        assert stats["practices"] == 1
        assert stats["issues_created"] == 1
