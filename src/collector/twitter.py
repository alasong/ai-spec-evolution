"""Twitter API v2 collector — fetch timeline from curated accounts."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import httpx

from src.models.practice import Tweet

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"


class TwitterCollector:
    """Fetch tweets from curated accounts via Twitter API v2."""

    def __init__(self, bearer_token: str, accounts_file: str):
        self.bearer_token = bearer_token
        self.session = httpx.Client(
            base_url=TWITTER_API_BASE,
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=30.0,
        )
        from src.collector.account_manager import AccountManager
        self.account_mgr = AccountManager(accounts_file)

    def fetch_timelines(self, since_days: int = 7, limit_per_account: int = 20) -> list[Tweet]:
        """Fetch recent tweets from all active curated accounts."""
        all_tweets: list[Tweet] = []
        since = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        for account in self.account_mgr.active_accounts():
            logger.info("Fetching tweets from @%s...", account.handle)
            tweets = self._fetch_user_timeline(account.handle, since, limit_per_account)
            all_tweets.extend(tweets)
            # Rate limit: stay within 5-min window for Free tier
            time.sleep(1.0)

        logger.info("Fetched %d tweets from %d accounts", len(all_tweets), len(self.account_mgr.active_accounts()))
        return all_tweets

    def _fetch_user_timeline(self, handle: str, since: str, limit: int) -> list[Tweet]:
        """Fetch tweets from a single user's timeline."""
        # First resolve handle to user_id
        user_id = self._resolve_user_id(handle)
        if not user_id:
            return []

        params = {
            "max_results": min(limit, 100),
            "start_time": since,
            "tweet.fields": "created_at,public_metrics,conversation_id",
            "exclude": "retweets,replies",
        }

        try:
            resp = self.session.get(f"/users/{user_id}/tweets", params=params)
            if resp.status_code == 429:
                logger.warning("Rate limited on @%s, waiting...", handle)
                time.sleep(900)  # 15 min backoff
                return self._fetch_user_timeline(handle, since, limit)

            if resp.status_code != 200:
                logger.error("Failed to fetch @%s: %d %s", handle, resp.status_code, resp.text)
                return []

            data = resp.json().get("data", [])
            return [
                Tweet(
                    id=t["id"],
                    author_handle=handle,
                    author_name=handle,
                    text=t["text"],
                    created_at=datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
                    metrics=t.get("public_metrics", {}),
                )
                for t in data
            ]
        except httpx.RequestError as e:
            logger.error("Request error for @%s: %s", handle, e)
            return []

    def _resolve_user_id(self, handle: str) -> str | None:
        """Resolve a handle to a Twitter user ID."""
        try:
            resp = self.session.get("/users/by/username/" + handle.lstrip("@"))
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("id")
            logger.error("Failed to resolve @%s: %d", handle, resp.status_code)
        except httpx.RequestError as e:
            logger.error("Error resolving @%s: %s", handle, e)
        return None

    @staticmethod
    def fetch_mock() -> list[Tweet]:
        """Return mock tweets for testing pipeline without API access."""
        now = datetime.now()
        return [
            Tweet(
                id="mock-001",
                author_handle="karpathy",
                author_name="Andrej Karpathy",
                text="Best practice: always write the test first before implementing the feature. TDD catches edge cases you wouldn't think of. Saw this save us hours in production debugging.",
                created_at=now,
                metrics={"likes": 5200, "retweets": 890, "replies": 120},
            ),
            Tweet(
                id="mock-002",
                author_handle="karpathy",
                author_name="Andrej Karpathy",
                text="Hot take: AI will replace developers. The end. (just kidding, please don't quote tweet me)",
                created_at=now - timedelta(hours=1),
                metrics={"likes": 12000, "retweets": 3400, "replies": 890},
            ),
            Tweet(
                id="mock-003",
                author_handle="karpathy",
                author_name="Andrej Karpathy",
                text="We've been using spec-driven development with AI agents. The key insight: write the API contract in OpenAPI first, then let the agent generate both server and test code. Reduced our spec-to-production cycle from days to hours. The contract acts as a single source of truth that prevents drift.",
                created_at=now - timedelta(hours=3),
                metrics={"likes": 8100, "retweets": 1500, "replies": 340},
            ),
        ]
