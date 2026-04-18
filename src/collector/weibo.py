"""Weibo API collector — stub for Phase 3 implementation.

Weibo data can be sourced from:
- 微博开放平台 API (requires developer account)
- Third-party scrapers (less stable, use with caution)

This module provides the interface that will be filled in once
we decide on the Weibo data source.
"""

from __future__ import annotations

import logging

from src.models.practice import Tweet

logger = logging.getLogger(__name__)


class WeiboCollector:
    """Fetch posts from curated Weibo accounts.

    TODO (Phase 3): Implement real Weibo API integration.
    Options:
    1. 微博开放平台 API — official, requires app approval
    2. Weibo RSS / third-party services
    3. Web scraping (higher maintenance)
    """

    def __init__(self, accounts_file: str):
        self.accounts_file = accounts_file

    def fetch_posts(self, since_days: int = 7, limit_per_account: int = 20) -> list[Tweet]:
        """Fetch recent posts from active Weibo accounts."""
        logger.info("Weibo collector not yet implemented (Phase 3)")
        # Return empty list — Weibo integration is Phase 3
        return []

    @staticmethod
    def fetch_mock() -> list[Tweet]:
        """Return mock Weibo posts for testing."""
        from datetime import datetime

        now = datetime.now()
        return [
            Tweet(
                id="weibo-mock-001",
                author_handle="ai_researcher_cn",
                author_name="AI研究员",
                text="用AI做代码review的一个好方法：先让AI解释每段代码的意图，再对比实际需求。这比直接问'有bug吗'更能发现逻辑错误。",
                created_at=now,
                metrics={"likes": 320, "retweets": 85, "replies": 42},
            ),
        ]
