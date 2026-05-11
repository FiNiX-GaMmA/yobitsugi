#!/usr/bin/env python3
"""
llm_client.py — Provider-agnostic LLM client.

Supports OpenAI, Anthropic, Google Gemini, Ollama, and any OpenAI-compatible endpoint
(Groq, Together, Fireworks, vLLM, LM Studio, OpenRouter, etc.). Selects a provider via
CLI flag, env var, config file, or autodetection — in that priority order.

Usage as a library:
    from llm_client import LLMClient
    client = LLMClient.from_env()
    text = client.chat("You are a helpful assistant.", "Hi!")

Usage as a CLI:
    echo "What is 2+2?" | python llm_client.py
    python llm_client.py --provider ollama --model mistral --prompt "hi"
    python llm_client.py --system "You speak only in haiku" --prompt "Describe Python"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    sys.stderr.write("requests is required: pip install requests\n")
    sys.exit(2)

# Optional: PyYAML for config file support. We degrade gracefully without it.
try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------- Provider definitions ----------------------------------------------------

# Each provider is a small adapter: it knows how to build a request and how to extract
# the assistant text from the response. Adding a new provider = adding one entry here.

@dataclass
class ProviderSpec:
    name: str
    default_model: str
    default_base_url: str
    api_key_env: str | None  # None for Ollama which is unauthenticated by default
    request_builder: str     # "openai" | "anthropic" | "google" | "ollama"


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        name="openai",
        default_model="gpt-4o-mini",
        default_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        request_builder="openai",
    ),
    "anthropic": ProviderSpec(
        name="anthropic",
        default_model="claude-sonnet-4-5",
        default_base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        request_builder="anthropic",
    ),
    "google": ProviderSpec(
        name="google",
        default_model="gemini-2.5-flash",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GOOGLE_API_KEY",
        request_builder="google",
    ),
    "ollama": ProviderSpec(
        name="ollama",
        default_model="mistral",
        default_base_url="http://localhost:11434",
        api_key_env=None,
        request_builder="ollama",
    ),
    # Catch-all for Groq, Together, Fireworks, vLLM, LM Studio, OpenRouter, etc.
    # They all speak the OpenAI chat-completions wire format.
    "openai-compatible": ProviderSpec(
        name="openai-compatible",
        default_model="",  # user MUST specify
        default_base_url="",  # user MUST specify
        api_key_env="OPENAI_COMPATIBLE_API_KEY",
        request_builder="openai",
    ),
}


# ---------- Config resolution -------------------------------------------------------

@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    temperature: float = 0.1
    max_tokens: int = 2048
    timeout: int = 120
    extra_headers: dict[str, str] = field(default_factory=dict)


def _load_config_file() -> dict[str, Any]:
    """Load ~/.yobitsugi/config.yaml if it exists. Returns {} if absent or yaml unavailable."""
    path = Path(os.path.expanduser("~/.yobitsugi/config.yaml"))
    if not path.exists() or not _HAS_YAML:
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        sys.stderr.write(f"[llm_client] warning: failed to read {path}: {e}\n")
        return {}


def _autodetect_provider() -> str | None:
    """Pick a provider based on which API key env var is set."""
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return "google"
    # If Ollama is running locally, prefer it (privacy-safe default).
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=1.5)
        if r.ok:
            return "ollama"
    except Exception:
        pass
    return None


def resolve_config(
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMConfig:
    """Resolve a complete LLMConfig from CLI > env > file > autodetect."""
    file_cfg = _load_config_file()

    # 1. provider
    provider = (
        provider
        or os.environ.get("VULN_FIXER_PROVIDER")
        or file_cfg.get("provider")
        or _autodetect_provider()
    )
    if not provider:
        raise SystemExit(
            "[llm_client] No LLM provider configured. Set one via:\n"
            "  --provider <name>\n"
            "  VULN_FIXER_PROVIDER env var\n"
            "  ~/.yobitsugi/config.yaml\n"
            "  or set one of: OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY,\n"
            "  or run a local Ollama instance on :11434.\n"
            "See references/providers.md for details."
        )
    if provider not in PROVIDERS:
        raise SystemExit(
            f"[llm_client] Unknown provider {provider!r}. "
            f"Known: {sorted(PROVIDERS)}"
        )

    spec = PROVIDERS[provider]

    # 2. model
    model = (
        model
        or os.environ.get("VULN_FIXER_MODEL")
        or file_cfg.get("model")
        or spec.default_model
    )
    if not model:
        raise SystemExit(
            f"[llm_client] Provider {provider!r} requires --model (no default)."
        )

    # 3. base_url
    base_url = (
        base_url
        or os.environ.get("VULN_FIXER_BASE_URL")
        or file_cfg.get("base_url")
        or spec.default_base_url
    )
    if not base_url:
        raise SystemExit(
            f"[llm_client] Provider {provider!r} requires --base-url (no default)."
        )

    # 4. api_key
    if spec.api_key_env:
        api_key = api_key or os.environ.get(spec.api_key_env) or file_cfg.get("api_key")
        if not api_key:
            raise SystemExit(
                f"[llm_client] Provider {provider!r} requires {spec.api_key_env} "
                f"(or --api-key, or api_key in config.yaml)."
            )
    else:
        api_key = None  # Ollama

    return LLMConfig(
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        temperature=float(file_cfg.get("temperature", 0.1)),
        max_tokens=int(file_cfg.get("max_tokens", 2048)),
        timeout=int(file_cfg.get("timeout", 120)),
        extra_headers=dict(file_cfg.get("extra_headers", {})),
    )


# ---------- Request builders --------------------------------------------------------

def _build_openai_request(
    cfg: LLMConfig, system: str, user: str
) -> tuple[str, dict, dict]:
    url = f"{cfg.base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        **cfg.extra_headers,
    }
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    body = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    return url, headers, body


def _extract_openai(response_json: dict) -> str:
    return response_json["choices"][0]["message"]["content"]


def _build_anthropic_request(
    cfg: LLMConfig, system: str, user: str
) -> tuple[str, dict, dict]:
    url = f"{cfg.base_url}/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": cfg.api_key or "",
        "anthropic-version": "2023-06-01",
        **cfg.extra_headers,
    }
    body: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    return url, headers, body


def _extract_anthropic(response_json: dict) -> str:
    # content is a list of blocks; concatenate any text blocks.
    parts = []
    for block in response_json.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def _build_google_request(
    cfg: LLMConfig, system: str, user: str
) -> tuple[str, dict, dict]:
    # Gemini puts the API key on the querystring.
    url = (
        f"{cfg.base_url}/models/{cfg.model}:generateContent"
        f"?key={cfg.api_key}"
    )
    headers = {"Content-Type": "application/json", **cfg.extra_headers}
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": cfg.temperature,
            "maxOutputTokens": cfg.max_tokens,
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return url, headers, body


def _extract_google(response_json: dict) -> str:
    candidates = response_json.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _build_ollama_request(
    cfg: LLMConfig, system: str, user: str
) -> tuple[str, dict, dict]:
    url = f"{cfg.base_url}/api/chat"
    headers = {"Content-Type": "application/json", **cfg.extra_headers}
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    body = {
        "model": cfg.model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": cfg.temperature,
            "num_predict": cfg.max_tokens,
        },
    }
    return url, headers, body


def _extract_ollama(response_json: dict) -> str:
    return response_json.get("message", {}).get("content", "")


_BUILDERS = {
    "openai": (_build_openai_request, _extract_openai),
    "anthropic": (_build_anthropic_request, _extract_anthropic),
    "google": (_build_google_request, _extract_google),
    "ollama": (_build_ollama_request, _extract_ollama),
}


# ---------- Client ------------------------------------------------------------------

class LLMClient:
    """Thin facade over the configured provider."""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        spec = PROVIDERS[cfg.provider]
        self._builder, self._extractor = _BUILDERS[spec.request_builder]

    @classmethod
    def from_env(cls, **overrides) -> "LLMClient":
        return cls(resolve_config(**overrides))

    def chat(self, system: str, user: str) -> str:
        url, headers, body = self._builder(self.cfg, system, user)
        try:
            r = requests.post(url, headers=headers, json=body, timeout=self.cfg.timeout)
        except requests.RequestException as e:
            raise RuntimeError(f"LLM request failed: {e}") from e
        if not r.ok:
            raise RuntimeError(
                f"LLM {self.cfg.provider}/{self.cfg.model} returned "
                f"{r.status_code}: {r.text[:500]}"
            )
        try:
            data = r.json()
        except ValueError as e:
            raise RuntimeError(f"LLM returned non-JSON: {r.text[:500]}") from e
        return self._extractor(data).strip()


# ---------- CLI ---------------------------------------------------------------------

def _cli() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--provider", help="openai | anthropic | google | ollama | openai-compatible")
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--api-key")
    p.add_argument("--system", default="", help="System prompt (optional)")
    p.add_argument("--prompt", help="User prompt (otherwise read from stdin)")
    p.add_argument(
        "--print-config",
        action="store_true",
        help="Resolve and print the config that would be used, then exit.",
    )
    args = p.parse_args()

    cfg = resolve_config(args.provider, args.model, args.base_url, args.api_key)
    if args.print_config:
        # Redact key for safety.
        out = {
            "provider": cfg.provider,
            "model": cfg.model,
            "base_url": cfg.base_url,
            "api_key": "***" if cfg.api_key else None,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        print(json.dumps(out, indent=2))
        return 0

    user_prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    if not user_prompt.strip():
        p.error("No prompt given (use --prompt or pipe via stdin).")

    client = LLMClient(cfg)
    print(client.chat(args.system, user_prompt))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
