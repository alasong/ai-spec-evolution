"""CLI entry point for ai-spec-evolution — full pipeline wiring."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("spec-evolution")


def main():
    parser = argparse.ArgumentParser(
        description="AI Spec Evolution — discover, verify, and propose AI coding practices"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("collect", help="Fetch tweets from curated accounts")
    sub.add_parser("filter", help="LLM-classify collected tweets")
    sub.add_parser("dedup", help="Remove duplicates against existing issues/specs")
    sub.add_parser("verify", help="Run logic + project verification")
    sub.add_parser("issue", help="Create GitHub issues for verified practices")
    sub.add_parser("accounts", help="Manage curated Twitter accounts")
    sub.add_parser("run", help="Run full pipeline")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    config = load_config()
    logger.info("Running command: %s", args.command)
    logger.info("Models: %s (filter), %s (analysis), %s (verification)",
                config.pipeline.dashscope.filter_model,
                config.pipeline.dashscope.analysis_model,
                config.pipeline.dashscope.verification_model)

    if args.command == "run":
        run_pipeline(config)
    else:
        logger.info("Command '%s' — run with 'run' for full pipeline", args.command)
        sys.exit(0)


def run_pipeline(config):
    """Run the full pipeline: collect -> filter -> dedup -> verify -> issue."""
    from src.collector.twitter import TwitterCollector
    from src.processor.filter import PracticeFilter, PracticeExtractor, save_practices
    from src.processor.dedup import DedupEngine
    from src.verifier.logic_validator import LogicValidator
    from src.verifier.fork_runner import ProjectVerifier
    from src.generator.issue import IssueGenerator
    from src.llm.dashscope import DashScopeClient

    # ─── Initialize components ────────────────────────────────────────
    llm_filter = DashScopeClient(
        api_key=config.pipeline.dashscope.api_key,
        default_model=config.pipeline.dashscope.filter_model,
    )
    llm_analysis = DashScopeClient(
        api_key=config.pipeline.dashscope.api_key,
        default_model=config.pipeline.dashscope.analysis_model,
    )
    llm_verify = DashScopeClient(
        api_key=config.pipeline.dashscope.api_key,
        default_model=config.pipeline.dashscope.verification_model,
    )

    data_dir = Path(config.pipeline.data_dir)
    data_dir.mkdir(exist_ok=True)
    (data_dir / "collected").mkdir(exist_ok=True)
    (data_dir / "filtered").mkdir(exist_ok=True)
    (data_dir / "verified").mkdir(exist_ok=True)

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ─── Stage 1: Collect ─────────────────────────────────────────────
    logger.info("=== Stage 1/5: Collecting tweets ===")
    collector = TwitterCollector(
        bearer_token=config.pipeline.twitter.bearer_token,
        accounts_file=config.pipeline.twitter.accounts_file,
    )
    # Use mock data if bearer token is empty (dev mode)
    if not config.pipeline.twitter.bearer_token:
        logger.info("No Twitter bearer token — using mock data")
        tweets = TwitterCollector.fetch_mock()
    else:
        tweets = collector.fetch_timelines(
            since_days=config.pipeline.twitter.fetch_since_days,
            limit_per_account=config.pipeline.twitter.fetch_limit,
        )
    logger.info("Collected %d tweets", len(tweets))

    # ─── Stage 2: Filter + Extract ────────────────────────────────────
    logger.info("=== Stage 2/5: Filtering and extracting practices ===")
    f = PracticeFilter(llm_filter)
    classified = f.filter_practices(tweets)
    logger.info("Filtered to %d practice tweets", len(classified))

    extractor = PracticeExtractor(llm_analysis)
    practices = extractor.extract_batch(classified)
    logger.info("Extracted %d structured practices", len(practices))

    collected_file = data_dir / "collected" / f"{run_ts}.jsonl"
    save_practices(practices, str(collected_file))

    # ─── Stage 3: Dedup ───────────────────────────────────────────────
    logger.info("=== Stage 3/5: Deduplicating ===")
    dedup = DedupEngine()
    unique_practices = []
    for p in practices:
        doc, score = dedup.find_matching_doc(p.tags, p.summary)
        p.suggested_spec_doc = doc
        if score > 0.0:
            logger.info("  Match: %s → %s (score=%.2f)", p.summary[:50], doc, score)
        unique_practices.append(p)
    logger.info("%d practices after dedup", len(unique_practices))

    # ─── Stage 4: Verify ──────────────────────────────────────────────
    logger.info("=== Stage 4/5: Running verification ===")
    logic_validator = LogicValidator(llm_verify)
    project_verifier = ProjectVerifier(config.pipeline.github)

    verified_results = []
    for p in unique_practices:
        logger.info("  Verifying: %s", p.summary[:60])
        logic_result = logic_validator.verify(p)
        project_result = project_verifier.verify(p)

        # Combine verdicts
        final = combine_verdicts(logic_result, project_result)
        logic_result.final_verdict = final

        verified_results.append((p, logic_result))
        logger.info("  → %s", final.value)

        # Save verified results
        verified_file = data_dir / "verified" / f"{p.id}.json"

    # ─── Stage 5: Generate Issues ─────────────────────────────────────
    logger.info("=== Stage 5/5: Generating GitHub issues ===")
    issue_gen = IssueGenerator(config.pipeline.github)
    created = 0
    for practice, result in verified_results:
        if result.final_verdict in ("verified", "needs_review"):
            issue = issue_gen.create_issue(practice, result)
            if issue:
                created += 1

    logger.info("=== Pipeline complete ===")
    logger.info("Collected: %d → Filtered: %d → Verified: %d → Issues created: %d",
                len(tweets), len(practices), len(verified_results), created)


def combine_verdicts(logic: "VerificationResult", project: "VerificationResult") -> str:
    """Combine logic and project verdicts into a final verdict."""
    from src.models.practice import VerdictStatus
    if logic.logic_verdict == VerdictStatus.FAILED:
        return VerdictStatus.REJECTED.value
    if logic.logic_verdict == VerdictStatus.VERIFIED and project.project_verdict == VerdictStatus.VERIFIED:
        return VerdictStatus.VERIFIED.value
    if logic.logic_verdict == VerdictStatus.NEEDS_REVIEW:
        return VerdictStatus.NEEDS_REVIEW.value
    return VerdictStatus.NEEDS_REVIEW.value


if __name__ == "__main__":
    main()
