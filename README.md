# AI Spec Evolution

Automatically discover, verify, and propose AI coding best practices from social media.

> **Philosophy**: Don't blindly aggregate. Every practice must pass through logic verification, project-level evidence, and human review before becoming part of the spec.

## Architecture

```
Twitter Accounts (curated)        Weibo Accounts (future)
        │                                  │
        ▼                                  ▼
┌──────────────────────────────────────────────────────┐
│  L1: Collect  →  L2: Filter/Extract                  │
│  Timeline fetch    LLM classify (practice/noise)     │
│  Incremental       Structured extraction             │
└───────────────────────┬──────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────┐
│  L3: Dedup + Gap Analysis                            │
│  - Semantic dedup against open issues                │
│  - Map to existing spec document                     │
└───────────────────────┬──────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────┐
│  L4: Verification Engine                             │
│  4a. Logic: causal chain, premises, counter-examples  │
│  4b. Project: fork spec repo, apply, run CI           │
└───────────────────────┬──────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────┐
│  L5: Issue Generator                                 │
│  GitHub Issue with full evidence chain                │
└──────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install

```bash
git clone <your-repo-url>
cd ai-spec-evolution
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp config.example.yaml config.yaml
```

Required environment variables:

| Variable | Description |
|----------|-------------|
| `DASHSCOPE_PRO` | DashScope API key (阿里云灵积) |
| `TWITTER_BEARER_TOKEN` | Twitter API v2 Bearer Token |
| `GITHUB_TOKEN` | GitHub PAT with `issues:write` permission |

### 3. Run

```bash
# Full pipeline
python -m src.cli run

# Individual stages
python -m src.cli collect
python -m src.cli filter
python -m src.cli verify
python -m src.cli issue
```

## Twitter Account Management

Curated accounts are defined in `data/accounts.yaml`. The system periodically refreshes trust scores:

```yaml
accounts:
  - handle: "karpathy"
    name: "Andrej Karpathy"
    expertise: ["deep-learning", "training"]
    trust_score: 0.9
    added_reason: "Deep learning pioneer"
    active: true
```

- Accounts with `trust_score < 0.2` are auto-deactivated
- Run `python -m src.cli accounts` to manage accounts
- New accounts start at `trust_score: 0.5`

## Verification Levels

| Level | What it checks | Result |
|-------|----------------|--------|
| **Logic** | Causal chain, premises, counter-examples | verified / failed / needs_review |
| **Project** | Fork spec repo, apply change, run CI | verified / failed / needs_review |
| **Final** | Combined verdict | verified → issue created |

Only `verified` or high-confidence `needs_review` practices generate GitHub issues.

## Project Structure

```
ai-spec-evolution/
├── src/
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # Configuration loader
│   ├── collector/
│   │   ├── twitter.py             # Twitter API v2 collector
│   │   └── account_manager.py     # Curated account manager
│   ├── llm/
│   │   └── dashscope.py           # DashScope (Qwen) wrapper
│   ├── models/
│   │   └── practice.py            # Data models
│   ├── processor/
│   │   ├── filter.py              # L1 Filter + L2 Extractor
│   │   └── dedup.py               # L3 Dedup + Gap Analysis
│   ├── verifier/
│   │   ├── logic_validator.py     # L4a Logic verification
│   │   └── fork_runner.py         # L4b Project verification
│   └── generator/
│       └── issue.py               # L5 Issue generator
├── data/                          # Runtime data (gitignored)
│   ├── accounts.yaml              # Curated Twitter accounts
│   ├── collected/                 # Raw collected tweets
│   ├── filtered/                  # Filtered practices (JSONL)
│   └── verified/                  # Verification results
├── .github/workflows/
│   └── spec-evolution.yml         # GitHub Actions (Mon/Wed/Fri)
└── config.example.yaml            # Configuration template
```

## Twitter API Setup

1. Visit https://developer.twitter.com/
2. Sign in with your Twitter account
3. Apply for **Free** tier (500K reads/month)
4. Create an App → copy the **Bearer Token**
5. Add to your environment: `export TWITTER_BEARER_TOKEN=AAAA...`

Approval typically takes 1-3 days.

## License

MIT
