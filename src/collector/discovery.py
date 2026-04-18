"""Discovery Layer — find new AI coding voices via keyword search.

Operates in two phases:
1. DISCOVERY (weekly): Search Twitter for AI coding keywords, extract candidate authors
2. VERIFICATION: Score candidates against quality thresholds, auto-add to accounts.yaml

Separated from Collection layer to minimize API usage while maximizing coverage.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from src.collector.account_manager import AccountManager
from src.llm.dashscope import DashScopeClient
from src.models.practice import AccountEntry, Tweet

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"

# Core keywords for AI coding discovery
DEFAULT_KEYWORDS = [
    "AI coding best practices",
    "cursor rules",
    "Claude Code tips",
    "spec-driven development",
    "agentic development",
    "AI agent coding",
    "TDD with AI",
    "AI code review",
    "prompt engineering coding",
    "AI software engineering",
]


@dataclass
class CandidateAuthor:
    """A potential new account discovered via keyword search."""
    handle: str
    name: str
    tweet_text: str
    tweet_id: str
    keyword_matched: str
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    llm_score: float = 0.0
    llm_reason: str = ""
    discovery_count: int = 1  # How many times this author was found
    expertise_areas: list[str] = field(default_factory=list)


class DiscoveryCollector:
    """Search Twitter for AI coding content and discover new authors."""

    def __init__(self, bearer_token: str):
        self.bearer_token = bearer_token
        self.session = httpx.Client(
            base_url=TWITTER_API_BASE,
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=30.0,
        )

    def search_keywords(
        self,
        keywords: list[str] | None = None,
        since_days: int = 7,
        min_likes: int = 10,
        max_results: int = 50,
    ) -> list[Tweet]:
        """Search Twitter for AI coding content using keywords.
        Returns high-engagement tweets matching any keyword.
        """
        keywords = keywords or DEFAULT_KEYWORDS
        since = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        all_tweets: list[Tweet] = []

        for keyword in keywords:
            logger.info("Searching: '%s'", keyword)
            # Build query: keyword + min engagement filter
            query = f"{keyword} min_faves:{min_likes} -is:retweet lang:en"

            params = {
                "query": query,
                "max_results": min(max_results, 100),
                "start_time": since,
                "tweet.fields": "created_at,public_metrics,author_id",
                "expansions": "author_id",
                "user.fields": "name,username,description,public_metrics",
            }

            try:
                resp = self.session.get("/tweets/search/recent", params=params)
                if resp.status_code == 429:
                    logger.warning("Rate limited, waiting 15 min...")
                    time.sleep(900)
                    continue
                if resp.status_code != 200:
                    logger.error("Search failed for '%s': %d %s", keyword, resp.status_code, resp.text)
                    continue

                data = resp.json()
                tweets_data = data.get("data", [])
                users_map = {}
                for user in data.get("includes", {}).get("users", []):
                    users_map[user["id"]] = user

                for t in tweets_data:
                    author_id = t.get("author_id", "")
                    user = users_map.get(author_id, {})
                    all_tweets.append(
                        Tweet(
                            id=t["id"],
                            author_handle=user.get("username", "unknown"),
                            author_name=user.get("name", "unknown"),
                            text=t["text"],
                            created_at=datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")),
                            metrics=t.get("public_metrics", {}),
                            thread=[],
                        )
                    )
            except httpx.RequestError as e:
                logger.error("Request error for keyword '%s': %s", keyword, e)

            # Rate limit: Free tier = 1 req / 15 min for search
            time.sleep(2.0)

        logger.info("Discovery search found %d tweets", len(all_tweets))
        return all_tweets

    @staticmethod
    def search_mock() -> list[Tweet]:
        """Mock discovery results for testing."""
        now = datetime.now()
        return [
            Tweet(
                id="disc-001",
                author_handle="swyx",
                author_name="swyx",
                text="After building 50+ AI agents, here's the pattern that actually works: write the test specification FIRST, then have the agent generate code against it. The spec becomes the contract. No more hallucinated APIs.",
                created_at=now,
                metrics={"likes": 3400, "retweets": 890, "replies": 156},
            ),
            Tweet(
                id="disc-002",
                author_handle="codyogden",
                author_name="Cody Ogden",
                text="Hot take: most AI coding tools are built wrong. The right approach is to let the AI read your entire codebase context, then give it a focused task. Context window is your friend, not your enemy.",
                created_at=now - timedelta(hours=2),
                metrics={"likes": 1200, "retweets": 340, "replies": 89},
            ),
            Tweet(
                id="disc-003",
                author_handle="bentossell",
                author_name="Ben Tossell",
                text="My team switched to AI-first code reviews. Before any PR is merged, an AI agent reviews it for security, performance, and style. Humans only review business logic. Cut review time by 70%.",
                created_at=now - timedelta(hours=5),
                metrics={"likes": 2100, "retweets": 520, "replies": 98},
            ),
            # Noise (low engagement, no actionable content)
            Tweet(
                id="disc-004",
                author_handle="random_user",
                author_name="Random User",
                text="AI is so cool!!! #coding #AI #technology",
                created_at=now,
                metrics={"likes": 3, "retweets": 0, "replies": 0},
            ),
        ]


class DiscoveryAnalyzer:
    """Analyze discovered tweets and score candidate authors."""

    def __init__(self, llm: DashScopeClient, account_manager: AccountManager):
        self.llm = llm
        self.account_mgr = account_manager

    def analyze(
        self,
        tweets: list[Tweet],
        min_likes: int = 50,
        min_llm_score: float = 0.6,
    ) -> list[CandidateAuthor]:
        """Filter and score tweets, returning qualified candidate authors."""
        # Phase 1: Filter by engagement
        high_engagement = [
            t for t in tweets
            if t.metrics.get("likes", 0) >= min_likes
            and t.metrics.get("retweets", 0) >= min_likes // 5
        ]
        logger.info("High engagement filter: %d → %d tweets", len(tweets), len(high_engagement))

        # Phase 2: Skip accounts already in our list
        existing_handles = {a.handle for a in self.account_mgr.accounts}
        new_tweets = [t for t in high_engagement if t.author_handle not in existing_handles]
        logger.info("After existing filter: %d tweets from new authors", len(new_tweets))

        # Phase 3: LLM quality scoring (batch)
        candidates: list[CandidateAuthor] = []
        for tweet in new_tweets:
            try:
                score, reason, expertise = self._score_tweet(tweet)
                if score >= min_llm_score:
                    candidates.append(
                        CandidateAuthor(
                            handle=tweet.author_handle,
                            name=tweet.author_name,
                            tweet_text=tweet.text,
                            tweet_id=tweet.id,
                            keyword_matched="discovery",
                            likes=tweet.metrics.get("likes", 0),
                            retweets=tweet.metrics.get("retweets", 0),
                            replies=tweet.metrics.get("replies", 0),
                            llm_score=score,
                            llm_reason=reason,
                            expertise_areas=expertise,
                        )
                    )
            except Exception as e:
                logger.error("Failed to score tweet %s: %s", tweet.id, e)

        # Phase 4: Deduplicate — aggregate by author
        authors: dict[str, CandidateAuthor] = {}
        for c in candidates:
            if c.handle in authors:
                existing = authors[c.handle]
                existing.discovery_count += 1
                # Keep highest score
                if c.llm_score > existing.llm_score:
                    existing.llm_score = c.llm_score
                    existing.llm_reason = c.llm_reason
                    existing.tweet_text = c.tweet_text
                    existing.expertise_areas = c.expertise_areas
                # Accumulate engagement
                existing.likes += c.likes
            else:
                authors[c.handle] = c

        result = list(authors.values())
        result.sort(key=lambda a: a.llm_score, reverse=True)
        logger.info("Discovery found %d qualified candidate authors", len(result))
        return result

    def _score_tweet(self, tweet: Tweet) -> tuple[float, str, list[str]]:
        """Use LLM to score a single tweet for author quality.
        Returns (score, reason, expertise_areas).
        """
        prompt = f"""Evaluate whether this Twitter user is a valuable source for AI coding best practices.
Consider: technical depth, actionable insights, real-world evidence, domain expertise.

Tweet: {tweet.text}
Engagement: {tweet.metrics.get('likes', 0)} likes, {tweet.metrics.get('retweets', 0)} retweets

Respond with JSON only:
{{
  "score": 0.0-1.0,
  "reason": "one sentence explaining the score",
  "expertise": ["area1", "area2"]
}}"""

        result = self.llm.chat_json(
            messages=[
                {"role": "system", "content": "Evaluate AI coding content quality. JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        return (
            result.get("score", 0.0),
            result.get("reason", ""),
            result.get("expertise", []),
        )

    def promote_candidates(
        self,
        candidates: list[CandidateAuthor],
        min_score: float = 0.7,
        min_engagement: int = 100,
    ) -> list[AccountEntry]:
        """Promote high-scoring candidates to the curated accounts list."""
        promoted = []
        for c in candidates:
            if c.llm_score >= min_score and c.likes >= min_engagement:
                reason = f"Discovered via keyword search: {c.llm_reason}"
                self.account_mgr.add_account(
                    handle=c.handle,
                    name=c.name,
                    expertise=c.expertise_areas,
                    reason=reason,
                )
                # Set initial trust score based on LLM score
                entry = self.account_mgr.accounts[-1]
                entry.trust_score = round(c.llm_score * 0.5, 2)  # New accounts start conservative
                self.account_mgr.save()
                promoted.append(entry)
                logger.info(
                    "Promoted @%s to curated accounts (score=%.2f, likes=%d)",
                    c.handle, c.llm_score, c.likes,
                )
        return promoted

    def run_full_discovery(
        self,
        collector: DiscoveryCollector,
        keywords: list[str] | None = None,
        min_likes: int = 50,
        min_llm_score: float = 0.6,
        promote_min_score: float = 0.7,
        promote_min_engagement: int = 100,
    ) -> dict:
        """Run the full discovery pipeline: search → analyze → promote."""
        tweets = collector.search_keywords(keywords=keywords, min_likes=min_likes)
        candidates = self.analyze(tweets, min_likes=min_likes, min_llm_score=min_llm_score)
        promoted = self.promote_candidates(
            candidates, min_score=promote_min_score, min_engagement=promote_min_engagement,
        )
        return {
            "tweets_found": len(tweets),
            "candidates_qualified": len(candidates),
            "accounts_promoted": len(promoted),
            "promoted_handles": [p.handle for p in promoted],
        }


def save_discovery_report(candidates: list[CandidateAuthor], output_path: str):
    """Save discovery results as JSON for review."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "discovered_at": datetime.now().isoformat(),
        "total_candidates": len(candidates),
        "candidates": [
            {
                "handle": c.handle,
                "name": c.name,
                "llm_score": c.llm_score,
                "llm_reason": c.llm_reason,
                "likes": c.likes,
                "retweets": c.retweets,
                "discovery_count": c.discovery_count,
                "expertise": c.expertise_areas,
                "sample_tweet": c.tweet_text,
            }
            for c in candidates
        ],
    }
    with open(path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Saved discovery report to %s", output_path)
