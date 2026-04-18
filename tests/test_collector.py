"""Tests for Twitter collector and account manager."""

import tempfile
from datetime import datetime

import pytest
import yaml

from src.collector.twitter import TwitterCollector
from src.collector.account_manager import AccountManager
from src.models.practice import AccountEntry


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
        {
            "handle": "inactive_user",
            "name": "Inactive",
            "expertise": [],
            "trust_score": 0.5,
            "last_refreshed": "",
            "added_reason": "test",
            "active": False,
        },
    ]
}


class TestTwitterCollector:
    def test_fetch_mock_returns_tweets(self):
        """Mock data returns valid tweets."""
        tweets = TwitterCollector.fetch_mock()
        assert len(tweets) == 3
        assert tweets[0].author_handle == "karpathy"
        assert tweets[0].metrics["likes"] > 0

    def test_mock_tweet_structure(self):
        """Mock tweets have all required fields."""
        tweets = TwitterCollector.fetch_mock()
        for t in tweets:
            assert t.id
            assert t.text
            assert t.created_at
            assert t.author_handle


class TestAccountManager:
    def _make_manager(self, accounts_data=None):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump(accounts_data or SAMPLE_ACCOUNTS, f)
        f.close()
        return AccountManager(f.name), f.name

    def test_load_accounts(self):
        mgr, path = self._make_manager()
        assert len(mgr.accounts) == 2

    def test_active_accounts_filters(self):
        mgr, path = self._make_manager()
        active = mgr.active_accounts()
        assert len(active) == 1
        assert active[0].handle == "karpathy"

    def test_handles_returns_list(self):
        mgr, path = self._make_manager()
        handles = mgr.handles()
        assert handles == ["karpathy"]

    def test_add_account(self):
        mgr, path = self._make_manager()
        mgr.add_account("test_user", "Test User", ["ai"], "testing")
        assert len(mgr.accounts) == 3
        # Verify persistence
        mgr2 = AccountManager(path)
        assert len(mgr2.accounts) == 3

    def test_remove_account(self):
        mgr, path = self._make_manager()
        assert mgr.remove_account("karpathy")
        assert len(mgr.accounts) == 1
        assert not mgr.remove_account("nonexistent")

    def test_save_persists(self):
        mgr, path = self._make_manager()
        mgr.accounts[0].trust_score = 0.95
        mgr.save()

        mgr2 = AccountManager(path)
        assert mgr2.accounts[0].trust_score == 0.95
