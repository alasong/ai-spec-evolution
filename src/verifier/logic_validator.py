"""L4 Logic Validator — verify logical soundness of AI coding practices."""

from __future__ import annotations

import logging
from datetime import datetime

from src.models.practice import Practice, VerdictStatus, VerificationResult
from src.llm.dashscope import DashScopeClient

logger = logging.getLogger(__name__)


class LogicValidator:
    """Verify the logical soundness of a practice before creating an issue."""

    def __init__(self, llm: DashScopeClient):
        self.llm = llm

    def verify(self, practice: Practice) -> VerificationResult:
        """Run logic verification on a practice."""
        try:
            result = self.llm.verify_logic(
                practice.summary,
                practice.detail,
                model="qwen-max",
            )
        except Exception as e:
            logger.error("Logic verification error for %s: %s", practice.id, e)
            return VerificationResult(
                practice_id=practice.id,
                logic_verdict=VerdictStatus.NEEDS_REVIEW,
                logic_reasoning=f"Verification error: {e}",
            )

        status_str = result.get("status", "needs_review")
        try:
            status = VerdictStatus(status_str)
        except ValueError:
            status = VerdictStatus.NEEDS_REVIEW

        return VerificationResult(
            practice_id=practice.id,
            logic_verdict=status,
            logic_reasoning=result.get("reasoning", ""),
            timestamp=datetime.now(),
        )
