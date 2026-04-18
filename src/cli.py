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
    sub.add_parser("discover", help="Run Discovery Layer — find new AI coding voices via keyword search")
    sub.add_parser("stats", help="Show pipeline statistics")
    sub.add_parser("filter", help="LLM-classify collected tweets")
    sub.add_parser("dedup", help="Remove duplicates against existing issues/specs")
    sub.add_parser("verify", help="Run logic + project verification")
    sub.add_parser("issue", help="Create GitHub issues for verified practices")
    sub.add_parser("accounts", help="Manage curated Twitter accounts")
    sub.add_parser("run", help="Run full pipeline (collection + discovery)")

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
    elif args.command == "discover":
        run_discovery(config)
    elif args.command == "stats":
        show_stats(config)
    else:
        logger.info("Command '%s' — run with 'run' for full pipeline", args.command)
        sys.exit(0)


def run_pipeline(config):
    """Run the full collection pipeline: collect -> filter -> dedup -> verify -> issue."""
    from src.collector.twitter import TwitterCollector
    from src.processor.filter import PracticeFilter, PracticeExtractor
    from src.processor.dedup import DedupEngine
    from src.verifier.logic_validator import LogicValidator
    from src.verifier.fork_runner import ProjectVerifier
    from src.generator.issue import IssueGenerator
    from src.llm.dashscope import DashScopeClient
    from src.db import Database

    db = Database(str(Path(config.pipeline.data_dir) / "spec_evolution.db"))
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

    # ─── Stage 1: Collect ─────────────────────────────────────────────
    logger.info("=== Stage 1/5: Collecting tweets ===")
    collector = TwitterCollector(
        bearer_token=config.pipeline.twitter.bearer_token,
        accounts_file=config.pipeline.twitter.accounts_file,
    )
    if not config.pipeline.twitter.bearer_token:
        logger.info("No Twitter bearer token — using mock data")
        tweets = TwitterCollector.fetch_mock()
    else:
        tweets = collector.fetch_timelines(
            since_days=config.pipeline.twitter.fetch_since_days,
            limit_per_account=config.pipeline.twitter.fetch_limit,
        )

    # Persist tweets to DB (dedup handled)
    for t in tweets:
        db.insert_tweet(
            tweet_id=t.id,
            author_handle=t.author_handle,
            author_name=t.author_name,
            text=t.text,
            created_at=t.created_at.isoformat(),
            metrics=t.metrics,
            source="collection",
        )
    logger.info("Collected %d tweets (DB total: %d)", len(tweets), db.count_tweets())

    # ─── Stage 2: Filter + Extract ────────────────────────────────────
    logger.info("=== Stage 2/5: Filtering and extracting practices ===")
    f = PracticeFilter(llm_filter)
    classified = f.filter_practices(tweets)
    logger.info("Filtered to %d practice tweets", len(classified))

    extractor = PracticeExtractor(llm_analysis)
    practices = extractor.extract_batch(classified)
    logger.info("Extracted %d structured practices", len(practices))

    # Persist practices to DB
    for p in practices:
        db.insert_practice(
            practice_id=p.id,
            tweet_id=p.source.id,
            summary=p.summary,
            detail=p.detail,
            tags=p.tags,
            confidence=p.confidence,
            evidence=p.evidence,
        )

    # ─── Stage 3: Dedup ───────────────────────────────────────────────
    logger.info("=== Stage 3/5: Deduplicating ===")
    dedup = DedupEngine()
    unique_practices = []
    for p in practices:
        doc, score = dedup.find_matching_doc(p.tags, p.summary)
        p.suggested_spec_doc = doc
        if score > 0.0:
            logger.info("  Match: %s → %s (score=%.2f)", p.summary[:50], doc, score)
            db.update_practice_status(p.id, "deduped")
        else:
            unique_practices.append(p)
    logger.info("%d practices after dedup", len(unique_practices))

    # ─── Stage 4: Verify ──────────────────────────────────────────────
    logger.info("=== Stage 4/5: Running verification ===")
    logic_validator = LogicValidator(llm_verify)
    project_verifier = ProjectVerifier(config.pipeline.github)

    verified_results = []
    for p in unique_practices:
        if db.has_verification(p.id):
            logger.info("  Skipping %s — already verified", p.id)
            continue
        logger.info("  Verifying: %s", p.summary[:60])
        logic_result = logic_validator.verify(p)
        project_result = project_verifier.verify(p)

        final = combine_verdicts(logic_result, project_result)
        logic_result.final_verdict = final

        db.log_verification(
            practice_id=p.id,
            logic_verdict=logic_result.logic_verdict.value,
            logic_reasoning=logic_result.logic_reasoning,
            project_verdict=logic_result.project_verdict.value if logic_result.project_verdict else None,
            project_evidence=logic_result.project_evidence,
            final_verdict=final,
        )
        db.update_practice_status(p.id, final)

        verified_results.append((p, logic_result))
        logger.info("  → %s", final)

    # ─── Stage 5: Generate Issues ─────────────────────────────────────
    logger.info("=== Stage 5/5: Generating GitHub issues ===")
    issue_gen = IssueGenerator(config.pipeline.github)
    created = 0
    for practice, result in verified_results:
        if result.final_verdict in ("verified", "needs_review"):
            if db.has_issue(practice.id):
                logger.info("  Skipping %s — issue already created", practice.id)
                continue
            issue = issue_gen.create_issue(practice, result)
            if issue:
                db.log_issue(practice.id, issue["number"], issue["html_url"], issue["title"])
                created += 1

    logger.info("=== Pipeline complete ===")
    logger.info("Collected: %d → Filtered: %d → Verified: %d → Issues created: %d",
                len(tweets), len(practices), len(verified_results), created)
    logger.info("DB stats: %s", db.stats())


def run_discovery(config):
    """Run the Discovery Layer — find new AI coding voices via keyword search."""
    from src.collector.discovery import DiscoveryCollector, DiscoveryAnalyzer, save_discovery_report
    from src.collector.account_manager import AccountManager
    from src.llm.dashscope import DashScopeClient
    from src.db import Database

    db = Database(str(Path(config.pipeline.data_dir) / "spec_evolution.db"))
    llm_discovery = DashScopeClient(
        api_key=config.pipeline.dashscope.api_key,
        default_model=config.pipeline.dashscope.filter_model,
    )

    account_mgr = AccountManager(
        accounts_file=config.pipeline.twitter.accounts_file,
        llm=llm_discovery,
    )
    analyzer = DiscoveryAnalyzer(llm_discovery, account_mgr)

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(config.pipeline.data_dir) / f"discovery_{run_ts}.json"

    if not config.pipeline.twitter.bearer_token:
        logger.info("No Twitter bearer token — using mock discovery data")
        tweets = DiscoveryCollector.search_mock()
    else:
        collector = DiscoveryCollector(config.pipeline.twitter.bearer_token)
        tweets = collector.search_keywords()

    # Filter out already-discovered tweets
    new_tweets = [t for t in tweets if not db.discovery_exists(t.id)]
    logger.info("New tweets for discovery: %d (skipped %d already logged)",
                len(new_tweets), len(tweets) - len(new_tweets))

    candidates = analyzer.analyze(new_tweets)
    promoted = analyzer.promote_candidates(candidates)

    # Log discovery to DB
    for c in candidates:
        was_promoted = any(p.handle == c.handle for p in promoted)
        db.log_discovery(
            handle=c.handle,
            name=c.name,
            tweet_text=c.tweet_text,
            tweet_id=c.tweet_id,
            keyword_matched=c.keyword_matched,
            likes=c.likes,
            retweets=c.retweets,
            llm_score=c.llm_score,
            llm_reason=c.llm_reason,
            expertise=c.expertise_areas,
            promoted=was_promoted,
        )

    save_discovery_report(candidates, str(report_path))

    logger.info("=== Discovery complete ===")
    logger.info("Tweets found: %d → Candidates qualified: %d → Accounts promoted: %d",
                len(new_tweets), len(candidates), len(promoted))
    if promoted:
        logger.info("Promoted: %s", ", ".join(f"@{h.handle}" for h in promoted))
    logger.info("Discovery stats: %s", db.get_discovery_stats())


def show_stats(config):
    """Show pipeline statistics from the database."""
    from src.db import Database
    db = Database(str(Path(config.pipeline.data_dir) / "spec_evolution.db"))
    stats = db.stats()
    discovery = db.get_discovery_stats()

    print("\n┌─────────────────────────────────────┐")
    print("│     AI Spec Evolution — Stats       │")
    print("├─────────────────────────────────────┤")
    print(f"│  Tweets collected:     {stats['tweets']:>6}         │")
    print(f"│  Practices extracted:  {stats['practices']:>6}         │")
    print(f"│    └─ new:             {stats['practices_new']:>6}         │")
    print(f"│    └─ verified:        {stats['practices_verified']:>6}         │")
    print(f"│  Issues created:       {stats['issues_created']:>6}         │")
    print(f"│  Accounts tracked:     {stats['accounts_tracked']:>6}         │")
    print(f"│                                     │")
    print(f"│  Discovery:            {discovery['total_discovered']:>6}         │")
    print(f"│    └─ promoted:        {discovery['promoted']:>6}         │")
    print(f"│    └─ avg LLM score:   {discovery['avg_llm_score']:>6.2f}         │")
    print("└─────────────────────────────────────┘\n")


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
