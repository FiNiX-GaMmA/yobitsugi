"""GitHub Copilot CLI installer.

GitHub Copilot CLI supports custom instruction files. We write one to
~/.config/github-copilot/intellij/instructions/ (Linux) or platform-equivalent.
"""
from __future__ import annotations

import platform
from pathlib import Path

from yobitsugi.installers.base import Installer, InstallResult, register
from yobitsugi.installers.utils import load_template


@register
class CopilotInstaller(Installer):
    name = "copilot"
    display_name = "GitHub Copilot CLI"

    def config_dir(self) -> Path:
        if platform.system() == "Darwin":
            return Path.home() / "Library" / "Application Support" / "GitHub Copilot"
        if platform.system() == "Windows":
            return Path.home() / "AppData" / "Roaming" / "GitHub Copilot"
        return Path.home() / ".config" / "github-copilot"

    def _target(self, scope: str) -> Path:
        base = Path.cwd() / ".github" if scope == "project" else self.config_dir()
        return base / "copilot-instructions" / "yobitsugi.md"

    def install(self, scope: str = "user") -> InstallResult:
        target = self._target(scope)
        self._write(target, load_template("slash_command.md"))
        notes = (
            "Copilot's slash-command surface area is limited; yobitsugi is installed\n"
            "as a custom instruction file. Reference it in chat with `@yobitsugi`."
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
