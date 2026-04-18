"""Tests for DashScope HTTP client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm.dashscope import DashScopeClient


class TestDashScopeClient:
    def test_chat_success(self):
        """Test chat returns parsed LLMResult."""
        client = DashScopeClient(api_key="test-key", default_model="qwen-turbo")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        client.session = MagicMock(post=MagicMock(return_value=mock_resp))

        result = client.chat(messages=[{"role": "user", "content": "hi"}])

        assert result.text == "hello"
        assert result.usage["input_tokens"] == 10

    def test_chat_error_raises(self):
        """Test API error raises RuntimeError."""
        client = DashScopeClient(api_key="bad-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"error":"bad key"}'
        client.session = MagicMock(post=MagicMock(return_value=mock_resp))

        with pytest.raises(RuntimeError, match="401"):
            client.chat(messages=[{"role": "user", "content": "hi"}])

    def test_chat_json_parses(self):
        """Test chat_json returns parsed dict."""
        client = DashScopeClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"foo": "bar"}'}, "finish_reason": "stop"}],
            "usage": {},
        }
        client.session = MagicMock(post=MagicMock(return_value=mock_resp))

        result = client.chat_json(messages=[{"role": "user", "content": "json please"}])
        assert result == {"foo": "bar"}

    def test_chat_json_invalid_raises(self):
        """Test malformed JSON raises."""
        client = DashScopeClient(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
            "usage": {},
        }
        client.session = MagicMock(post=MagicMock(return_value=mock_resp))

        with pytest.raises(json.JSONDecodeError):
            client.chat_json(messages=[{"role": "user", "content": "bad json"}])
