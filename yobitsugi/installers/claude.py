"""Claude Code installer.

Claude Code looks for SKILL.md files under:
  ~/.claude/skills/<name>/SKILL.md       (user scope)
  ./.claude/skills/<name>/SKILL.md       (project scope)

We ship the canonical SKILL.md bundled inside the wheel at `yobitsugi/data/SKILL.md`
and copy it verbatim on install. This keeps a single source of truth: the repo-root
SKILL.md (for users who drop the repo into ~/.claude/skills/ manually) and the
installer-written SKILL.md (for users who go through `yobitsugi install`) are the
exact same file.
"""
from __future__ import annotations

from pathlib import Path

from yobitsugi.installers.base import Installer, InstallResult, register


PKG_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_SKILL = PKG_ROOT / "data" / "SKILL.md"


@register
class ClaudeCodeInstaller(Installer):
    name = "claude"
    display_name = "Claude Code"

    def config_dir(self) -> Path:
        return Path.home() / ".claude"

    def _target(self, scope: str) -> Path:
        if scope == "project":
            base = Path.cwd() / ".claude"
        else:
            base = self.config_dir()
        return base / "skills" / "yobitsugi" / "SKILL.md"

    def install(self, scope: str = "user") -> InstallResult:
        target = self._target(scope)
        if not BUNDLED_SKILL.exists():
            raise RuntimeError(
                f"bundled SKILL.md not found at {BUNDLED_SKILL}. "
                "This is a packaging bug — please report it."
            )
        self._write(target, BUNDLED_SKILL.read_text())
        notes = (
            "Claude Code will pick up the skill automatically on the next prompt.\n"
            "Invoke with `/yobitsugi .` or describe the security task in chat."
        )
        return InstallResult(self.display_name, [target], notes)

    def uninstall(self, scope: str = "user") -> InstallResult:
        target = self._target(scope).parent  # remove the whole skill dir
        removed = self._remove(target)
        return InstallResult(
            self.display_name,
            [removed] if removed else [],
            "" if removed else "nothing to remove.",
            action="uninstalled",
        )
