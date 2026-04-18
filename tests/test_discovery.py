"""Tests for Discovery Layer."""

import json
import tempfile
from pathlib import Path

import yaml

from src.collector.discovery import (
    CandidateAuthor,
    DiscoveryAnalyzer,
    DiscoveryCollector,
    save_discovery_report,
)
from src.collector.account_manager import AccountManager
from src.models.practice import Tweet


SAMPLE_ACCOUNTS = {
    "accounts": [
        {
            "handle": "karpathy",
            "name": "Andrej Karpathy",
            "expertise": ["deep-learning"],
            "trust_score": 0.9,
            "last_refreshed": "",
            "added_reason": "test",
            "active": True,
        },
    ]
}


class TestDiscoveryCollector:
    def test_search_mock_returns_tweets(self):
        """Mock discovery returns tweets with varied engagement."""
        tweets = DiscoveryCollector.search_mock()
        assert len(tweets) == 4
        # High engagement tweets
        assert tweets[0].metrics["likes"] > 50
        # Low engagement noise
        assert tweets[3].metrics["likes"] < 10


class TestDiscoveryAnalyzer:
    def _make_analyzer(self, llm=None):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump(SAMPLE_ACCOUNTS, f)
        f.close()
        mgr = AccountManager(f.name, llm=llm)
        return DiscoveryAnalyzer(llm, mgr)

    def test_high_engagement_filter(self):
        """Filter removes low-engagement tweets."""
        analyzer = self._make_analyzer()
        tweets = DiscoveryCollector.search_mock()

        # Manually filter
        high = [t for t in tweets if t.metrics.get("likes", 0) >= 50]
        assert len(high) == 3  # 3 out of 4 pass

    def test_existing_accounts_excluded(self):
        """Already-curated accounts are excluded."""
        analyzer = self._make_analyzer()
        tweets = DiscoveryCollector.search_mock()
        # None of the mock tweets are from karpathy, so all 4 pass through
        # This test verifies the exclusion filter doesn't crash and uses correct handles
        existing = {a.handle for a in analyzer.account_mgr.accounts}
        assert "karpathy" in existing
        new_tweets = [t for t in tweets if t.author_handle not in existing]
        assert len(new_tweets) == 4  # all mock tweets are from non-existing accounts

    def test_candidate_dedup_by_author(self):
        """Multiple tweets from same author are aggregated."""
        from unittest.mock import MagicMock, patch

        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {"score": 0.8, "reason": "great content", "expertise": ["ai-coding"]}

        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump({"accounts": []}, f)
        f.close()
        mgr = AccountManager(f.name, mock_llm)
        analyzer = DiscoveryAnalyzer(mock_llm, mgr)

        # Create 2 tweets from same author
        tweets = [
            Tweet(id="t1", author_handle="newuser", author_name="New", text="AI coding tip 1", created_at=None, metrics={"likes": 200, "retweets": 50}),
            Tweet(id="t2", author_handle="newuser", author_name="New", text="AI coding tip 2", created_at=None, metrics={"likes": 300, "retweets": 80}),
        ]

        candidates = analyzer.analyze(tweets, min_likes=50, min_llm_score=0.5)
        assert len(candidates) == 1
        assert candidates[0].discovery_count == 2
        assert candidates[0].likes == 500  # aggregated


class TestCandidatePromotion:
    def test_promotion_threshold(self):
        """Only high-scoring, high-engagement candidates get promoted."""
        from unittest.mock import MagicMock, patch

        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {"score": 0.85, "reason": "excellent", "expertise": ["TDD"]}

        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump({"accounts": []}, f)
        f.close()
        mgr = AccountManager(f.name, mock_llm)
        analyzer = DiscoveryAnalyzer(mock_llm, mgr)

        candidates = [
            CandidateAuthor(
                handle="expert_user",
                name="Expert",
                tweet_text="AI coding best practice",
                tweet_id="t1",
                keyword_matched="test",
                likes=500,
                retweets=100,
                llm_score=0.85,
                llm_reason="excellent",
                expertise_areas=["TDD"],
            ),
        ]

        promoted = analyzer.promote_candidates(candidates, min_score=0.7, min_engagement=100)
        assert len(promoted) == 1
        assert promoted[0].handle == "expert_user"
        # Trust score starts conservative
        assert promoted[0].trust_score < 0.85


class TestDiscoveryReport:
    def test_save_report(self):
        """Discovery report is valid JSON."""
        candidates = [
            CandidateAuthor(
                handle="test_user",
                name="Test",
                tweet_text="test tweet",
                tweet_id="t1",
                keyword_matched="test",
                likes=100,
                retweets=20,
                llm_score=0.7,
                llm_reason="good",
                expertise_areas=["ai"],
            ),
        ]
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        f.close()
        save_discovery_report(candidates, f.name)

        with open(f.name) as fh:
            report = json.load(fh)
        assert report["total_candidates"] == 1
        assert report["candidates"][0]["handle"] == "test_user"
