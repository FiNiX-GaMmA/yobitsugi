"""Gemini CLI installer.

Gemini CLI looks for commands under ~/.gemini/commands/.
"""
from __future__ import annotations

from pathlib import Path

from yobitsugi.installers.base import Installer, InstallResult, register
from yobitsugi.installers.utils import load_template


@register
class GeminiInstaller(Installer):
    name = "gemini"
    display_name = "Gemini CLI"

    def config_dir(self) -> Path:
        return Path.home() / ".gemini"

    def _target(self, scope: str) -> Path:
        base = Path.cwd() / ".gemini" if scope == "project" else self.config_dir()
        return base / "commands" / "yobitsugi.md"

    def install(self, scope: str = "user") -> InstallResult:
        target = self._target(scope)
        self._write(target, load_template("slash_command.md"))
        return InstallResult(
            self.display_name,
            [target],
            "Invoke with `/yobitsugi .` in Gemini CLI.",
        )

    def uninstall(self, scope: str = "user") -> InstallResult:
        removed = self._remove(self._target(scope))
        return InstallResult(
            self.display_name,
            [removed] if removed else [],
            "" if removed else "nothing to remove.",
            action="uninstalled",
        )
