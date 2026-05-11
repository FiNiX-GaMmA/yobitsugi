<p align="center">
  <h1 align="center">yobitsugi</h1>
  <p align="center"><em>呼継ぎ — "called-in joinery."</em></p>
</p>

<p align="center">
  <a href="https://github.com/FiNiX-GaMmA/yobitsugi/actions/workflows/ci.yml"><img src="https://github.com/FiNiX-GaMmA/yobitsugi/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://pypi.org/project/yobitsugi/"><img src="https://img.shields.io/pypi/v/yobitsugi?label=pypi&color=blue&cacheSeconds=3600" alt="PyPI"/></a>
  <a href="https://pypi.org/project/yobitsugi/"><img src="https://img.shields.io/pypi/pyversions/yobitsugi?color=blue&cacheSeconds=3600" alt="Python versions"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/pypi/l/yobitsugi?color=green&cacheSeconds=3600" alt="License: MIT"/></a>
  <a href="https://github.com/FiNiX-GaMmA"><img src="https://img.shields.io/github/followers/FiNiX-GaMmA?label=Follow%20%40FiNiX-GaMmA&style=flat&color=blue&cacheSeconds=3600" alt="GitHub followers"/></a>
</p>

<p align="center">
  <a href="https://star-history.com/#FiNiX-GaMmA/yobitsugi&Date">
    <img src="https://api.star-history.com/svg?repos=FiNiX-GaMmA/yobitsugi&type=Date" alt="Star History Chart" width="370"/>
  </a>
</p>

Type `/yobitsugi` in your AI coding assistant and it scans your repo with industry SAST/SCA tools, then walks you through fixes one at a time using your assistant's own model.

Works in Claude Code, Codex, Cursor, Gemini CLI, Aider, OpenCode, and GitHub Copilot CLI.

```
/yobitsugi .
```

That's it. You get a workspace dir:

```
~/.yobitsugi/<repo>-<timestamp>/
├── findings.json     unified, deduplicated list of vulnerabilities    ← the cracks
├── scan_report.json  per-scanner status (ok / skipped_missing_tool / errored)
├── languages.json    detected languages with file counts
└── raw/*             original scanner outputs, untouched, for forensic review
```

Your assistant then reads `findings.json`, summarises it in chat, proposes a unified diff for each CRITICAL/HIGH finding, asks before applying, and applies the edit with its own native edit tool. There's no separate LLM for yobitsugi — your editor's model does all the talking.

---

## Install

**Requires Python 3.11+**

```bash
pipx install yobitsugi && yobitsugi install
# or: uv tool install yobitsugi && yobitsugi install
# or: pip install yobitsugi && yobitsugi install
# or: uvx yobitsugi <args>   (ephemeral, no install)
```

> **`yobitsugi: command not found`?** Use `pipx install yobitsugi` or `uv tool install yobitsugi` — both put the CLI on PATH automatically. With plain `pip`, add `~/.local/bin` (Linux) or `~/Library/Python/3.x/bin` (Mac) to your PATH, or run `python -m yobitsugi`.

> **PowerShell note:** Use `yobitsugi scan .` not `/yobitsugi .` outside an assistant chat — the leading slash is a path separator in PowerShell.

> **Codex note:** Add `multi_agent = true` under `[features]` in `~/.codex/config.toml`. Codex uses `$yobitsugi` instead of `/yobitsugi`.

### Pick your platform

| Platform | Install command |
|----------|-----------------|
| Claude Code | `yobitsugi install --platform claude` |
| Codex | `yobitsugi install --platform codex` |
| Cursor | `yobitsugi install --platform cursor --scope project` |
| Gemini CLI | `yobitsugi install --platform gemini` |
| Aider | `yobitsugi install --platform aider` |
| OpenCode | `yobitsugi install --platform opencode` |
| GitHub Copilot CLI | `yobitsugi install --platform copilot` |

Bare `yobitsugi install` auto-detects every assistant on your machine and registers the skill for each. Add `--scope project` to install into the current repo instead of your home dir. Remove with `yobitsugi uninstall --platform <name>`. List everything with `yobitsugi list-platforms`.

---

## What the skill does

When you type `/yobitsugi <path>`, the host assistant follows a five-step runbook installed as a markdown skill file. It's exactly what a careful security review looks like:

1. **Announces the plan** and asks if you want to proceed. A throwaway scanner venv will be created and deleted at the end of the run — your system Python stays untouched.
2. **Runs `yobitsugi scan <path> --ephemeral-tools`** which detects languages, runs every matching SAST/SCA scanner, normalises the output to `findings.json`, and prints a markdown summary.
3. **Asks if you want fixes.** Shows the totals (CRITICAL / HIGH / MEDIUM / LOW) and the markdown table of every finding.
4. **Walks each finding interactively.** For every CRITICAL/HIGH finding: one-paragraph plain-English explanation, proposed unified diff inline, then "Apply this fix?" — yes/no/skip/explain-more. The assistant uses its own model and its own native edit tool. The `yobitsugi` binary never edits a file.
5. **Re-scans to confirm.** Compares finding ids before and after: any ids gone are *fixed*, any still present are *unresolved*, any new ones are *regressions* the assistant's edits introduced. Flags regressions loudly.

The temp scanner venv is removed in a `finally` block at the end — on success, failure, or Ctrl-C alike.

---

## What scanners it runs

Auto-detected per language. Missing binaries are skipped, not fatal — most are installed for you automatically when you pass `--ephemeral-tools` (which is what the slash command uses).

| Language | Scanners |
|----------|----------|
| Python | `bandit`, `safety`, `pip-audit`, `semgrep` |
| JavaScript / TypeScript | `eslint` (security plugins), `npm audit`, `semgrep` |
| Go | `gosec`, `govulncheck`, `semgrep` |
| Java | `spotbugs` (with FindSecBugs), `semgrep` |
| Ruby | `brakeman`, `bundler-audit`, `semgrep` |
| PHP | `phpstan` (security), `semgrep` |
| C / C++ | `flawfinder`, `cppcheck`, `semgrep` |
| Rust | `cargo-audit`, `semgrep` |
| Shell | `shellcheck`, `semgrep` |
| Cross-language | `semgrep`, `trufflehog` (secrets) |

### What ships in the wheel

`pip install yobitsugi` pulls these onto your `PATH` automatically — no extra step:

| Scanner | How it's bundled |
|---------|------------------|
| `bandit` | direct dep |
| `safety` | direct dep (pinned `>=3.0,<3.2` to dodge the `safety` ↔ `typer` ↔ `click 8.2` import crash; `click<8.2` is also pinned alongside) |
| `pip-audit` | direct dep |
| `semgrep` | direct dep |
| `flawfinder` | direct dep |
| `shellcheck` | direct dep via [`shellcheck-py`](https://github.com/shellcheck-py/shellcheck-py) — the Haskell binary is wrapped in a Python wheel, so `pip` puts a real `shellcheck` executable on `PATH` |
| `trufflehog` | **fetched on demand** when you pass `--ephemeral-tools`: the Go binary is downloaded from the official GitHub release into the same temp dir as the scanner venv, and is removed at the end of the run. No `brew install` step. See "Trufflehog" below for the persistent variant. |
| `eslint` + `eslint-plugin-security` | **`npm install`ed on demand** when you pass `--ephemeral-tools` and the repo has JS/TS code. Drops into `<tmp>/node/node_modules/.bin/` next to the venv; cleaned up at the end of the run. Requires `npm` on the host (Node.js — yobitsugi can't bootstrap that). A bundled fallback eslint config is used when your repo has none of its own. See "ESLint" below. |

Non-Python scanners that aren't ours to bundle — `eslint`, `npm audit`, `gosec`, `govulncheck`, `brakeman`, `bundler-audit`, `phpstan`, `cppcheck`, `cargo-audit`, `spotbugs` — need their own runtime (Node / Go / Ruby / etc.). `yobitsugi list-scanners` shows the install hint for each.

Adding a new scanner is one YAML block in [`yobitsugi/data/scanners.yaml`](yobitsugi/data/scanners.yaml) — no code change needed unless the output format is exotic.

### Parallel scanning

`yobitsugi scan` runs scanners on a thread pool so bandit, semgrep, pip-audit, trufflehog, shellcheck etc. all execute concurrently. Each scanner is a subprocess waiting on its own child process — threads are the right shape (no GIL contention) and the wall-clock time is `max(scanner_times)`, not `sum`.

```bash
yobitsugi scan ./my-project --concurrency 8   # cap at 8 in-flight (default: 6)
yobitsugi scan ./my-project --sequential       # force one-at-a-time (debugging)
YOBITSUGI_SCAN_CONCURRENCY=4 yobitsugi scan ./my-project   # env-var equivalent
```

Output streams as scanners finish:

```
[scan] concurrency: 6 parallel workers
  → bandit          dispatched
  → semgrep         dispatched
  → pip-audit       dispatched
  → trufflehog      dispatched
  ✓ bandit          ok                      0.2s
  ✓ trufflehog      ok                      3.1s
  ✓ pip-audit       ok                     25.4s
  ✓ semgrep         ok                     31.7s
[scan] all scanners done in 31.7s
```

### ESLint (JS / TypeScript)

ESLint is a Node.js tool — no PyPI wrapper exists, so it can't go inside the Python venv. Same workaround as trufflehog: when `yobitsugi scan --ephemeral-tools` detects JavaScript or TypeScript in the repo, it `npm install`s `eslint@^8.57 eslint-plugin-security@^3 @typescript-eslint/parser@^7 @typescript-eslint/eslint-plugin@^7` into the temp tools dir (next to the Python venv) and adds the resulting `node_modules/.bin/` to `PATH` for the scan. The whole thing is cleaned up in the `finally` block.

The only requirement on the host is `npm`. If it's not on PATH, yobitsugi prints an install hint (`brew install node` / `apt-get install nodejs npm` / nodejs.org) and the scan continues with eslint marked `skipped_missing_tool`. Node itself isn't auto-installable — it's a 100MB+ runtime that needs an OS-level package manager.

If your repo already has an eslint config (`.eslintrc.*`, `eslint.config.{js,mjs,cjs}`, or an `eslintConfig` block in `package.json`), eslint uses it. If not, yobitsugi falls back to the bundled config at [`yobitsugi/data/eslint-security.eslintrc.json`](yobitsugi/data/eslint-security.eslintrc.json) — eslint v8 schema, loads `eslint-plugin-security/recommended-legacy`, with a TypeScript override that pulls in `@typescript-eslint/parser`. That guarantees a vanilla JS/TS repo still produces findings instead of silently reporting "no issues".

For a persistent install (CI image, offline runners), use `bootstrap`:

```bash
yobitsugi bootstrap eslint                   # npm install -g eslint + plugins
yobitsugi bootstrap --dry-run eslint         # preview the command
```

Or pass `--no-fetch-native` to opt out of the auto-install at scan time (e.g. if you've already done `bootstrap` and want a faster startup).

### Trufflehog (persistent install)

The ephemeral fetch in `--ephemeral-tools` is enough for one-off runs and CI. If you'd rather have trufflehog stick around between runs (faster startup, works offline), use `bootstrap`:

```bash
yobitsugi bootstrap                       # auto-picks brew / apt / dnf / yum
yobitsugi bootstrap --dry-run             # print the install command without running it
yobitsugi bootstrap trufflehog            # be explicit about what to install
```

`bootstrap` runs the system package manager that's actually on PATH (in order: `brew`, `apt-get`, `dnf`, `yum`). On platforms without any of those, it prints the install URL.

If trufflehog is already on PATH (either via `bootstrap` or your own install), pass `--no-fetch-native` to `yobitsugi scan` to skip the download:

```bash
yobitsugi scan ./my-project --ephemeral-tools --no-fetch-native
```

---

## What's in the summary

`yobitsugi summary <workspace> --format markdown` (which the skill runs for you) prints five tables:

- **Run totals** — findings count, scanners ok / skipped / errored.
- **Findings by severity** — counts per CRITICAL / HIGH / MEDIUM / LOW.
- **Findings** — one row per finding: severity, type, scanner, file:line, title.
- **Missing scanners** — every scanner that was skipped because its binary isn't installed, with the install command or hint.
- **What next?** — ranked next actions: install missing scanners, hand findings to the assistant for the fix loop, re-scan to validate.

Every finding has a stable `id` (a hash of `tool` + `file` + `line` + `rule_id`) so a re-scan computes a clean fixed / still-present / newly-introduced diff against the previous one.

---

## Ephemeral tools mode

`--ephemeral-tools` is the recommended path for slash-command invocations and CI jobs. With that flag, `yobitsugi scan`:

1. Creates a fresh temp directory and redirects its managed scanner venv there for the duration of the command.
2. Detects the repo's languages and installs **only the pip scanners the repo actually needs** — semgrep won't be pulled into a Bash-only repo, bandit won't be pulled into a Go-only repo.
3. Downloads the right **trufflehog** release binary for your platform into the same temp dir. trufflehog is a Go binary and can't live inside a Python venv, but the temp tools dir is on the same lifecycle — `tempfile.mkdtemp` on entry, `shutil.rmtree` in the `finally`. Skip with `--no-fetch-native` if you've already got it on `PATH` (e.g. from `yobitsugi bootstrap`).
4. If JS/TS files were detected, `npm install`s **eslint** + the security and TypeScript plugins into `<tmp>/node/node_modules/` — same temp dir, same cleanup. Requires `npm` on the host. Falls back to the bundled eslint security config when your repo has none of its own. Skip with `--no-fetch-native`.
5. Runs the scan against the throwaway venv — scanners run in parallel via a thread pool (see "Parallel scanning" above). `PATH` is auto-prepended so the temp scanners shadow anything on the system.
6. Deletes the temp directory in a `finally` block. Your `~/.yobitsugi/tools/` is never touched.

```bash
yobitsugi scan ./services/api --ephemeral-tools
yobitsugi scan ./services/api --ephemeral-tools --no-fetch-native    # offline / already-bootstrapped
```

If you'd rather pay the install cost once and keep scanners around, use `yobitsugi install-scanners` (pip scanners → `~/.yobitsugi/tools/venv/`) and `yobitsugi bootstrap` (trufflehog → system package manager) instead.

---

## Common commands

```bash
/yobitsugi .                                     # inside any supported assistant — the skill drives everything
/yobitsugi . --severity CRITICAL                 # filter the fix loop the assistant will run
/yobitsugi . --auto                              # skip per-fix confirmation (assistant still shows each diff)

# Standalone binary usage (CI, headless audits, scripting):
yobitsugi scan ./services/api                    # scan, write findings.json
yobitsugi scan ./services/api --ephemeral-tools  # …with throwaway scanner venv + auto-fetched trufflehog
yobitsugi scan ./services/api --concurrency 8    # parallel scanners, cap 8 in-flight (default 6)
yobitsugi scan ./services/api --sequential       # force one-at-a-time (debugging)
yobitsugi scan ./services/api --only bandit semgrep   # restrict to specific scanners
yobitsugi scan ./services/api --no-fetch-native  # skip the trufflehog download (you have it already)
yobitsugi findings ~/.yobitsugi/<workspace>      # pretty-print existing findings
yobitsugi findings <ws> --severity HIGH --json   # JSON for piping
yobitsugi summary <ws> --format markdown         # the same markdown tables the assistant sees
yobitsugi summary <ws> --format json             # structured data for tooling

yobitsugi install                                # register skill files in every detected AI editor
yobitsugi install --platform claude              # only Claude Code
yobitsugi uninstall                              # remove from all platforms in one shot

yobitsugi list-platforms                         # show all supported assistants
yobitsugi detect-platforms                       # only the ones installed on this machine

yobitsugi list-scanners                          # every scanner + install status
yobitsugi install-scanners                       # persistent install of pip scanners into ~/.yobitsugi/tools/venv/
yobitsugi install-scanners --all                 # force reinstall/upgrade all of them
yobitsugi uninstall-scanners                     # wipe the managed venv
yobitsugi bootstrap                              # persistent install of native scanners (trufflehog, eslint) via brew/apt/dnf/yum/npm
yobitsugi bootstrap eslint                       # just eslint (npm install -g)
yobitsugi bootstrap --dry-run                    # preview the install command without running it
```

There is no `yobitsugi run`, no `yobitsugi fix`, no `yobitsugi apply`, no `yobitsugi rollback`, no `yobitsugi config`. Those used to be CLI subcommands; they're now the host AI assistant's job, driven by the installed skill.

---

## Skipping files

Most scanners walk the tree themselves, and yobitsugi excludes the common environment and build dirs by default (`.venv`, `venv`, `node_modules`, `.tox`, `build`, `dist`, `site-packages`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `target`, `vendor`, `third_party`, …) for `bandit` and `semgrep`.

For per-project overrides, drop the scanner's own ignore file:

- **bandit** — `.bandit` or `bandit.yaml` in the repo root
- **semgrep** — `.semgrepignore`
- **eslint** — `.eslintignore`
- **trufflehog** — respects `.gitignore` automatically (Go binary)

If you need to add a directory to yobitsugi's defaults, edit the `command:` line in [`yobitsugi/data/scanners.yaml`](yobitsugi/data/scanners.yaml).

---

## Team setup

The workspace dir at `~/.yobitsugi/<repo>-<ts>/` is local to your run — don't commit it. The audit trail is your chat transcript.

Recommended flow:

1. One developer (or CI) runs `/yobitsugi .` and triages the findings their assistant proposes.
2. They commit only the source changes the assistant applied (no workspace dir).
3. CI runs `yobitsugi scan . --ephemeral-tools` on every PR and fails the build if new CRITICAL/HIGH findings appear (use `yobitsugi findings <ws> --severity CRITICAL HIGH --json` to assert in your pipeline).
4. When a scanner is missing (`status: "skipped_missing_tool"` in `scan_report.json`), the assistant offers to install it. For CI, install the non-pip ones (`shellcheck`, `trufflehog`, `gosec`, etc.) in the build image and let `--ephemeral-tools` handle the pip ones.

---

## Privacy

- **Scanner output** stays on your machine. The `yobitsugi` binary never makes a network call.
- **Fix generation** happens in your AI editor — your model, your API key, your billing. Yobitsugi has no LLM client of its own.
- **Untrusted code snippets** in `findings.json`'s `code_snippet` field are marked as data in the skill prompt to mitigate prompt injection from malicious comments or string literals in scanned files.
- No telemetry, no usage tracking, no analytics.

---

## Full command reference

```
yobitsugi scan <path>                            # detect → run scanners (parallel) → parse to findings.json
yobitsugi scan <path> --ephemeral-tools          # …in a throwaway venv that's deleted on exit (auto-fetches trufflehog)
yobitsugi scan <path> --concurrency N            # cap parallel scanners (default 6, env: YOBITSUGI_SCAN_CONCURRENCY)
yobitsugi scan <path> --sequential               # disable parallelism (debugging)
yobitsugi scan <path> --only bandit semgrep      # restrict to specific scanners
yobitsugi scan <path> --no-fetch-native          # skip the trufflehog auto-download
yobitsugi scan <path> --out <workspace>          # write to a specific dir instead of ~/.yobitsugi/<name>-<ts>/

yobitsugi findings <workspace>                   # pretty-print
yobitsugi findings <workspace> --severity HIGH CRITICAL
yobitsugi findings <workspace> --type SQL_INJECTION XSS
yobitsugi findings <workspace> --json            # raw JSON for piping

yobitsugi summary <workspace>                    # rich tables (default)
yobitsugi summary <workspace> --format markdown  # what the assistant pastes into chat
yobitsugi summary <workspace> --format json      # structured data

yobitsugi install                                # register skill in every detected editor
yobitsugi install --platform <name>              # one specific editor
yobitsugi install --scope project                # write into ./.<editor>/ instead of ~/.<editor>/
yobitsugi uninstall [--platform <name>] [--scope ...]
yobitsugi list-platforms
yobitsugi detect-platforms

yobitsugi list-scanners
yobitsugi install-scanners                       # persistent install of missing pip scanners → ~/.yobitsugi/tools/venv/
yobitsugi install-scanners --all                 # force reinstall/upgrade
yobitsugi uninstall-scanners                     # wipe ~/.yobitsugi/tools/
yobitsugi bootstrap                              # persistent install of native scanners (trufflehog via brew/apt/dnf/yum, eslint via npm)
yobitsugi bootstrap trufflehog                   # just trufflehog
yobitsugi bootstrap eslint                       # just eslint (npm install -g eslint + plugins)
yobitsugi bootstrap --dry-run                    # preview the install command

yobitsugi version
```

---

## The unified Finding schema

Every scanner's output is normalised to this shape so the host assistant sees the same thing regardless of which tool found the bug:

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

`type` is one of: `SQL_INJECTION`, `XSS`, `HARDCODED_SECRET`, `COMMAND_INJECTION`, `PATH_TRAVERSAL`, `WEAK_CRYPTO`, `INSECURE_DESERIALIZATION`, `SSRF`, `OPEN_REDIRECT`, `VULNERABLE_DEPENDENCY`, `OTHER`.

---

## Learn more

- [SKILL.md](yobitsugi/data/SKILL.md) — the runbook the host AI assistant follows when you type `/yobitsugi`
- [ARCHITECTURE.md](ARCHITECTURE.md) — the two halves (CLI vs skill), module map, design notes
- [CHANGELOG.md](CHANGELOG.md) — what's new, what was removed

---

<details>
<summary>Contributing</summary>

Issues, PRs, and new scanner/installer plug-ins are welcome.

1. Fork the repo + create a branch.
2. `pip install -e ".[dev]"`.
3. Run `ruff check yobitsugi`, `mypy yobitsugi`, and `pytest` before pushing.
4. Open a PR against `main`. CI runs lint + type-check + tests on Python 3.11 / 3.12 / 3.13.

**Adding a scanner** — one YAML block in [`yobitsugi/data/scanners.yaml`](yobitsugi/data/scanners.yaml). If the output format is exotic, add a parser to [`yobitsugi/core/parse.py`](yobitsugi/core/parse.py) — see [`yobitsugi/data/parser_recipes.md`](yobitsugi/data/parser_recipes.md) for the contract.

**Adding an AI assistant** — one subclass of `Installer` in `yobitsugi/installers/<name>.py`. See `installers/claude.py` for the simplest case and `installers/cursor.py` / `installers/codex.py` for editors that need their own frontmatter format.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module responsibilities and design notes.

</details>

---

## License

`yobitsugi` is distributed under the [MIT License](LICENSE).
