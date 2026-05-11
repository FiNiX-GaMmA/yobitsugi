<!--
  yobitsugi — README
  Style: Apache Airflow (badges block, ToC, sectioned layout with anchors).
-->

<p align="center">
  <h1 align="center">yobitsugi</h1>
  <p align="center"><em>呼継ぎ — "called-in joinery."</em></p>
  <p align="center">AI coding assistant skill that scans a repository with industry SAST/SCA tools<br/>and patches the findings using your assistant's LLM.</p>
</p>

<div align="center">

[![PyPI version](https://img.shields.io/pypi/v/yobitsugi?label=pypi&color=blue&cacheSeconds=3600)](https://pypi.org/project/yobitsugi/)
[![PyPI downloads](https://static.pepy.tech/badge/yobitsugi/month)](https://pepy.tech/project/yobitsugi)
[![Python versions](https://img.shields.io/pypi/pyversions/yobitsugi?color=blue&cacheSeconds=3600)](https://pypi.org/project/yobitsugi/)
[![License: MIT](https://img.shields.io/pypi/l/yobitsugi?color=green&cacheSeconds=3600)](LICENSE)
[![Stars](https://img.shields.io/github/stars/FiNiX-GaMmA/yobitsugi?style=flat&color=yellow&cacheSeconds=3600)](https://github.com/FiNiX-GaMmA/yobitsugi/stargazers)
[![GitHub followers](https://img.shields.io/github/followers/FiNiX-GaMmA?label=Follow%20%40FiNiX-GaMmA&style=flat&color=blue&cacheSeconds=3600)](https://github.com/FiNiX-GaMmA)

[![CI](https://github.com/FiNiX-GaMmA/yobitsugi/actions/workflows/ci.yml/badge.svg)](https://github.com/FiNiX-GaMmA/yobitsugi/actions/workflows/ci.yml)
[![Release & Publish](https://github.com/FiNiX-GaMmA/yobitsugi/actions/workflows/publish.yml/badge.svg)](https://github.com/FiNiX-GaMmA/yobitsugi/actions/workflows/publish.yml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Type-checked: mypy](https://img.shields.io/badge/type--checked-mypy-1f5082.svg)](http://mypy-lang.org/)
[![Tests: pytest](https://img.shields.io/badge/tests-pytest-0A9EDC.svg)](https://docs.pytest.org/)


</div>

<br/>

> A Japanese pottery technique: when a broken vessel can't be repaired with its own fragments, pieces from a different vessel are *called in* and joined to complete the whole. The repair is honest about its origin — the foreign piece is visible, often a different colour or pattern, and the new vessel is more interesting for it. That's what this tool does. The original code has a crack (a vulnerability). The LLM is the foreign vessel — its patch comes from elsewhere, joined to your code at the seam. Backups, the `applied.json` log, the regression test, and the re-scan all keep the join visible and accountable.

---

## Table of Contents

- [What is yobitsugi?](#what-is-yobitsugi)
- [Project focus](#project-focus)
- [Requirements](#requirements)
- [Installing from PyPI](#installing-from-pypi)
- [Installing from source](#installing-from-source)
- [Quick start](#quick-start)
- [Supported AI coding assistants](#supported-ai-coding-assistants)
- [Supported scanners](#supported-scanners)
- [Installing scanners](#installing-scanners)
- [Configure the LLM provider](#configure-the-llm-provider)
- [Common commands](#common-commands)
- [Architecture overview](#architecture-overview)
- [Safety guarantees](#safety-guarantees)
- [The unified Finding schema](#the-unified-finding-schema)
- [Privacy](#privacy)
- [Development](#development)
- [Testing](#testing)
- [Test layout](#test-layout)
- [Releasing](#releasing)
- [Semantic versioning](#semantic-versioning)
- [Python version lifecycle](#python-version-lifecycle)
- [Contributing](#contributing)
- [License](#license)

---

## What is yobitsugi?

`yobitsugi` is a CLI and an **AI coding assistant skill** that:

1. **Detects** the languages in a repo.
2. **Scans** it with real, industry-standard SAST and SCA tools (bandit, semgrep, gosec, brakeman, npm audit, pip-audit, trufflehog, and more).
3. **Normalises** every scanner's output into a single Finding schema.
4. **Patches** each finding by asking an LLM (your provider, your key) to generate a unified diff.
5. **Applies** that diff safely — with backups, a rollback log, and a dirty-tree guard.
6. **Generates a regression test** that would have caught the original bug.
7. **Re-scans** to verify the fix actually closed the finding and didn't introduce a new one.

It ships as a slash command — `/yobitsugi .` — for Claude Code, Codex, Cursor, Gemini CLI, Aider, OpenCode, and GitHub Copilot CLI. The same `yobitsugi` CLI also works standalone outside any assistant.

```bash
/yobitsugi .                                 # inside any supported assistant
yobitsugi run ./services/api                 # standalone
yobitsugi run ./services/api --auto          # apply fixes without prompting
yobitsugi scan ./services/api                # scan-only, no LLM calls
```

---

## Project focus

- **Honest joinery.** The LLM patch is a *visible* repair — every change is logged, backed up, and re-verified.
- **No vendor lock-in.** Bring your own LLM. Bring your own scanners.
- **Offline-first scanning.** Only the fix step touches the network.
- **Single source of truth.** Each finding has a stable `id` so re-runs compute true `fixed_ids` / `still_present` / `newly_introduced` sets.
- **Testable.** Every core stage is a pure-ish function with a deliberate boundary. The pipeline runs in-process — no subprocess fork-bombs.

---

## Requirements

| Component | Requirement |
| --- | --- |
| Python | **3.11+** (tested on 3.11, 3.12, 3.13) |
| `git` | Required if you want the dirty-tree safety check |
| `patch` or `git apply` | Required for diff application |
| Scanner binaries | Optional per language — missing tools are skipped, not fatal |
| LLM provider | OpenAI / Anthropic / Google / Ollama / any OpenAI-compatible endpoint |

---

## Installing from PyPI

```bash
pipx install yobitsugi && yobitsugi install
# or
uv tool install yobitsugi && yobitsugi install
# or
pip install yobitsugi && yobitsugi install
```

For JS-native users (still needs Python 3.11+ available somewhere):

```bash
npx yobitsugi install
# the npm package is a thin shim that delegates to `uvx yobitsugi`
```

Or drop the repo in directly as a Claude Code skill:

```bash
git clone https://github.com/FiNiX-GaMmA/yobitsugi ~/.claude/skills/yobitsugi
```

`yobitsugi install` auto-detects every supported assistant on your machine and registers the skill for each. Pass `--platform <name>` to install for one specifically, or `--scope project` to install into the current repo's config instead of your home dir.

---

## Installing from source

```bash
git clone https://github.com/FiNiX-GaMmA/yobitsugi
cd yobitsugi
pip install -e ".[dev]"
yobitsugi version
```

---

## Quick start

```bash
# 1. Make sure you have an LLM key in your environment.
export ANTHROPIC_API_KEY=sk-ant-...

# 2. Scan + fix a repo, prompting before each patch.
yobitsugi run ./my-project

# 3. Or, scan only — no LLM, no edits.
yobitsugi scan ./my-project

# 4. Inspect what was found.
yobitsugi findings ~/.yobitsugi/my-project-20260511-100501
```

You get a workspace directory:

```
~/.yobitsugi/<repo>-<timestamp>/
├── languages.json    detected languages with file counts
├── scan_report.json  per-scanner status (ok / skipped_missing_tool / errored)
├── findings.json     unified, deduplicated list of vulnerabilities    ← the cracks
├── applied.json      rollback log — one entry per applied patch        ← the called-in pieces
└── validation.json   fixed_ids, still_present, newly_introduced        ← did the joins hold?
```

---

## Supported AI coding assistants

| Platform | Install command |
| --- | --- |
| Claude Code | `yobitsugi install --platform claude` |
| Codex | `yobitsugi install --platform codex` |
| Cursor | `yobitsugi install --platform cursor` |
| Gemini CLI | `yobitsugi install --platform gemini` |
| Aider | `yobitsugi install --platform aider` |
| OpenCode | `yobitsugi install --platform opencode` |
| GitHub Copilot CLI | `yobitsugi install --platform copilot` |

Uninstall with `yobitsugi uninstall --platform <name>`. List everything with `yobitsugi list-platforms`.

---

## Supported scanners

Auto-detected per language. Missing binaries are skipped, not fatal — and yobitsugi can install most of them for you in an isolated venv (see [Installing scanners](#installing-scanners) below).

| Language | Scanners |
| --- | --- |
| Python | `bandit`, `safety`, `pip-audit`, `semgrep` |
| JavaScript / TypeScript | `eslint` (security plugins), `npm audit`, `semgrep` |
| Go | `gosec`, `govulncheck`, `semgrep` |
| Java | `spotbugs` (with FindSecBugs), `semgrep` |
| Ruby | `brakeman`, `bundler-audit`, `semgrep` |
| PHP | `phpstan` (security extension), `semgrep` |
| C / C++ | `flawfinder`, `cppcheck`, `semgrep` |
| Rust | `cargo-audit`, `semgrep` |
| Shell | `shellcheck`, `semgrep` |
| Cross-language | `semgrep`, `trufflehog` (secrets scanning) |

Adding a new scanner is one YAML block in [`yobitsugi/data/scanners.yaml`](yobitsugi/data/scanners.yaml) — no code change needed unless the output format is exotic.

---

## Installing scanners

yobitsugi orchestrates scanners — it doesn't bundle their binaries. When you run `yobitsugi scan` and a scanner isn't on `PATH`, that scanner is silently skipped. To check the situation:

```bash
yobitsugi list-scanners       # every scanner, install method, and whether it's available
```

To install the **Python-based** scanners (bandit, safety, pip-audit, semgrep, flawfinder) in one shot, into an isolated venv at `~/.yobitsugi/tools/venv/`:

```bash
yobitsugi install-scanners    # installs only missing ones
yobitsugi install-scanners --all   # reinstall/upgrade everything

yobitsugi uninstall-scanners  # wipes ~/.yobitsugi/tools/ entirely
```

After `install-scanners` succeeds, every subsequent `yobitsugi scan` or `yobitsugi run` automatically prepends the venv's `bin/` to `PATH` for scanner subprocesses — you don't need to activate anything yourself, and the venv never pollutes your main Python environment.

**Non-Python scanners need their own runtime** and yobitsugi will print install hints rather than try to bootstrap six different package managers badly:

| Runtime | Scanners | Install yourself with |
| --- | --- | --- |
| Node | `eslint` | `npm install -g eslint eslint-plugin-security` |
| Go | `gosec`, `govulncheck` | `go install github.com/securego/gosec/v2/cmd/gosec@latest` etc. |
| Cargo | `cargo-audit` | `cargo install cargo-audit` |
| Ruby | `brakeman`, `bundler-audit` | `gem install brakeman bundler-audit` |
| System | `shellcheck`, `cppcheck`, `trufflehog` | `brew install …` or `apt install …` |
| Manual | `spotbugs`, `phpstan` | see project release pages |

If you're running yobitsugi via an AI assistant (`/yobitsugi .`), the assistant will see the "scanner skipped" entries in `scan_report.json` and **ask you** whether to run the appropriate install commands.

---

## Configure the LLM provider

Provider config is resolved in this order: `--provider` flag → environment variables → `~/.yobitsugi/config.yaml` → autodetect from any API key in env.

| Provider | Env var | Example model |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o`, `gpt-4o-mini` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-opus-4-7`, `claude-sonnet-4-6` |
| Google | `GOOGLE_API_KEY` | `gemini-1.5-pro` |
| Ollama (local) | none | `llama3.1:70b` |
| OpenAI-compatible (Groq, Together, Fireworks, vLLM, LM Studio, OpenRouter) | `OPENAI_API_KEY` + `OPENAI_BASE_URL` | any |

```bash
yobitsugi config --init        # write a starter ~/.yobitsugi/config.yaml
yobitsugi config               # show resolved provider/model/base_url
```

---

## Common commands

```
/yobitsugi .                                     # full pipeline, prompt before each fix
/yobitsugi . --auto                              # apply fixes without confirmation
/yobitsugi . --severity CRITICAL                 # only critical findings
/yobitsugi . --provider anthropic --model claude-opus-4-7
/yobitsugi . --skip-tests                        # don't generate regression tests
/yobitsugi . --allow-dirty                       # run on a dirty git tree

yobitsugi scan ./services/api                    # scan-only, no fixes, no LLM
yobitsugi findings ~/.yobitsugi/<workspace>      # pretty-print existing findings
yobitsugi findings <ws> --severity HIGH --json   # JSON output for piping
yobitsugi rollback ~/.yobitsugi/<workspace>      # restore all .yobitsugi.bak files

yobitsugi list-platforms                         # show all supported assistants
yobitsugi detect-platforms                       # show only the ones installed

yobitsugi list-scanners                          # every scanner + install status
yobitsugi install-scanners                       # install missing Python scanners into ~/.yobitsugi/tools/venv/
yobitsugi install-scanners --all                 # force reinstall/upgrade all of them
yobitsugi uninstall-scanners                     # wipe the managed venv

yobitsugi summary ~/.yobitsugi/<workspace>       # tabular post-run report (runs automatically at the end of `run`/`scan`)
yobitsugi summary <ws> --format markdown          # markdown tables — paste into chat
yobitsugi summary <ws> --format json              # structured data for tooling
```

---

## Architecture overview

```
detect → scan → parse → (loop: fix → apply) → tests → validate
```

Every stage is also a callable Python function and a standalone CLI entrypoint. The orchestrator at [`yobitsugi/core/pipeline.py`](yobitsugi/core/pipeline.py) runs them **in-process** — no subprocess fork between stages. Each stage reads and writes JSON inside the workspace directory, so you can re-run any stage by hand against the previous stage's output.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full module map and design notes.

---

## Safety guarantees

- Refuses to run on a dirty git tree unless `--allow-dirty` is set.
- Every modified file gets a `.yobitsugi.bak` sibling before the patch is applied.
- An `applied.json` rollback log records every patch — `yobitsugi rollback` restores all of them in one command.
- The model is constrained to return unified diffs or the literal string `# CANNOT_FIX: <reason>`. No inline edits, no destructive commands.
- Code snippets pulled from your repo are wrapped in `[BEGIN UNTRUSTED USER CODE]` / `[END UNTRUSTED USER CODE]` markers in the LLM prompt to mitigate prompt-injection from malicious comments or strings.
- Fixes are never auto-applied unless you explicitly pass `--auto`.
- `validate` re-runs the full scan after fixes and flags `newly_introduced` findings — vulnerabilities the patches accidentally created. Exit code 3 if any.

---

## The unified Finding schema

Every scanner's output is normalised to this shape so the LLM, the apply logic, and the test generator all see the same thing:

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

`type` is one of: `SQL_INJECTION`, `XSS`, `HARDCODED_SECRET`, `COMMAND_INJECTION`, `PATH_TRAVERSAL`, `WEAK_CRYPTO`, `INSECURE_DESERIALIZATION`, `SSRF`, `OPEN_REDIRECT`, `VULNERABLE_DEPENDENCY`, or `OTHER`. Auto-classified by the parser when the scanner doesn't say it explicitly.

The `id` is a stable hash of `(tool, file, line, rule_id)` — so the same finding gets the same id across runs, which is how `validate` computes `fixed_ids` and `still_present`.

---

## Privacy

- **Scanner output** stays on your machine. None of it is sent to the LLM unless a fix is being generated.
- **Fix generation** sends one finding's metadata plus ±12 lines of source context to the LLM, using your own API key.
- **No telemetry**, no usage tracking, no analytics.

---

## Development

```bash
git clone https://github.com/FiNiX-GaMmA/yobitsugi
cd yobitsugi
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Verify the toolchain.
yobitsugi version
ruff check yobitsugi
mypy yobitsugi
pytest
```

---

## Testing

The test suite is built around **pytest** and is designed to run hermetically — no real LLM calls, no real scanner binaries, no real network. External dependencies are mocked at well-defined seams (`subprocess.run`, `requests.post`, `Path.home()`).

### Running the tests

```bash
pip install -e ".[dev]"

pytest                              # run everything
pytest -v                           # verbose
pytest tests/test_parse.py          # one file
pytest tests/test_parse.py -k bandit  # one matching test
pytest --tb=short                   # shorter tracebacks
pytest -x                           # stop at first failure
```

### What's covered

| Suite | Module under test | What it asserts |
| --- | --- | --- |
| `tests/test_detect.py` | `yobitsugi.core.detect` | Language counting, directory pruning, large-file skip, symlink handling, CLI output. |
| `tests/test_parse.py` | `yobitsugi.core.parse` | Severity normalisation, vuln-type classification, stable `make_id`, the unified `finding()` constructor, bandit/semgrep/safety parsers, deduplication, malformed-input handling. |
| `tests/test_apply.py` | `yobitsugi.core.apply` | The `CANNOT_FIX` sentinel, diff file extraction, dirty-tree refusal, backup creation, `applied.json` logging, full rollback round-trip, failure modes. |
| `tests/test_llm.py` | `yobitsugi.core.llm` | Provider resolution precedence (kwargs → env → file → autodetect), missing-key errors, request-shape correctness for OpenAI/Anthropic, error propagation for non-OK / non-JSON responses. |
| `tests/test_pipeline.py` | `yobitsugi.core.pipeline` | Stage ordering, severity filtering, `--skip-tests`, per-finding LLM-error resilience, empty-diff handling, CLI → `run_pipeline` plumbing. |
| `tests/test_cli.py` | `yobitsugi.cli` | Every subcommand: `version`, `list-platforms`, `detect-platforms`, `config`, `findings`, `run`, positional shortcut, help fallthrough. |
| `tests/test_installers.py` | `yobitsugi.installers.*` | Registry completeness, `get_installer` lookup, `InstallResult.__str__`, install→uninstall round-trip for every supported assistant. |

The test suite runs in **~2 seconds** locally and against Python 3.11 / 3.12 / 3.13 in CI on every push and pull request.

### Test layout

```
tests/
├── conftest.py            # shared fixtures: tmp_repo, tmp_workspace, fake_home, sample_finding, ...
├── test_detect.py
├── test_parse.py
├── test_apply.py
├── test_llm.py
├── test_pipeline.py
├── test_cli.py
└── test_installers.py
```

Configuration lives in [`pyproject.toml`](pyproject.toml) under `[tool.pytest.ini_options]`. Linting + type checking are configured under `[tool.ruff]` and `[tool.mypy]`.

### Writing new tests

- Put pure, parameterised assertions on the smallest unit you can.
- For anything that would call subprocess, network, or the filesystem outside a `tmp_path`, use the existing fixtures or `monkeypatch`.
- New scanner parser? Add a fixture of sample raw input + assert against the unified Finding shape (see `TestBanditParser` / `TestSemgrepParser` for the pattern).
- New LLM provider? Add an analogue of `test_chat_openai_request_shape` that asserts the request URL, headers, and body shape.

---

## Releasing

> **Release policy: every push to `main` is a release.** The workflow finds the latest `vX.Y.Z` tag, bumps the patch component, creates the new tag, builds, and publishes to both GitHub Releases and PyPI. There is no separate "version bump" step — version metadata lives in git tags, not in source files.

This is wired through [`hatch-vcs`](https://github.com/ofek/hatch-vcs): at build time, the package's version is read from the latest git tag. `pyproject.toml` declares `dynamic = ["version"]` rather than a static value; `yobitsugi/__init__.py` reads `__version__` from a generated `yobitsugi/_version.py` (the file is gitignored — hatch-vcs writes it during `pip install` / `python -m build`).

### Day-to-day flow

```bash
git commit -m "Fix the thing"
git push origin main
```

That's the whole release procedure. The workflow takes over:

1. **prep** — finds the latest `vX.Y.Z` tag (e.g. `v0.1.4`), computes the next patch (`v0.1.5`).
2. **tag** — creates and pushes `v0.1.5`.
3. **build** — checks out at `v0.1.5`, builds an sdist + wheel; hatch-vcs stamps the artifacts as `0.1.5`. Validates with `twine check --strict`.
4. **release** — creates a GitHub Release at `/releases` with the wheel + sdist attached and notes pulled from the matching `## 0.1.5` section of [CHANGELOG.md](CHANGELOG.md) (falls back to auto-generated notes from commits).
5. **publish** — uploads to https://pypi.org/project/yobitsugi/ through the gated `pypi` environment.

### Workflow jobs

| Job | When it runs | What it does |
| --- | --- | --- |
| `prep` | Always | Computes the next tag (latest `vX.Y.Z` + 1 patch). |
| `tag` | Always (skipped only when a `v*` tag was pushed directly) | Creates and pushes the new tag. |
| `build` | After `tag` succeeds | sdist + wheel via `hatch-vcs`, validated with `twine check --strict`. |
| `release` | After `build` (skipped on `release: published` events) | Creates the GitHub Release with notes + assets. Tags containing `-rc`, `-alpha`, or `-beta` are marked as pre-releases. |
| `publish` | After `build` | Uploads to PyPI through the `pypi` environment. |

### Bumping minor or major

The workflow only auto-bumps the patch component. To cut a minor or major release, push the tag manually:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The `tag` job is skipped (tag already exists), `prep` picks up that exact tag, everything else runs.

### Trade-offs of this model

- **Every push burns a PyPI version number.** Even a typo fix in the README publishes a new release. PyPI versions are immutable.
- **Version numbers have no semantic meaning.** `0.1.47` just means "the 47th push since `v0.1.0`," not "47 patch-level fixes."
- **Every push costs ~2 minutes of CI.**
- **Upside:** zero release ceremony. Push and you've shipped.

If those trade-offs stop making sense, switch the `prep` job back to "release only when pyproject.toml's version is new" — the prior model. The relevant section is roughly 15 lines.

### Required secrets

| Secret | Required? | Value |
| --- | --- | --- |
| `PYPI_TOKEN` | **Yes** | A PyPI API token starting with `pypi-` (create one at https://pypi.org/manage/account/token/) |
| `RELEASE_PAT` | Optional | A fine-grained Personal Access Token with `contents: write` on this repo. Only useful if you want the auto-pushed tag to *also* trigger any **other** workflows that watch tags. The release flow itself works without it. |

The workflow passes `__token__` as the PyPI username, per PyPI's API-token convention — so you only need to manage one secret.

> **Note** — PyPI no longer accepts raw account passwords for uploads. `PYPI_TOKEN` **must** be an API token (the value starts with `pypi-`), not your account password.

Cut a release:

```bash
# Bump the version in pyproject.toml + yobitsugi/__init__.py, commit, then:
git tag v0.1.0
git push origin v0.1.0
```

---

## Semantic versioning

`yobitsugi` follows [SemVer 2.0.0](https://semver.org/). The current major (`0.x`) is the pre-stable line — minor versions may include breaking API changes. From `1.0.0` onwards, breaking changes will only land in major versions.

---

## Python version lifecycle

| Python | Status |
| --- | --- |
| 3.11 | **Supported** (oldest supported) |
| 3.12 | **Supported** |
| 3.13 | **Supported** |
| ≤ 3.10 | Unsupported — `pip install` will refuse to install. |

When a Python version reaches end-of-life upstream, support is dropped in the next minor release of `yobitsugi`.

---

## Contributing

Issues, PRs, and new scanner/installer/provider plug-ins are welcome.

1. Fork the repo + create a branch.
2. `pip install -e ".[dev]"`.
3. Run `ruff check yobitsugi`, `mypy yobitsugi`, and `pytest` before pushing.
4. Open a PR against `main`. CI will run lint + type-check + tests on Python 3.11 / 3.12 / 3.13.

See [ARCHITECTURE.md](ARCHITECTURE.md) for where to add new scanners, installers, or LLM providers — most additions are config-only.

---

## License

`yobitsugi` is distributed under the [MIT License](LICENSE).
