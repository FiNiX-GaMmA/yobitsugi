"""Codex (codex-cli) installer.

Codex stores reusable prompts as plain markdown files under ~/.codex/prompts/.
Invoke with `$yobitsugi .` (Codex uses `$` rather than `/` for command expansion).
"""
from __future__ import annotations

from pathlib import Path

from yobitsugi.installers.base import Installer, InstallResult, register
from yobitsugi.installers.utils import load_template


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
        self._write(target, load_template("slash_command.md"))
        notes = (
            "Codex picks up prompts on the next session.\n"
            "Invoke with `$yobitsugi .` (Codex uses $, not /).\n"
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
