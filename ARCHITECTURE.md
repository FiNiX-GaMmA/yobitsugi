# Architecture

yobitsugi is a **skill-first** security audit tool: the bulk of the
experience lives as a markdown runbook (`yobitsugi/data/SKILL.md`)
installed into each supported agentic AI editor. The host editor's own LLM
and edit tool do the conversational work, the fix generation, and the
edit application. A thin Python binary backs the parts that genuinely need
to shell out — running SAST/SCA scanner binaries and normalising their
output into one unified findings file.

## The two halves

```
┌────────────────────────────────────────────┐  ┌──────────────────────────┐
│   The CLI binary (yobitsugi)               │  │   The skill (SKILL.md)   │
│                                            │  │                          │
│   detect → scan → parse                    │  │   summarise              │
│   summary (render tables)                  │  │   propose diff           │
│   install / uninstall (skill files)        │  │   ask for approval       │
│   install-scanners (managed venv)          │  │   apply with edit tool   │
│                                            │  │   re-scan to validate    │
│   Reads/writes JSON in a workspace dir.    │  │                          │
│   No LLM, no network, no edits.            │  │   Runs in the host AI    │
│                                            │  │   editor's own runtime.  │
└────────────────────────────────────────────┘  └──────────────────────────┘
```

The CLI's pipeline writes JSON into a workspace directory at
`~/.yobitsugi/<repo>-<timestamp>/`. The skill's pipeline reads that JSON,
proposes diffs to the user, and edits files via the assistant's native
edit tool. The chat transcript is the audit trail.

## CLI stages

| Stage | Module | Reads | Writes |
| --- | --- | --- | --- |
| detect | `yobitsugi.core.detect` | repo root | `languages.json` |
| scan | `yobitsugi.core.scan` | `languages.json`, `data/scanners.yaml` | `raw/*.json`, `scan_report.json` |
| parse | `yobitsugi.core.parse` | `raw/*.json` | `findings.json` |
| summary | `yobitsugi.core.summary` | `findings.json`, `scan_report.json` | stdout (rich / markdown / json) |

Every stage is callable as a Python function and as a standalone CLI
entrypoint (`python -m yobitsugi.core.scan --workspace <ws> --root <repo>`).
The `cmd_scan` function in `cli.py` chains detect → scan → parse → summary
in-process. There's no orchestrator module — the chain is short enough that
a five-line loop in the CLI handles it.

## Module map

```
yobitsugi/
├── cli.py              top-level argparse — subcommands: scan, summary,
│                       findings, install, uninstall, list-platforms,
│                       detect-platforms, list-scanners, install-scanners,
│                       uninstall-scanners, version
├── __main__.py         enables `python -m yobitsugi`
├── core/
│   ├── detect.py       language detection (file extensions + filename map)
│   ├── scan.py         runs scanners from the YAML registry
│   ├── parse.py        ~17 per-scanner parsers → unified Finding schema
│   ├── summary.py      rich / markdown / json renderers for the workspace
│   └── tools.py        managed-venv install paths + `ephemeral_tools_dir()` context manager
├── data/               static reference content shipped with the package
│   ├── SKILL.md               the runbook the host AI assistant follows — the *primary artifact*
│   ├── scanners.yaml          scanner registry (per-language + cross-language)
│   └── parser_recipes.md      how to add a new parser
├── templates/
│   └── slash_command.md       same content as SKILL.md (sans Claude-style frontmatter),
│                              rendered into each non-Claude editor's plugin location
└── installers/
    ├── base.py         Installer ABC + INSTALLERS registry + get_installer()
    ├── utils.py        shared template loader
    ├── claude.py       writes ~/.claude/skills/yobitsugi/SKILL.md (uses data/SKILL.md verbatim)
    ├── codex.py        writes ~/.codex/prompts/yobitsugi.md (uses slash_command.md + Codex frontmatter)
    ├── cursor.py       writes .cursor/rules/yobitsugi.mdc
    ├── gemini.py       writes ~/.gemini/commands/yobitsugi.md
    ├── aider.py        writes ~/.aider/yobitsugi.md + edits .aider.conf.yml
    ├── opencode.py     writes ~/.opencode/commands/yobitsugi.md
    └── copilot.py      writes ~/.config/github-copilot/copilot-instructions/yobitsugi.md
```

What's **not** here, by design (deleted in v0.2 when the project became
skill-first):

- `core/pipeline.py` — the in-process orchestrator for the old end-to-end run
- `core/fix.py` — LLM-based unified-diff generation
- `core/apply.py` — backup + patch + git apply + rollback log
- `core/tests_gen.py` — LLM-based regression-test generation
- `core/validate.py` — re-scan + set-diff
- `core/llm.py` — provider abstraction over OpenAI / Anthropic / Google / Ollama
- `data/fix_prompts.md`, `data/test_templates.md`, `data/providers.md`

Those responsibilities moved into the host AI editor.

## CLI surface

| Command | Purpose |
| --- | --- |
| `yobitsugi install [--platform X] [--scope user\|project]` | Register the skill files. Auto-detects assistants if `--platform` omitted. |
| `yobitsugi uninstall [--platform X]` | Remove the skill files. |
| `yobitsugi list-platforms` | Show every supported assistant, marked as detected/not. |
| `yobitsugi detect-platforms` | Just the detected ones. |
| `yobitsugi scan <path> [--ephemeral-tools]` | Detect → run scanners → parse to findings.json. The only scanning entrypoint. With `--ephemeral-tools`, the scanner venv is created in a tempdir and deleted when the command exits. |
| `yobitsugi summary <ws> [--format rich\|markdown\|json]` | Render the workspace as tables for the host assistant to display. |
| `yobitsugi findings <ws>` | Pretty-print or `--json` dump existing findings. |
| `yobitsugi list-scanners` | Every scanner + install status. |
| `yobitsugi install-scanners [--all]` | Persistent install of pip scanners into `~/.yobitsugi/tools/venv/`. |
| `yobitsugi uninstall-scanners` | Wipe `~/.yobitsugi/tools/`. |
| `yobitsugi version` | Print version. |

Positional shortcut: `yobitsugi <path>` (first arg not a known subcommand)
is rewritten to `yobitsugi scan <path>`. Previously this aliased to `run`;
when the `run` subcommand was removed in v0.2 the shortcut was repointed to
the read-only `scan` so muscle memory still produces a useful result.

## How an assistant invokes it

1. User types `/yobitsugi .` inside Claude Code (or `$yobitsugi .` inside Codex, etc.).
2. The assistant reads the skill file we installed (`~/.claude/skills/yobitsugi/SKILL.md`
   for Claude, `~/.codex/prompts/yobitsugi.md` for Codex, etc.) and sees the
   runbook: ask first, run `yobitsugi scan --ephemeral-tools`, render the
   summary, walk findings one at a time, edit with the native edit tool,
   re-scan to validate.
3. The assistant shells out to `yobitsugi scan . --ephemeral-tools`. The
   binary writes `findings.json` and prints the summary.
4. The assistant reads `findings.json`, drives the per-fix loop using its
   own model and edit tool, and re-invokes `yobitsugi scan` for validation.

No LLM call originates from the `yobitsugi` binary — the host assistant
owns all model selection, API keys, prompts, and edit application. This is
the entire point of the skill-first design: the user already chose their
model when they chose their editor; yobitsugi shouldn't second-guess it.

## Ephemeral tools mode

`yobitsugi scan --ephemeral-tools` installs the pip-installable scanners
into a throwaway venv for the duration of one invocation, then deletes it.
This is what makes the slash-command invocation pattern (`/yobitsugi .`
inside any supported assistant) safe to run on machines that don't have
scanners installed — there's no leftover state, no `~/.yobitsugi/tools/`
to clean up afterwards.

The mechanism has five pieces, all owned by `cli.py` and `core/tools.py`:

| Piece | Module | Responsibility |
| --- | --- | --- |
| `--ephemeral-tools` flag | `cli.py` (registered on the `scan` subparser) | Opt-in switch. Default is the persistent `~/.yobitsugi/tools/venv/` behaviour. |
| `_with_optional_ephemeral_tools(fn, args, root)` | `cli.py` | Wraps the body of `cmd_scan`. When the flag is set: detect languages → enter `tools.ephemeral_tools_dir()` → install only the pip scanners the repo actually needs → call `fn()` → tear down temp venv in a `finally`. |
| `_quick_detect_languages(root)` | `cli.py` | Calls `detect.detect()` directly to get the language map *before* the pipeline does. Lets the pre-install step target only the relevant scanners without writing to the real workspace and without ordering it before the pipeline's own `detect` stage. Returns `[]` on any error, in which case the install step falls back to installing every pip scanner. |
| `tools.ephemeral_tools_dir()` | `core/tools.py` | Context manager. Swaps the module-level `TOOLS_DIR` / `VENV_DIR` / `MANIFEST_PATH` to a fresh `tempfile.mkdtemp()` path on entry, restores the originals and `shutil.rmtree`s the temp dir on exit. Cleanup runs in a `finally` block so exceptions and SIGINT both trigger it. |
| `tools.install_missing_pip_scanners(registry, languages=...)` | `core/tools.py` | The programmatic equivalent of `yobitsugi install-scanners`, factored out so `--ephemeral-tools` can call it without spawning a subprocess. Returns `(installed_names, failed_names)`. |

The `tools.TOOLS_DIR` / `VENV_DIR` / `MANIFEST_PATH` constants are mutated
in place so every other module that reads them (`scan.py` calls
`tools.venv_exists()` and `tools.prepend_to_path()`) automatically sees the
temp paths. The rule: never `from yobitsugi.core.tools import VENV_DIR` —
always `tools.VENV_DIR`. The existing modules all follow this.

## Extending

### Add a scanner

Edit `yobitsugi/data/scanners.yaml`:

```yaml
Python:
  - name: my-new-tool
    binary: my-new-tool
    command: 'my-new-tool --json {root} > {out} || true'
    output: json
    install:
      method: pip
      package: my-new-tool
```

Then write a parser function in `yobitsugi/core/parse.py` — see
`data/parser_recipes.md` for the contract. Register it in the `PARSERS`
dict at the bottom of `parse.py`.

### Add an AI assistant

Create `yobitsugi/installers/<name>.py`:

```python
from yobitsugi.installers.base import Installer, InstallResult, register
from yobitsugi.installers.utils import load_template
from pathlib import Path

@register
class MyAssistantInstaller(Installer):
    name = "myasst"
    display_name = "My Assistant"

    def config_dir(self) -> Path:
        return Path.home() / ".myasst"

    def install(self, scope="user"):
        target = self.config_dir() / "commands" / "yobitsugi.md"
        self._write(target, load_template("slash_command.md"))
        return InstallResult(self.display_name, [target])

    def uninstall(self, scope="user"):
        removed = self._remove(self.config_dir() / "commands" / "yobitsugi.md")
        return InstallResult(self.display_name, [removed] if removed else [], action="uninstalled")
```

Then add the import at the bottom of `installers/base.py`. The registry
decorator handles the rest.

If the editor's plugin format needs frontmatter or a different file layout
(see `codex.py` for the Codex frontmatter pattern, `cursor.py` for the
`.mdc` rule format), customise the installer accordingly — the rest of the
codebase doesn't care.

## Test architecture

The test suite lives in `tests/` and is organised one-file-per-module.
Tests are hermetic by design: nothing touches the network, scanner
binaries, or the developer's real `$HOME`.

| Seam | How it's isolated |
| --- | --- |
| `subprocess.run` (scanners, pip) | `monkeypatch` replaces the runner with deterministic stubs. |
| `Path.home()` | A `fake_home` fixture in `conftest.py` redirects to a `tmp_path` so installer tests can't escape. |
| Real repos | A `tmp_repo` fixture creates a one-commit git repo inside `tmp_path`. |
| Scanner venv | `tests/test_tools.py` exercises both the persistent and `ephemeral_tools_dir()` paths in isolated `tmp_path` dirs. |

The result is that `pytest` runs against the full CLI surface in a couple
of seconds with no hidden global state.

## Design notes

**Why skill-first instead of an end-to-end CLI?** The previous design
(`yobitsugi run` driving fix → apply → tests → validate with its own LLM
client) duplicated work the host AI editor already does. The editor has a
model the user chose, an edit tool the user trusts, an undo stack, plan
mode, syntax highlighting, file watching — all the things a security
audit benefits from. Replicating any of that in a separate binary is
either worse or fragile (the Ollama / mistral autodetect bug being a
concrete example: yobitsugi guessed wrong, the user's already-configured
Claude or GPT inside the editor would have just worked).

**Why a YAML scanner registry instead of code?** Adding a scanner shouldn't
require touching Python. Most additions are "this binary takes these flags,
writes JSON to this path" — pure config.

**Why ship `data/` with the wheel instead of fetching at runtime?**
Offline-first. `yobitsugi scan` works without network. There's nothing
network-bound left in the binary at all.

**Why mutate `tools.TOOLS_DIR` for `--ephemeral-tools` instead of threading
a path argument through every call site?** Because `scan.py`, `cli.py` and
the installers all reach into `tools` to ask "where's the managed venv?"
— passing a path through five layers of function calls just to redirect a
single context-manager-scoped run would have been worse, both for the diff
size and for the chance of one call site forgetting. The price is a global
mutation, which is OK because (a) it's strictly scoped to the lifetime of
the context manager, (b) the `finally` restores the originals even on
Ctrl-C, and (c) tests already use the same pattern (`fake_home` redirects
`Path.home()` globally for the test's duration).
