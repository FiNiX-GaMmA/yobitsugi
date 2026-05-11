---
name: yobitsugi
description: |
  Use this skill when the user asks to scan a repository for security vulnerabilities,
  audit code for CVEs or hardcoded secrets, run SAST/SCA tools (bandit, semgrep, safety,
  pip-audit, eslint, npm audit, gosec, brakeman, etc.), or generate patches for known
  vulnerabilities. Also trigger when the user says things like "find security bugs in
  this project", "check for SQL injection", "audit dependencies", "fix the high-severity
  findings", or "review this repo before deployment". Do NOT use for general code review,
  refactoring, performance optimisation, style/lint issues, or non-security static
  analysis.
---

# yobitsugi

> 呼継ぎ — *"called-in joinery."* A Japanese pottery technique: when a broken vessel can't be repaired with its own fragments, pieces from a different vessel are *called in* and joined to complete the whole. The repair is honest about its origin — the foreign piece stays visible.

Scans the current repository with industry SAST/SCA tools and uses an LLM to generate patches for the findings.

## When to use

Trigger when the user wants to:

- find security bugs / vulnerabilities in a repo
- run a security audit / SAST scan / SCA scan / dependency check
- check for SQL injection, XSS, command injection, hardcoded secrets, path traversal, weak crypto, insecure deserialization, SSRF, open redirect, or known-vulnerable dependencies
- patch high-severity findings / address CVEs
- review a repo before deployment or release

Do NOT use for general code review, refactoring, performance, lint/style issues, or non-security static analysis.

## Invocation

The skill ships as the `yobitsugi` CLI. Install it with any of:

```
pipx install yobitsugi          # or: uv tool install yobitsugi
pip install yobitsugi
uvx yobitsugi <args>            # ephemeral, no install
npx yobitsugi <args>            # ephemeral, no install, JS users
```

Then in chat the user types `/yobitsugi <path>`, which expands to:

```
yobitsugi <path>                    # full pipeline, prompts before each fix
yobitsugi <path> --auto             # apply every patch without confirmation
yobitsugi <path> --severity HIGH    # filter to one severity tier
yobitsugi scan <path>               # scan-only, no LLM, no fixes
yobitsugi findings <workspace>      # pretty-print existing findings
yobitsugi rollback <workspace>      # restore all .yobitsugi.bak files
```

## Pipeline

```
detect → scan → parse → (loop: fix → apply) → tests → validate
```

| Stage | What happens |
| --- | --- |
| detect | Identifies languages in use (Python, JS/TS, Go, Java, Ruby, PHP, C/C++, Rust, Shell, ...). |
| scan | Runs the appropriate SAST/SCA tools — bandit, semgrep, safety, pip-audit, eslint, npm audit, gosec, govulncheck, brakeman, bundler-audit, phpstan, flawfinder, cppcheck, cargo-audit, shellcheck, spotbugs, trufflehog. Missing tools are skipped, not fatal. |
| parse | Normalises every scanner's output to a unified Finding schema with a stable hash-based `id`. |
| fix | For each CRITICAL/HIGH finding, asks the LLM for a unified diff. Untrusted code snippets are wrapped in `[BEGIN UNTRUSTED USER CODE]` markers in the prompt. |
| apply | Backs the file up as `<file>.yobitsugi.bak`, tries `patch -p1` then `git apply`, asks the user before applying unless `--auto`. Logs every patch to `applied.json`. |
| tests | Generates one focused regression test per applied fix, using language-appropriate templates. |
| validate | Re-runs the full scan and reports `fixed_ids`, `still_present`, `newly_introduced`. Exit code 3 if anything regressed. |

## Workspace

Everything for one run lands in `~/.yobitsugi/<repo>-<timestamp>/`:

```
languages.json     detected languages with file counts
scan_report.json   per-scanner status (ok / skipped_missing_tool / errored)
findings.json      unified, deduplicated list of vulnerabilities    ← the cracks
applied.json       rollback log — one entry per applied patch       ← the called-in pieces
validation.json    fixed_ids, still_present, newly_introduced       ← did the joins hold?
raw/*.json         original scanner outputs, untouched, for forensic review
tests/             generated regression tests (if --skip-tests not set)
```

## Finding schema

All scanners are normalised to this shape so the LLM, the apply logic, and the test generator see the same thing:

```json
{
  "id": "28b33dd29e127dbf",
  "tool": "bandit",
  "language": "Python",
  "file": "/abs/path/to/file.py",
  "line": 6,
  "end_line": 6,
  "rule_id": "B608",
  "type": "SQL_INJECTION",
  "severity": "HIGH",
  "confidence": "HIGH",
  "title": "hardcoded_sql_expressions",
  "description": "Possible SQL injection vector through string-based query construction.",
  "code_snippet": "5     # SQL injection\n6     query = ...\n7     return ...",
  "cwe": ["CWE-89"],
  "references": ["https://..."],
  "remediation_hint": null,
  "package": null,
  "fixed_version": null
}
```

`type` is one of: `SQL_INJECTION`, `XSS`, `HARDCODED_SECRET`, `COMMAND_INJECTION`, `PATH_TRAVERSAL`, `WEAK_CRYPTO`, `INSECURE_DESERIALIZATION`, `SSRF`, `OPEN_REDIRECT`, `VULNERABLE_DEPENDENCY`, `OTHER`. Auto-classified by the parser when the scanner doesn't say it explicitly.

`id` is a stable hash of `(tool, file, line, rule_id)` so the same finding gets the same id across runs — that's how `validate` computes `fixed_ids` and `still_present`.

## LLM provider

The skill calls an LLM to generate patches. Resolution order: `--provider`/`--model` flags → env vars → `~/.yobitsugi/config.yaml` → autodetect from any API key in env.

| Provider | Env var | Notes |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | Default if no other key set |
| Anthropic | `ANTHROPIC_API_KEY` | Recommended for fix quality |
| Google | `GOOGLE_API_KEY` | |
| Ollama (local) | none | Set `--provider ollama --model llama3.1:70b` |
| OpenAI-compatible | `OPENAI_API_KEY` + `OPENAI_BASE_URL` | Works for Groq, Together, Fireworks, vLLM, LM Studio, OpenRouter |

## Safety

- Refuses to run on a dirty git tree unless `--allow-dirty` is set.
- Every modified file gets a `.yobitsugi.bak` sibling before patching.
- `applied.json` is a complete rollback log — `yobitsugi rollback <workspace>` restores everything in one call.
- The model is constrained to return unified diffs only, or the literal string `# CANNOT_FIX: <reason>`. No inline edits, no destructive shell commands.
- Code snippets from the repo are wrapped in `[BEGIN/END UNTRUSTED USER CODE]` markers in prompts to mitigate prompt injection from malicious comments or strings.
- Fixes are never auto-applied unless `--auto` is explicitly passed.
- `validate` flags `newly_introduced` findings prominently — those are vulnerabilities the patches accidentally created.

## How the assistant should respond after a run

When the user invokes this skill, the assistant should:

1. Run `yobitsugi` with the user's arguments.
2. Read `findings.json` and `validation.json` from the workspace.
3. Summarise in plain prose: how many findings, by severity and type; how many fixes applied vs skipped vs `CANNOT_FIX`; what the re-scan said.
4. **Lead with the validation result.** If `newly_introduced` is non-empty, flag it loudly — those need human review.
5. Don't paste large JSON in the chat. Point to the workspace path for raw outputs.
6. Don't auto-apply fixes unless the user explicitly asked.

## Extension points

| To add... | Edit |
| --- | --- |
| A new scanner | `yobitsugi/data/scanners.yaml` (one YAML block) |
| A new parser | `yobitsugi/core/parse.py` — see `data/parser_recipes.md` |
| A new LLM provider | `yobitsugi/core/llm.py` — three functions + one dict entry |
| A new vulnerability type | `yobitsugi/data/fix_prompts.md` + `test_templates.md` |
| A new AI assistant integration | `yobitsugi/installers/<name>.py` — subclass `Installer`, decorate `@register` |

See `ARCHITECTURE.md` for module responsibilities and pipeline detail.
