# Architecture

yobitsugi is a pipeline of single-purpose modules that communicate exclusively through JSON files in a workspace directory. No shared in-memory state, no implicit ordering — each stage can be re-run independently against the previous stage's output.

## The pipeline

```
detect → scan → parse → (loop: fix → apply) → tests → validate
```

| Stage | Module | Reads | Writes |
| --- | --- | --- | --- |
| detect | `yobitsugi.core.detect` | repo root | `languages.json` |
| scan | `yobitsugi.core.scan` | `languages.json`, `data/scanners.yaml` | `raw/*.json`, `scan_report.json` |
| parse | `yobitsugi.core.parse` | `raw/*.json` | `findings.json` |
| fix | `yobitsugi.core.fix` | one finding dict + `data/fix_prompts.md` | unified diff (string) |
| apply | `yobitsugi.core.apply` | unified diff (string) + `findings.json` | edits repo, `applied.json`, `.yobitsugi.bak` files |
| tests | `yobitsugi.core.tests_gen` | `applied.json`, `findings.json` + `data/test_templates.md` | `tests/*` |
| validate | `yobitsugi.core.validate` | repo (post-fix), `findings.json` | `validation.json` |

The orchestrator [`yobitsugi.core.pipeline`](yobitsugi/core/pipeline.py) is an **in-process** driver. It imports each stage and calls it directly — no subprocesses between stages — which keeps the call stack inspectable, makes the pipeline cheaply testable, and avoids Python-startup-cost overhead per stage.

Every stage is **also** a standalone CLI entrypoint: `python -m yobitsugi.core.scan --workspace <ws> --root <repo>` works the same way as `pipeline.run_pipeline()` calling `scan.main([...])` internally. This is deliberate. Run any stage by hand, tweak its output, then resume — the JSON-file workspace contract makes that safe.

The `fix` and `apply` stages also expose pure-function variants (`generate_fix(finding, root, ...)` and `apply_diff(diff_text, root, workspace, ...)`) so callers can compose them without going through argv parsing.

## Module map

```
yobitsugi/
├── cli.py              top-level argparse — subcommands listed below
├── __main__.py         enables `python -m yobitsugi`
├── core/
│   ├── detect.py       language detection (file extensions + filename map)
│   ├── scan.py         runs scanners from the YAML registry
│   ├── parse.py        ~17 per-scanner parsers → unified Finding schema
│   ├── fix.py          LLM call → unified diff
│   ├── apply.py        backup + patch + git apply fallback + rollback log
│   ├── tests_gen.py    LLM call → regression test per fix
│   ├── validate.py     re-scan + set-diff
│   ├── pipeline.py     in-process orchestrator — exposes run_pipeline() + main()
│   ├── tools.py        managed-venv install paths + `ephemeral_tools_dir()` context manager
│   └── llm.py          provider abstraction (OpenAI/Anthropic/Google/Ollama/OpenAI-compat)
├── data/               static reference content shipped with the package
│   ├── scanners.yaml          scanner registry (per-language + cross-language)
│   ├── fix_prompts.md         per-vuln-type guidance for the fix LLM call
│   ├── test_templates.md      per-vuln-type test patterns
│   ├── parser_recipes.md      how to add a new parser
│   └── providers.md           per-LLM-provider env vars, models, gotchas
├── templates/
│   └── slash_command.md       the /yobitsugi command body (rendered into each platform)
└── installers/
    ├── base.py         Installer ABC + INSTALLERS registry + get_installer()
    ├── utils.py        shared template loader
    ├── claude.py       writes ~/.claude/skills/yobitsugi/SKILL.md
    ├── codex.py        writes ~/.codex/prompts/yobitsugi.md
    ├── cursor.py       writes .cursor/rules/yobitsugi.mdc
    ├── gemini.py       writes ~/.gemini/commands/yobitsugi.md
    ├── aider.py        writes ~/.aider/yobitsugi.md + edits .aider.conf.yml
    ├── opencode.py     writes ~/.opencode/commands/yobitsugi.md
    └── copilot.py      writes ~/.config/github-copilot/copilot-instructions/yobitsugi.md
```

## CLI surface

| Command | Purpose |
| --- | --- |
| `yobitsugi install [--platform X] [--scope user\|project]` | Register the slash command. Auto-detects assistants if `--platform` omitted. |
| `yobitsugi uninstall [--platform X]` | Remove the slash command. |
| `yobitsugi list-platforms` | Show every supported assistant, marked as detected/not. |
| `yobitsugi detect-platforms` | Just the detected ones. |
| `yobitsugi run <path> [--ephemeral-tools]` | End-to-end pipeline. Aliased: `yobitsugi <path>`. With `--ephemeral-tools`, the scanner venv is created in a tempdir and deleted when the command exits. |
| `yobitsugi scan <path> [--ephemeral-tools]` | Scan-only — no LLM, no fixes. With `--ephemeral-tools`, same throwaway-venv behaviour as `run`. |
| `yobitsugi findings <ws>` | Pretty-print or `--json` dump existing findings. |
| `yobitsugi rollback <ws>` | Restore all `.yobitsugi.bak` files from a workspace's `applied.json`. |
| `yobitsugi config --init / --print` | Bootstrap or inspect resolved LLM provider config. |
| `yobitsugi version` | Print version. |

Positional shortcut: `yobitsugi <path>` (first arg not a known subcommand) is rewritten to `yobitsugi run <path>`. This is what makes `/yobitsugi .` work inside an assistant — the slash command body just passes the user's args straight through.

## How an assistant invokes it

1. User types `/yobitsugi .` inside Claude Code (or `$yobitsugi .` inside Codex, etc).
2. The assistant reads the skill/command file we installed and sees: "run `yobitsugi` from the shell with these args, then summarise the output".
3. The assistant shells out to `yobitsugi .`, which expands to `yobitsugi run .`.
4. Pipeline runs, writes to a workspace dir.
5. Assistant reads `findings.json`, `validation.json`, summarises in the chat.

The LLM call inside `fix.py` uses the **same** provider the user has configured for the standalone CLI — it does *not* hijack the assistant's own model API. This is deliberate: it keeps cost and observability in one place, and works identically regardless of which assistant invoked it.

## Ephemeral tools mode

`yobitsugi run --ephemeral-tools` and `yobitsugi scan --ephemeral-tools` install the pip-installable scanners into a throwaway venv for the duration of one invocation, then delete it. This is what makes the slash-command invocation pattern (`/yobitsugi .` inside any supported assistant) safe to run on machines that don't have scanners installed — there's no leftover state, no `~/.yobitsugi/tools/` to clean up afterwards.

The mechanism has three pieces, all owned by `cli.py` and `core/tools.py`:

| Piece | Module | Responsibility |
| --- | --- | --- |
| `--ephemeral-tools` flag | `cli.py` (registered on both `run` and `scan` subparsers) | Opt-in switch. Default is the persistent `~/.yobitsugi/tools/venv/` behaviour. |
| `_with_optional_ephemeral_tools(fn, args, root)` | `cli.py` | Wraps the body of `cmd_run` / `cmd_scan`. When the flag is set: detect languages → enter `tools.ephemeral_tools_dir()` → install only the pip scanners the repo actually needs → call `fn()` → tear down temp venv in a `finally`. |
| `_quick_detect_languages(root)` | `cli.py` | Calls `detect.detect()` directly to get the language map *before* the pipeline does. This lets the pre-install step target only the relevant scanners, without writing to the real workspace and without ordering it before the pipeline's own `detect` stage. Returns `[]` on any error, in which case the install step falls back to installing every pip scanner. |
| `tools.ephemeral_tools_dir()` | `core/tools.py` | Context manager. Swaps the module-level `TOOLS_DIR` / `VENV_DIR` / `MANIFEST_PATH` to a fresh `tempfile.mkdtemp()` path on entry, restores the originals and `shutil.rmtree`s the temp dir on exit. Cleanup runs in a `finally` block so exceptions and SIGINT both trigger it. |
| `tools.install_missing_pip_scanners(registry, languages=...)` | `core/tools.py` | The programmatic equivalent of `yobitsugi install-scanners`, factored out so `--ephemeral-tools` can call it without spawning a subprocess. Returns `(installed_names, failed_names)`. |

Sequence (one invocation of `yobitsugi run --ephemeral-tools <root>`):

```
cli.main
 └─ cmd_run(args)
     └─ _with_optional_ephemeral_tools(fn=run_pipeline, args, root)
         ├─ _quick_detect_languages(root)              # cheap pre-sniff
         ├─ tools.ephemeral_tools_dir() as tmp:        # mkdtemp + path swap
         │   ├─ tools.install_missing_pip_scanners(registry, languages)
         │   ├─ fn()                                    # → run_pipeline(...)
         │   └─ finally: print teardown
         └─ (context exit) shutil.rmtree(tmp)
```

The `tools.TOOLS_DIR` / `VENV_DIR` / `MANIFEST_PATH` constants are mutated in place so every other module that reads them (e.g. `scan.py` calls `tools.venv_exists()` and `tools.prepend_to_path()`) automatically sees the temp paths. The rule: never `from yobitsugi.core.tools import VENV_DIR` — always `tools.VENV_DIR`. The existing modules all follow this; tests assert the swap is visible to scanners.

`--ephemeral-tools` is intentionally additive: without it, the CLI behaves exactly as before and the persistent `~/.yobitsugi/tools/venv/` workflow is unchanged.

## Extending

### Add a scanner

Edit `yobitsugi/data/scanners.yaml`:

```yaml
Python:
  - name: my-new-tool
    binary: my-new-tool
    command: ["my-new-tool", "--json", "{root}"]
    output: json
    output_path: "{out}/raw/my-new-tool.json"
    timeout: 300
```

Then write a parser function in `yobitsugi/core/parse.py` — see `data/parser_recipes.md` for the contract. Register it in the `PARSERS` dict at the bottom of `parse.py`.

### Add an LLM provider

Edit `yobitsugi/core/llm.py`:

1. Add a `ProviderSpec` entry to the `PROVIDERS` dict.
2. Add a `_build_<name>_request(...)` function that returns a `(url, headers, body)` tuple.
3. Add a `_extract_<name>_response(...)` function that pulls the assistant text out of the response JSON.

That's it. The rest of the pipeline doesn't care which provider you used.

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

Then add the import at the bottom of `installers/base.py`. The registry decorator handles the rest.

## Test architecture

The test suite lives in `tests/` and is organised one-file-per-module. Tests are hermetic by design: nothing touches the network, scanner binaries, or the developer's real `$HOME`.

| Seam | How it's isolated |
| --- | --- |
| `subprocess.run` (git status, patch, scanners) | `monkeypatch` replaces the helper (`_git_is_dirty`, `_apply_with_patch`) with deterministic stubs. |
| `requests.post` (LLM HTTP) | `monkeypatch.setattr(llm.requests, "post", fake_post)` with a `MagicMock` response. |
| `Path.home()` | A `fake_home` fixture in `conftest.py` redirects to a `tmp_path` so installer tests can't escape. |
| LLM env vars | An autouse `_clean_llm_env` fixture strips `*_API_KEY` env vars before every test. |
| Real repos | A `tmp_repo` fixture creates a one-commit git repo inside `tmp_path`. |

The result is that `pytest` runs end-to-end against the full pipeline (with `run_pipeline` calling stubbed stage `main()` functions) in under two seconds, with no hidden global state.

## Design notes

**Why in-process between stages instead of subprocess?** Originally each stage was forked as a subprocess to enforce the JSON-file contract between them. That cost Python-startup overhead per stage, made debugging painful (every error message ate the stack trace), and made the pipeline untestable without spinning up real processes. The current design imports each stage and calls it as a function — but the stages still **read and write JSON files** rather than passing Python objects, so the contract is preserved. Each stage is also still a standalone CLI you can run by hand.

**Why a YAML scanner registry instead of code?** Adding a scanner shouldn't require touching Python. Most additions are "this binary takes these flags, writes JSON to this path" — pure config.

**Why one InstallResult shape for both install and uninstall?** So `cli.py` can treat them uniformly. The `action` field is the only thing that differs.

**Why ship `data/` with the wheel instead of fetching at runtime?** Offline-first. `yobitsugi scan` works without network. Only `fix` needs network (for the LLM call).

**Why a separate pure function for `fix.generate_fix()` and `apply.apply_diff()`?** So the pipeline can call them without going through argv parsing and stdin piping, and so unit tests can exercise the LLM-shaped code path with a mocked `requests.post` rather than forking a process. The original `main()` entry points still exist and still read from stdin / argv — they're just thin wrappers around the pure functions now.

**Why mutate `tools.TOOLS_DIR` for `--ephemeral-tools` instead of threading a path argument through every call site?** Because `scan.py`, `cli.py` and the future installers all reach into `tools` to ask "where's the managed venv?" — passing a path through five layers of function calls just to redirect a single context-manager-scoped run would have been worse, both for the diff size and for the chance of one call site forgetting. The price is a global mutation, which is OK because (a) it's strictly scoped to the lifetime of the context manager, (b) the `finally` restores the originals even on Ctrl-C, and (c) tests already use the same pattern (`fake_home` redirects `Path.home()` globally for the test's duration). The discipline is "everyone reads `tools.VENV_DIR`, nobody copies it into a local at import time" — and the existing modules all follow that.
