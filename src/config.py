"""Configuration loader for ai-spec-evolution."""

import os
from pathlib import Path
from dataclasses import dataclass, field

import yaml


@dataclass
class TwitterConfig:
    bearer_token: str = ""
    accounts_file: str = "data/accounts.yaml"
    fetch_limit: int = 20
    fetch_since_days: int = 7

@dataclass
class DashScopeConfig:
    api_key: str = ""
    filter_model: str = "qwen-turbo"
    analysis_model: str = "qwen-plus"
    verification_model: str = "qwen-max"

@dataclass
class GitHubConfig:
    token: str = ""
    target_repo: str = "alasong/ai-coding-standards"
    spec_docs_dir: str = "ai-coding-v5.4"

@dataclass
class PipelineConfig:
    twitter: TwitterConfig = field(default_factory=TwitterConfig)
    dashscope: DashScopeConfig = field(default_factory=DashScopeConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)
    data_dir: str = "data"
    run_mode: str = "full"  # full | filter-only | verify-only

@dataclass
class AppConfig:
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)

    @classmethod
    def from_file(cls, path: str = "config.yaml") -> "AppConfig":
        config_path = Path(path)
        if config_path.exists():
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        # Merge env vars (env takes precedence)
        twitter = raw.get("twitter", {})
        twitter.setdefault("bearer_token", os.getenv("TWITTER_BEARER_TOKEN", ""))

        dashscope = raw.get("dashscope", {})
        dashscope.setdefault("api_key", os.getenv("DASHSCOPE_PRO", ""))

        github = raw.get("github", {})
        github.setdefault("token", os.getenv("GITHUB_TOKEN", ""))

        pipeline = PipelineConfig(
            twitter=TwitterConfig(**twitter),
            dashscope=DashScopeConfig(**dashscope),
            github=GitHubConfig(**github),
            data_dir=raw.get("data_dir", "data"),
            run_mode=raw.get("run_mode", "full"),
        )
        return cls(pipeline=pipeline)

    def validate(self) -> list[str]:
        errors = []
        if not self.pipeline.dashscope.api_key:
            errors.append("DASHSCOPE_PRO env var is required")
        # Twitter token is optional — empty token triggers mock data mode
        return errors


def load_config(path: str = "config.yaml") -> AppConfig:
    config = AppConfig.from_file(path)
    errs = config.validate()
    if errs:
        raise RuntimeError(f"Configuration errors: {'; '.join(errs)}")
    return config
