"""L1 Filter + L2 Extractor — classify tweets and extract structured practices."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from src.models.practice import Category, Practice, Tweet, VerdictStatus
from src.llm.dashscope import DashScopeClient

logger = logging.getLogger(__name__)


class PracticeFilter:
    """L1: Classify tweets — keep only actionable engineering practices."""

    def __init__(self, llm: DashScopeClient):
        self.llm = llm

    def classify(self, tweet: Tweet) -> tuple[Category, float]:
        """Return (category, confidence) for a single tweet."""
        try:
            result = self.llm.classify_tweet(tweet.text, model="qwen-turbo")
            cat = Category(result.get("category", "noise"))
            conf = float(result.get("confidence", 0.0))
            return cat, conf
        except Exception as e:
            logger.error("Classification error for tweet %s: %s", tweet.id, e)
            return Category.NOISE, 0.0

    def filter_practices(self, tweets: list[Tweet], min_confidence: float = 0.7) -> list[Tweet]:
        """Filter tweets, returning only those classified as 'practice' above confidence threshold."""
        results = []
        for t in tweets:
            cat, conf = self.classify(t)
            if cat == Category.PRACTICE and conf >= min_confidence:
                t.metrics["classification"] = cat.value
                t.metrics["confidence"] = conf
                results.append(t)
                logger.info("  PRACTICE [%s] @%s conf=%.2f: %s...", cat.value, t.author_handle, conf, t.text[:60])
            else:
                logger.debug("  FILTERED [@%s] %s → %s (conf=%.2f)", t.author_handle, t.text[:50], cat.value, conf)
        return results


class PracticeExtractor:
    """L2: Extract structured practice information from classified tweets."""

    def __init__(self, llm: DashScopeClient):
        self.llm = llm

    def extract(self, tweet: Tweet) -> Practice:
        """Extract a structured Practice from a tweet."""
        try:
            result = self.llm.extract_practice(tweet.text, model="qwen-plus")
        except Exception as e:
            logger.error("Extraction error for tweet %s: %s", tweet.id, e)
            result = {
                "summary": tweet.text[:100],
                "detail": tweet.text,
                "tags": [],
                "evidence": tweet.text,
                "claims": [],
            }

        return Practice(
            id=f"practice-{tweet.id}",
            source=tweet,
            summary=result.get("summary", tweet.text[:100]),
            detail=result.get("detail", tweet.text),
            category=Category.PRACTICE,
            tags=result.get("tags", []),
            confidence=tweet.metrics.get("confidence", 0.0),
            evidence=result.get("evidence", tweet.text),
            suggested_spec_doc="",
            suggested_section="",
        )

    def extract_batch(self, tweets: list[Tweet]) -> list[Practice]:
        """Extract practices from a batch of classified tweets."""
        practices = []
        for t in tweets:
            p = self.extract(t)
            practices.append(p)
        return practices


def save_practices(practices: list[Practice], output_path: str):
    """Save practices to JSONL file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for p in practices:
            record = {
                "id": p.id,
                "summary": p.summary,
                "detail": p.detail,
                "tags": p.tags,
                "confidence": p.confidence,
                "evidence": p.evidence,
                "source_handle": p.source.author_handle,
                "source_text": p.source.text,
                "source_metrics": p.source.metrics,
                "timestamp": p.timestamp.isoformat(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("Saved %d practices to %s", len(practices), output_path)


def load_practices(input_path: str) -> list[Practice]:
    """Load practices from JSONL file."""
    path = Path(input_path)
    if not path.exists():
        return []
    practices = []
    with open(path) as f:
        for line in f:
            record = json.loads(line)
            # Build minimal Practice from stored record
            from src.models.practice import Tweet
            source = Tweet(
                id=record.get("id", ""),
                author_handle=record.get("source_handle", ""),
                author_name=record.get("source_handle", ""),
                text=record.get("source_text", ""),
                created_at=datetime.now(),
                metrics=record.get("source_metrics", {}),
            )
            practices.append(Practice(
                id=record["id"],
                source=source,
                summary=record["summary"],
                detail=record["detail"],
                category=Category.PRACTICE,
                tags=record.get("tags", []),
                confidence=record.get("confidence", 0.0),
                evidence=record.get("evidence", ""),
            ))
    return practices
