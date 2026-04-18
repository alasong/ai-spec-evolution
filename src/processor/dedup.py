"""L3 Dedup + Gap Analysis — semantic dedup against existing issues and specs."""

from __future__ import annotations

import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)


class DedupEngine:
    """Deduplicate new practices against existing issues and spec documents."""

    def __init__(self, target_repo_path: str = "../ai-coding-standards"):
        self.spec_docs_dir = Path(target_repo_path) / "ai-coding-v5.4"
        self._spec_texts: dict[str, str] = {}
        self._load_spec_docs()

    def _load_spec_docs(self):
        """Load all existing spec documents for comparison."""
        if not self.spec_docs_dir.exists():
            logger.warning("Spec docs dir not found at %s, skipping dedup", self.spec_docs_dir)
            return
        for md_file in self.spec_docs_dir.glob("*.md"):
            self._spec_texts[md_file.name] = md_file.read_text()
        logger.info("Loaded %d spec documents for dedup", len(self._spec_texts))

    def keyword_overlap_score(self, tags: list[str], doc_text: str) -> float:
        """Simple keyword-based relevance score."""
        if not tags:
            return 0.0
        doc_lower = doc_text.lower()
        matches = sum(1 for tag in tags if tag.lower() in doc_lower)
        return matches / len(tags)

    def find_matching_doc(self, tags: list[str], summary: str) -> tuple[str, float]:
        """Find the best-matching spec document for a practice.
        Returns (filename, score).
        """
        best_doc = ""
        best_score = 0.0
        for filename, text in self._spec_texts.items():
            score = self.keyword_overlap_score(tags, text)
            if score > best_score:
                best_score = score
                best_doc = filename
        return best_doc, best_score

    def check_dup_against_issues(self, practice_summary: str, existing_issues: list[dict]) -> dict | None:
        """Check if this practice is already proposed in an existing issue.
        Returns the matching issue if found, None otherwise.
        Uses simple string similarity (cosine similarity on word overlap).
        """
        if not existing_issues:
            return None

        new_words = set(practice_summary.lower().split())
        best_match = None
        best_sim = 0.0

        for issue in existing_issues:
            existing_words = set(issue.get("title", "").lower().split())
            existing_words.update(issue.get("body", "").lower().split()[:50])  # limit
            if not existing_words or not new_words:
                continue
            overlap = len(new_words & existing_words)
            union = len(new_words | existing_words)
            sim = overlap / max(union, 1)
            if sim > best_sim:
                best_sim = sim
                best_match = issue

        if best_sim > 0.4:
            return best_match
        return None


def cosine_similarity(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors (word -> weight)."""
    all_keys = set(v1.keys()) | set(v2.keys())
    if not all_keys:
        return 0.0
    dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in all_keys)
    norm1 = math.sqrt(sum(v * v for v in v1.values()))
    norm2 = math.sqrt(sum(v * v for v in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def build_word_freq(text: str) -> dict[str, float]:
    """Build a simple word frequency vector."""
    words = text.lower().split()
    freq: dict[str, float] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return freq
