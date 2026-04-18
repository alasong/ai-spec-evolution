"""DashScope LLM wrapper — supports both SDK and HTTP (compatible mode) calls."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Coding Plan uses dedicated endpoint: https://coding.dashscope.aliyuncs.com/v1
# Regular DashScope uses: https://dashscope.aliyuncs.com/compatible-mode/v1
# Auto-detect based on key prefix: sk-sp- → coding endpoint
DASHSCOPE_HTTP = "https://coding.dashscope.aliyuncs.com/v1"
DASHSCOPE_HTTP_STANDARD = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class LLMResult:
    text: str
    usage: dict
    finish_reason: str


class DashScopeClient:
    """DashScope client with HTTP fallback — supports qwen models.

    Auto-detects endpoint based on API key prefix:
    - sk-sp-* → Coding Plan endpoint (coding.dashscope.aliyuncs.com)
    - sk-*    → Standard DashScope endpoint (dashscope.aliyuncs.com)
    """

    def __init__(self, api_key: str, default_model: str = "qwen-plus"):
        self.api_key = api_key
        self.default_model = default_model
        # Auto-select endpoint based on key prefix
        if api_key.startswith("sk-sp-"):
            base_url = DASHSCOPE_HTTP
            logger.info("Using Coding Plan endpoint: %s", base_url)
        else:
            base_url = DASHSCOPE_HTTP_STANDARD
            logger.info("Using standard DashScope endpoint: %s", base_url)

        self.session = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> LLMResult:
        """Send a chat completion request via HTTP compatible mode."""
        model = model or self.default_model

        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        resp = self.session.post("/chat/completions", json=body)
        if resp.status_code != 200:
            raise RuntimeError(f"DashScope API error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choice = data["choices"][0]
        return LLMResult(
            text=choice["message"]["content"],
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", "unknown"),
        )

    def chat_json(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.1,
    ) -> dict:
        """Send a chat request expecting JSON response."""
        result = self.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(result.text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON from LLM: %s", result.text[:200])
            raise

    # ─── Convenience methods for pipeline stages ───────────────────────

    def classify_tweet(self, tweet_text: str, model: str | None = None) -> dict:
        """Classify a tweet into practice/noise/tool/opinion."""
        prompt = f"""Classify the following text about AI coding. Respond with JSON only.

{{
  "category": "practice" | "noise" | "tool" | "opinion",
  "confidence": 0.0-1.0,
  "reason": "one sentence explaining why"
}}

Text: {tweet_text}"""

        messages = [
            {"role": "system", "content": "You are a classifier for AI coding practices. Output JSON only."},
            {"role": "user", "content": prompt},
        ]
        return self.chat_json(messages, model=model, temperature=0.0)

    def extract_practice(self, tweet_text: str, model: str | None = None) -> dict:
        """Extract structured practice information from tweet text."""
        prompt = f"""Extract the AI coding practice from this text. Respond with JSON only.

{{
  "summary": "one-line description of the practice",
  "detail": "expanded explanation with context",
  "tags": ["relevant tags like TDD, spec-driven, agentic, etc."],
  "evidence": "quoted evidence from the original text",
  "claims": ["specific claims made that need verification"]
}}

Text: {tweet_text}"""

        messages = [
            {"role": "system", "content": "You extract structured coding practices. Output JSON only."},
            {"role": "user", "content": prompt},
        ]
        return self.chat_json(messages, model=model, temperature=0.1)

    def verify_logic(self, practice_summary: str, claims: list[str], model: str | None = None) -> dict:
        """Verify the logical soundness of a practice."""
        claims_str = "\n".join(f"- {c}" for c in claims)
        prompt = f"""Verify the logical soundness of this AI coding practice.

Practice: {practice_summary}
Claims to verify:
{claims_str}

Respond with JSON only:
{{
  "status": "verified" | "failed" | "needs_review",
  "reasoning": "step-by-step analysis of the causal chain",
  "premises_valid": true/false,
  "counter_examples_found": ["list any counter-examples or empty list"],
  "logical_gaps": ["identify any gaps in reasoning or empty list"]
}}"""

        messages = [
            {"role": "system", "content": "You are a logic verifier for AI coding practices. Output JSON only."},
            {"role": "user", "content": prompt},
        ]
        return self.chat_json(messages, model=model, temperature=0.0)
