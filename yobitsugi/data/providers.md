# LLM Provider Reference

`llm_client.py` is the single seam between the skill and any LLM. Configure it once
and every worker downstream (`generate_fix.py`, `generate_tests.py`) uses the same
provider transparently.

## Resolution order

The client picks settings in this order; the first match wins:

1. **CLI flags:** `--provider`, `--model`, `--base-url`, `--api-key`
2. **Environment vars:** `VULN_FIXER_PROVIDER`, `VULN_FIXER_MODEL`, `VULN_FIXER_BASE_URL`,
   plus the provider's standard key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
   `GOOGLE_API_KEY`)
3. **Config file:** `~/.yobitsugi/config.yaml` (see `config.example.yaml`)
4. **Autodetect:** picks based on which API key env var is set; falls back to
   a running local Ollama on `:11434`

Run `python scripts/llm_client.py --print-config` to see exactly what was resolved.

## Supported providers

### `openai`
- Default model: `gpt-4o-mini` (cheap, fast, good enough for diffs)
- Env: `OPENAI_API_KEY`
- Base URL: `https://api.openai.com/v1`
- Wire format: standard chat-completions

### `anthropic`
- Default model: `claude-sonnet-4-5`
- Env: `ANTHROPIC_API_KEY`
- Base URL: `https://api.anthropic.com/v1`
- Wire format: Anthropic Messages API (`x-api-key` header, `anthropic-version: 2023-06-01`)

### `google`
- Default model: `gemini-2.5-flash`
- Env: `GOOGLE_API_KEY` (or `GEMINI_API_KEY` for autodetect)
- Base URL: `https://generativelanguage.googleapis.com/v1beta`
- Wire format: Gemini `generateContent`; key on querystring

### `ollama` (local)
- Default model: `mistral` (or whatever you've pulled — `llama3.1`, `qwen2.5-coder`, etc.)
- Env: none required
- Base URL: `http://localhost:11434`
- Setup: `ollama pull <model>` then `ollama serve`
- **This is the right choice for sensitive code** — nothing leaves the box.

### `openai-compatible`
The catch-all. Works with any service that speaks the OpenAI chat-completions wire
format — Groq, Together, Fireworks, OpenRouter, Anyscale, DeepInfra, vLLM, LM Studio,
LocalAI, llama.cpp's server, etc. You **must** specify `--model` and `--base-url`
since there's no sensible default.

Env var for the key: `OPENAI_COMPATIBLE_API_KEY`.

Examples:

```bash
# Groq
export OPENAI_COMPATIBLE_API_KEY=gsk_...
python scripts/llm_client.py --provider openai-compatible \
  --base-url https://api.groq.com/openai/v1 --model llama-3.3-70b-versatile --prompt hi

# Local vLLM
python scripts/llm_client.py --provider openai-compatible \
  --base-url http://localhost:8000/v1 --model your-model --prompt hi

# OpenRouter (routes to many providers)
export OPENAI_COMPATIBLE_API_KEY=sk-or-...
python scripts/llm_client.py --provider openai-compatible \
  --base-url https://openrouter.ai/api/v1 \
  --model anthropic/claude-3.5-sonnet --prompt hi
```

## Adding a new provider with a non-OpenAI wire format

If a provider doesn't speak OpenAI-compatible JSON, add a new request builder:

1. In `scripts/llm_client.py`, write `_build_<name>_request(cfg, system, user)`
   returning `(url, headers, body)`.
2. Write `_extract_<name>(response_json) -> str`.
3. Register both in the `_BUILDERS` dict.
4. Add a `ProviderSpec` entry to `PROVIDERS` and (if needed) a default API-key env var.

The diff for adding a new provider is usually <30 lines.

## Picking a model for fix generation

The fix generator works best with models that handle code well and follow
"output only a diff" instructions reliably. Roughly, in order of how reliably
they emit clean unified diffs in my experience:

1. **Top tier (very reliable):** `claude-sonnet-4-5`, `gpt-4o`, `claude-opus-4-5`
2. **Solid:** `gpt-4o-mini`, `gemini-2.5-flash`, `llama-3.3-70b-versatile`
3. **Workable with cleanup:** small local models (`mistral`, `qwen2.5-coder:7b`,
   `llama3.1:8b`) — they'll often wrap diffs in markdown fences. `generate_fix.py`
   strips those, but expect more failed-patch attempts.

For high-stakes codebases, prefer top-tier on a small subset and validate by re-running
the scanner. For exploration on huge codebases, smaller/faster models are fine because
`validate.py` catches bad fixes.

## Cost / latency notes

- Each `generate_fix.py` call is ~1–2k input tokens, ~200–500 output. At gpt-4o-mini
  rates that's well under a cent per finding.
- `generate_tests.py` is comparable.
- The big-ticket call is when you triage hundreds of findings. Filter aggressively
  (start with CRITICAL + HIGH) and prove the pipeline works before scaling.

## Common failure modes

- **401 / 403:** key env var not set or wrong. Run `--print-config` to see what
  the client resolved.
- **Model not found:** model id is per-provider — `gpt-4o-mini` won't work on Groq;
  `mistral` won't work on OpenAI.
- **Empty response:** some local models occasionally return "" with no error. The
  generator treats that as "no fix"; rerun or switch model.
- **Network egress blocked:** in restricted environments the only viable option is
  `ollama` or a local OpenAI-compatible endpoint.
