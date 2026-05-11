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

## Before running anything — enter plan mode if supported

`yobitsugi run` modifies files in the user's working tree (it applies LLM-generated patches and writes `.yobitsugi.bak` backups). That's a destructive operation. If the assistant's harness has a plan-mode / dry-run concept, enter it BEFORE invoking yobitsugi so the user can preview and approve.

| Assistant | How to enter plan mode |
| --- | --- |
| **Claude Code** | Call the `ExitPlanMode` tool with a written plan first (the canonical Claude Code plan-mode pattern). User must approve before any tool that modifies the filesystem runs. |
| **Codex** | Use Codex's planning workflow — set `approval_mode = "on-failure"` (or `"never"`) in `~/.codex/config.toml` only after approval, and present the plan first. Per the OpenAI Codex best-practices guide (developers.openai.com/codex/learn/best-practices), Codex supports a plan-first workflow where you write the plan as a structured message, surface it for user approval, then execute. Use Codex's read-only `approval_mode = "read-only"` while drafting the plan, switch to `"on-failure"` after approval to apply patches. |
| **Cursor** | Use Agent mode's review step; present the plan as a message and wait for approval. |
| **Aider / Gemini CLI / OpenCode** | No formal plan mode — instead, write the plan as a chat message and explicitly ask the user *"Should I proceed?"* before invoking yobitsugi. Wait for an affirmative reply. |
| **GitHub Copilot CLI** | Show the planned `yobitsugi` command and ask the user to confirm before executing. |

The plan should cover: which path will be scanned, what severity threshold will be applied, whether `--auto` is being passed, and (if `yobitsugi install-scanners` is needed first) the install commands that will run. After approval, exit plan mode and run yobitsugi. Apply this in plan mode for **`yobitsugi run`** and for **`yobitsugi install-scanners`** — both have side effects. `yobitsugi scan` (read-only) does not need plan mode.

## How the assistant should respond after a run

When the user invokes this skill, the assistant should:

1. Run `yobitsugi` with the user's arguments.
2. Read `findings.json`, `validation.json`, **and `scan_report.json`** from the workspace.
3. **Render the structured summary in chat.** Run `yobitsugi summary <workspace> --format markdown` and surface the output verbatim — it contains five markdown tables (Run totals, Findings by severity, Findings, Missing scanners, What next?) which most clients render natively. If markdown tables don't render in the user's client, fall back to `--format json` and rebuild the same tables yourself.
4. **Check `scan_report.json` for `status: "skipped_missing_tool"` entries.** If any exist, before summarising findings:
   - Tell the user *which* scanners were skipped and why (binary not installed).
   - Split them into auto-installable (those with `install_method: "pip"`) and manual (everything else, which carries an `install_hint` field).
   - Ask the user: *"X scanners aren't installed (semgrep, bandit, …). Want me to install the auto-installable ones into yobitsugi's isolated venv (`yobitsugi install-scanners`), and/or run the install commands for the manual ones?"*
   - If they say yes to the auto-installable group, run `yobitsugi install-scanners` and then re-run the original `yobitsugi` command.
   - If they say yes to the manual ones, run the `install_hint` commands one at a time (each is a single shell command). Confirm before re-running yobitsugi.
   - If they decline, proceed to step 4 against whatever findings were collected — make clear that the picture is partial.
5. **Lead with the validation result.** If `newly_introduced` is non-empty, flag it loudly — those need human review. The summary's "Newly introduced" section is already styled prominently; quote it.
6. **Present the "What next?" table as a choice menu** and ask the user which row to act on. Example:
   *"I see 3 next-action options — 1) install missing scanners, 2) accept and git-commit, 3) re-scan only. Which would you like?"* Then run the corresponding command from the table.
7. Don't paste raw JSON in the chat unless the user asks. Point to the workspace path for inspection.
8. Don't auto-apply fixes (and don't run installs) without explicit confirmation from the user.

### Scanner installation, in detail

`yobitsugi install-scanners` creates and manages an isolated venv at `~/.yobitsugi/tools/venv/`. It only handles Python-installable scanners (bandit, safety, pip-audit, semgrep, flawfinder) — installing them there never touches the user's main Python environment. After install, the venv's `bin/` is auto-prepended to `PATH` for every scanner subprocess, so `yobitsugi scan` / `yobitsugi run` find the tools without further configuration.

For non-Python scanners (eslint via npm, gosec via go install, brakeman via gem, shellcheck via brew/apt, etc.), the assistant should use its own shell tool to run the install commands. They're not in yobitsugi's sandbox because each one needs a different runtime that's outside Python's scope.

`yobitsugi list-scanners` prints the full table (method, installed status, package or hint) — useful when the user asks "what *can* yobitsugi run?"
`yobitsugi uninstall-scanners` wipes `~/.yobitsugi/tools/` entirely.

## Extension points

| To add... | Edit |
| --- | --- |
| A new scanner | `yobitsugi/data/scanners.yaml` (one YAML block) |
| A new parser | `yobitsugi/core/parse.py` — see `data/parser_recipes.md` |
| A new LLM provider | `yobitsugi/core/llm.py` — three functions + one dict entry |
| A new vulnerability type | `yobitsugi/data/fix_prompts.md` + `test_templates.md` |
| A new AI assistant integration | `yobitsugi/installers/<name>.py` — subclass `Installer`, decorate `@register` |

See `ARCHITECTURE.md` for module responsibilities and pipeline detail.
