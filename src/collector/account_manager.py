"""Twitter account manager — curated list with periodic quality refresh."""

from __future__ import annotations

import logging
from datetime import datetime

import yaml

from src.models.practice import AccountEntry
from src.llm.dashscope import DashScopeClient

logger = logging.getLogger(__name__)


class AccountManager:
    """Manages curated Twitter accounts with periodic trust_score refresh."""

    def __init__(self, accounts_file: str, llm: DashScopeClient | None = None):
        self.accounts_file = accounts_file
        self.llm = llm
        self.accounts: list[AccountEntry] = []
        self._load()

    def _load(self):
        with open(self.accounts_file) as f:
            raw = yaml.safe_load(f) or {"accounts": []}
        self.accounts = [AccountEntry(**a) for a in raw["accounts"]]

    def save(self):
        raw = {
            "accounts": [
                {
                    "handle": a.handle,
                    "name": a.name,
                    "expertise": a.expertise,
                    "trust_score": a.trust_score,
                    "last_refreshed": a.last_refreshed,
                    "added_reason": a.added_reason,
                    "active": a.active,
                }
                for a in self.accounts
            ]
        }
        with open(self.accounts_file, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def active_accounts(self) -> list[AccountEntry]:
        return [a for a in self.accounts if a.active]

    def handles(self) -> list[str]:
        return [a.handle for a in self.active_accounts()]

    def refresh_trust_scores(self, recent_tweets: dict[str, list[str]]) -> dict[str, float]:
        """
        Analyze recent tweets per account and update trust scores.
        recent_tweets: {handle: [tweet_texts]}
        Returns: {handle: new_trust_score}
        """
        if not self.llm:
            logger.warning("No LLM client provided, skipping trust score refresh")
            return {}

        results = {}
        for account in self.active_accounts():
            tweets = recent_tweets.get(account.handle, [])
            if not tweets:
                logger.info("No recent tweets for @%s, keeping score %.2f", account.handle, account.trust_score)
                results[account.handle] = account.trust_score
                continue

            # Sample up to 10 tweets for analysis
            sample = tweets[:10]
            text_block = "\n---\n".join(f"[{i+1}] {t}" for i, t in enumerate(sample))

            prompt = f"""Evaluate the AI coding practice quality of this Twitter account's recent tweets.
Score 0.0-1.0 based on: actionable insights, technical depth, real-world evidence.

Tweets:
{text_block}

Respond with JSON only:
{{
  "quality_score": 0.0-1.0,
  "reason": "one sentence",
  "top_practices": ["list 1-2 best practices mentioned"]
}}"""

            try:
                result = self.llm.chat_json(
                    messages=[
                        {"role": "system", "content": "Evaluate AI coding content quality. JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    model="qwen3.5-plus",
                    temperature=0.0,
                )
                new_score = result.get("quality_score", account.trust_score)
                old_score = account.trust_score

                # Smooth update (30% new, 70% old)
                account.trust_score = round(0.7 * old_score + 0.3 * new_score, 2)
                account.last_refreshed = datetime.now().isoformat()

                # Auto-deactivate if score drops below threshold
                if account.trust_score < 0.2:
                    account.active = False
                    logger.info("Auto-deactivated @%s (score %.2f < 0.2)", account.handle, account.trust_score)

                results[account.handle] = account.trust_score
                logger.info(
                    "@%s trust_score: %.2f -> %.2f (%s)",
                    account.handle, old_score, account.trust_score, result.get("reason", ""),
                )
            except Exception as e:
                logger.error("Failed to refresh trust score for @%s: %s", account.handle, e)
                results[account.handle] = account.trust_score

        self.save()
        return results

    def add_account(self, handle: str, name: str = "", expertise: list[str] | None = None, reason: str = ""):
        """Add a new account to the curated list."""
        entry = AccountEntry(
            handle=handle.lstrip("@"),
            name=name or handle,
            expertise=expertise or [],
            trust_score=0.5,
            added_reason=reason,
            last_refreshed=datetime.now().isoformat(),
        )
        self.accounts.append(entry)
        self.save()
        logger.info("Added account @%s (trust_score=%.2f)", entry.handle, entry.trust_score)

    def remove_account(self, handle: str) -> bool:
        """Remove an account. Returns True if found and removed."""
        handle = handle.lstrip("@")
        before = len(self.accounts)
        self.accounts = [a for a in self.accounts if a.handle != handle]
        if len(self.accounts) < before:
            self.save()
            return True
        return False
