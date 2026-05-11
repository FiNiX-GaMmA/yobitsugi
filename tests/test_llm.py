"""Unit tests for yobitsugi.core.llm — provider resolution + request building."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from yobitsugi.core import llm
from yobitsugi.core.llm import (
    PROVIDERS,
    LLMClient,
    LLMConfig,
    resolve_config,
)


class TestResolveConfig:
    def test_explicit_kwargs_win(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        cfg = resolve_config(
            provider="openai", model="gpt-4o", base_url="https://x.example",
            api_key="sk-test",
        )
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o"
        assert cfg.api_key == "sk-test"

    def test_env_var_used_when_no_kwarg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        cfg = resolve_config(provider="openai")
        assert cfg.provider == "openai"
        assert cfg.api_key == "env-key"

    def test_config_file_used_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {
            "provider": "openai", "api_key": "file-key", "model": "gpt-4o-mini",
        })
        cfg = resolve_config()
        assert cfg.provider == "openai"
        assert cfg.api_key == "file-key"

    def test_unknown_provider_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        with pytest.raises(SystemExit):
            resolve_config(provider="nonsense", api_key="x")

    def test_no_provider_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        monkeypatch.setattr(llm, "_autodetect_provider", lambda: None)
        with pytest.raises(SystemExit):
            resolve_config()

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        with pytest.raises(SystemExit):
            resolve_config(provider="openai")  # no key anywhere

    def test_ollama_needs_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        cfg = resolve_config(provider="ollama")
        assert cfg.provider == "ollama"
        assert cfg.api_key is None

    def test_openai_compatible_requires_model_and_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        with pytest.raises(SystemExit):
            resolve_config(provider="openai-compatible", api_key="x")  # no model

    def test_autodetect_prefers_openai_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        cfg = resolve_config()
        assert cfg.provider == "openai"


class TestProvidersRegistry:
    def test_all_expected_providers_present(self) -> None:
        for name in ("openai", "anthropic", "google", "ollama", "openai-compatible"):
            assert name in PROVIDERS

    def test_each_provider_has_required_attrs(self) -> None:
        for spec in PROVIDERS.values():
            assert spec.name
            assert spec.request_builder in ("openai", "anthropic", "google", "ollama")


class TestLLMClient:
    def _cfg(self, provider: str = "openai") -> LLMConfig:
        return LLMConfig(
            provider=provider,
            model=PROVIDERS[provider].default_model or "test-model",
            base_url=PROVIDERS[provider].default_base_url or "http://localhost",
            api_key="sk-test",
        )

    def test_chat_openai_request_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            response = MagicMock()
            response.ok = True
            response.json.return_value = {
                "choices": [{"message": {"content": "hello"}}]
            }
            return response

        monkeypatch.setattr(llm.requests, "post", fake_post)
        client = LLMClient(self._cfg("openai"))
        out = client.chat("You are helpful", "Hi")
        assert out == "hello"
        assert "chat/completions" in captured["url"]
        assert captured["headers"]["Authorization"] == "Bearer sk-test"
        assert captured["json"]["model"] == "gpt-4o-mini"
        assert captured["json"]["messages"][0]["role"] == "system"

    def test_chat_anthropic_request_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            response = MagicMock()
            response.ok = True
            response.json.return_value = {
                "content": [{"type": "text", "text": "claude-response"}]
            }
            return response

        monkeypatch.setattr(llm.requests, "post", fake_post)
        client = LLMClient(self._cfg("anthropic"))
        out = client.chat("sys", "user")
        assert out == "claude-response"
        assert "x-api-key" in captured["headers"]
        assert captured["json"]["system"] == "sys"

    def test_chat_returns_error_on_non_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = MagicMock()
        response.ok = False
        response.status_code = 401
        response.text = "Unauthorized"
        monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: response)

        client = LLMClient(self._cfg("openai"))
        with pytest.raises(RuntimeError, match="401"):
            client.chat("sys", "user")

    def test_chat_handles_non_json_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = MagicMock()
        response.ok = True
        response.json.side_effect = ValueError("not json")
        response.text = "<html>oops</html>"
        monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: response)

        client = LLMClient(self._cfg("openai"))
        with pytest.raises(RuntimeError, match="non-JSON"):
            client.chat("sys", "user")

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm, "_load_config_file", lambda: {})
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        client = LLMClient.from_env(provider="openai")
        assert isinstance(client, LLMClient)
        assert client.cfg.provider == "openai"
