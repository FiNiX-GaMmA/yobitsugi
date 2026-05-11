# Changelog

## Unreleased

### Changed
- **Python 3.11+ is now required.** Python 3.10 is no longer supported.
- The pipeline orchestrator now runs **in-process**. Stages are imported and called as Python functions instead of being forked as subprocesses. Each stage is still a standalone CLI entrypoint, and the JSON-file workspace contract between stages is preserved.
- `core.fix.generate_fix(finding, root, ...)` is now a public pure function that returns the diff string. `core.fix.main()` is a thin CLI wrapper around it.
- `core.apply.apply_diff(diff_text, root, workspace, ...)` is now a public pure function. `core.apply.main()` is a thin CLI wrapper around it.
- Each `core.<stage>.main()` accepts an optional `argv: list[str] | None` parameter so it can be invoked from Python without mutating `sys.argv`.

### Fixed
- `cli.cmd_config` was passing an `argparse.Namespace` to `llm.resolve_config()` which expects positional strings — this raised a `TypeError` at runtime. The CLI now calls `resolve_config()` correctly.
- `cli.cmd_run` no longer mutates `sys.argv`; it calls `pipeline.run_pipeline()` directly.
- `cli.cmd_scan` and `cli.cmd_rollback` no longer spawn Python subprocesses; they call the relevant `main([...])` in-process.

### Added
- **Unit test suite** (`tests/`) — 147 hermetic pytest tests covering `detect`, `parse`, `apply`, `llm`, `pipeline`, `cli`, and all platform installers. Runs in ~2 seconds. Tested against Python 3.11, 3.12, 3.13.
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — runs ruff, mypy, and pytest on every push and PR across Python 3.11 / 3.12 / 3.13.
- **GitHub Actions release + publish workflow** (`.github/workflows/publish.yml`) — triggered by `v*` tags, GitHub Releases, or manual dispatch. Three jobs:
  - **build** — produces sdist + wheel, validates with `twine check --strict`.
  - **release** — on a `v*` tag, creates a GitHub Release at https://github.com/FiNiX-GaMmA/yobitsugi/releases with notes extracted from the matching `## <version>` section of `CHANGELOG.md` (or auto-generated from commit history as a fallback), and attaches the wheel + sdist as release assets. Tags containing `-rc`, `-alpha`, or `-beta` are marked as pre-releases.
  - **publish** — uploads the same artifacts to PyPI, gated behind the `pypi` GitHub Environment. Authenticated by a single `PYPI_TOKEN` repository secret (the workflow passes `__token__` as the username, per PyPI's API-token convention).
- `pyproject.toml` now includes `[tool.pytest.ini_options]`, `[tool.mypy]`, and an expanded `[tool.ruff.lint]` configuration.
- `Changelog` URL in project metadata.
- **Comprehensive `.gitignore`** covering Python build/cache artifacts, virtual environments, lint/type/test caches, IDE files, OS metadata, every common secret/credential filename (`.env`, `*.pem`, `*.key`, `*.token`, `credentials.json`, etc.), `yobitsugi` runtime outputs (workspaces, `.yobitsugi.bak` backups, accidental root-level `findings.json`/`applied.json`/`languages.json`/`scan_report.json`/`validation.json`/`raw/`), and documentation builds — with a negation rule (`!yobitsugi/data/*.yaml`) so the shipped scanner registry is never accidentally swallowed.

### Removed
- The redundant `yobitsugi/yobitsugi/yobitsugi/` wrapper folder layer. The Python package now sits directly under the repo root.
- Phantom `yobitsugi/{core,data,installers,templates,viz}` directory (created accidentally by a failed shell brace expansion).

## 0.1.0 — initial release

- Pipeline: detect → scan → parse → fix → apply → tests → validate.
- Unified Finding schema across 17 SAST/SCA scanner parsers.
- LLM provider abstraction: OpenAI, Anthropic, Google, Ollama, and any OpenAI-compatible endpoint (Groq, Together, Fireworks, vLLM, LM Studio, OpenRouter).
- Platform installers: Claude Code, Codex, Cursor, Gemini CLI, Aider, OpenCode, GitHub Copilot CLI.
- Three install paths: Python (`pipx`/`uv`/`pip`), npm/npx (delegates to `uvx`), or manual git-clone into `~/.claude/skills/`.
- Canonical `SKILL.md` at repo root, bundled inside the wheel so the Claude installer writes the exact same file you'd get from a manual drop-in.
- CLI: `install`, `uninstall`, `list-platforms`, `detect-platforms`, `run`, `scan`, `findings`, `rollback`, `config`, `version`.
- Safety: dirty-tree guard, `.yobitsugi.bak` per modified file, `applied.json` rollback log, prompt-injection wrapping of untrusted snippets, unified-diff-only model output.
