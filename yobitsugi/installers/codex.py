"""Codex (codex-cli) installer.

Codex stores reusable prompts as plain markdown files under ~/.codex/prompts/.
It reads a YAML frontmatter block at the top of each file for display metadata:
`name` becomes the prompt's title in the picker, `description` becomes the one-line
summary, and `trigger` is the slash-command alias.

Without the frontmatter Codex falls back to showing the bare filename (e.g.
"prompts:yobitsugi") which is ugly. We prepend the frontmatter to the shared
template body when writing the prompt file.
"""
from __future__ import annotations

from pathlib import Path

from yobitsugi.installers.base import Installer, InstallResult, register
from yobitsugi.installers.utils import load_template

CODEX_FRONTMATTER = """---
name: yobitsugi
description: "SAST/SCA scan + LLM-generated unified-diff fixes for the current repo. \
Scans with bandit, semgrep, gosec, safety, pip-audit, eslint, trufflehog and friends; \
patches CRITICAL/HIGH findings with backups and a rollback log; generates a regression \
test per fix; re-scans to confirm. Use when the user wants to audit a repo for security \
issues, fix CVEs, or check for SQL injection / XSS / hardcoded secrets / vulnerable \
dependencies."
trigger: /yobitsugi
---

"""


@register
class CodexInstaller(Installer):
    name = "codex"
    display_name = "Codex"

    def config_dir(self) -> Path:
        return Path.home() / ".codex"

    def _target(self, scope: str) -> Path:
        base = Path.cwd() / ".codex" if scope == "project" else self.config_dir()
        return base / "prompts" / "yobitsugi.md"

    def install(self, scope: str = "user") -> InstallResult:
        target = self._target(scope)
        body = CODEX_FRONTMATTER + load_template("slash_command.md")
        self._write(target, body)
        notes = (
            "Codex picks up prompts on the next session.\n"
            "Invoke with `/yobitsugi .` — the prompt picker will show "
            "'yobitsugi  SAST/SCA scan + LLM-generated …'.\n"
            "Make sure `multi_agent = true` is set under [features] in ~/.codex/config.toml."
        )
        return InstallResult(self.display_name, [target], notes)

    def uninstall(self, scope: str = "user") -> InstallResult:
        removed = self._remove(self._target(scope))
        return InstallResult(
            self.display_name,
            [removed] if removed else [],
            "" if removed else "nothing to remove.",
            action="uninstalled",
        )
