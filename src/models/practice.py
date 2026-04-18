"""Data models for AI spec evolution pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Category(str, Enum):
    PRACTICE = "practice"
    NOISE = "noise"
    TOOL = "tool"
    OPINION = "opinion"


class VerdictStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


@dataclass
class Tweet:
    """Raw tweet from Twitter API."""
    id: str
    author_handle: str
    author_name: str
    text: str
    created_at: datetime
    metrics: dict = field(default_factory=dict)  # likes, retweets, replies
    thread: list[str] = field(default_factory=list)  # full thread if available


@dataclass
class Practice:
    """A structured AI coding practice extracted from social media."""
    id: str
    source: Tweet
    summary: str  # one-line description
    detail: str   # expanded explanation
    category: Category
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: str = ""  # quoted evidence from original text
    suggested_spec_doc: str = ""  # which spec doc this maps to
    suggested_section: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class VerificationResult:
    """Result of running a practice through the verification pipeline."""
    practice_id: str
    logic_verdict: VerdictStatus
    logic_reasoning: str = ""
    project_verdict: VerdictStatus | None = None
    project_evidence: str = ""  # CI logs, test results
    final_verdict: VerdictStatus | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AccountEntry:
    """A curated Twitter account to follow for AI coding practices."""
    handle: str
    name: str = ""
    expertise: list[str] = field(default_factory=list)
    trust_score: float = 0.5  # 0.0 - 1.0, updated by periodic refresh
    last_refreshed: str = ""  # ISO date
    added_reason: str = ""
    active: bool = True
