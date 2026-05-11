"""Cursor installer.

Cursor reads `.mdc` rule files from `.cursor/rules/`. A rule with `alwaysApply: false`
and a descriptive trigger gets surfaced as a discoverable command.
"""
from __future__ import annotations

from pathlib import Path

from yobitsugi.installers.base import Installer, InstallResult, register
from yobitsugi.installers.utils import load_template


CURSOR_FRONTMATTER = """---
description: Scan repository for security vulnerabilities and generate LLM-driven fixes
globs: ["**/*"]
alwaysApply: false
---

"""


@register
class CursorInstaller(Installer):
    name = "cursor"
    display_name = "Cursor"

    def config_dir(self) -> Path:
        return Path.home() / ".cursor"

    def _target(self, scope: str) -> Path:
        # Cursor rules are usually project-scoped.
        base = Path.cwd() / ".cursor" if scope == "project" else self.config_dir()
        return base / "rules" / "yobitsugi.mdc"

    def install(self, scope: str = "project") -> InstallResult:
        target = self._target(scope)
        body = CURSOR_FRONTMATTER + load_template("slash_command.md")
        self._write(target, body)
        notes = (
            "Cursor will surface the rule when the user mentions security scanning.\n"
            "Default scope is `project` (writes to ./.cursor/rules/); pass --scope user\n"
            "to install globally."
        )
        return InstallResult(self.display_name, [target], notes)

    def uninstall(self, scope: str = "project") -> InstallResult:
        removed = self._remove(self._target(scope))
        return InstallResult(
            self.display_name,
            [removed] if removed else [],
            "" if removed else "nothing to remove.",
            action="uninstalled",
        )
