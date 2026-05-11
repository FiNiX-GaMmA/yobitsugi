"""Base class for platform installers.

Each AI coding assistant has its own way of registering slash commands or skills:
  - Claude Code reads SKILL.md files from ~/.claude/skills/<name>/
  - Codex reads slash commands from ~/.codex/prompts/ or ~/.codex/commands/
  - Cursor reads rules from ~/.cursor/rules/ and supports MCP
  - Gemini CLI reads ~/.gemini/commands/
  - Aider uses .aider.conf.yml + --read flags
  - OpenCode reads ~/.opencode/commands/

The Installer abstraction handles the platform-specific paths and file formats so
the rest of the codebase doesn't have to know about them.
"""
from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class InstallResult:
    """Result of an install operation."""
    platform: str
    installed_paths: list[Path]
    notes: str = ""
    action: str = "installed"

    def __str__(self) -> str:
        if not self.installed_paths:
            return f"[{self.platform}] nothing to {self.action.rstrip('ed').rstrip('e')}."
        paths = "\n  ".join(str(p) for p in self.installed_paths)
        out = f"[{self.platform}] {self.action}:\n  {paths}"
        if self.notes:
            out += f"\n\n{self.notes}"
        return out


class Installer(ABC):
    """One concrete subclass per AI coding assistant.

    Subclasses must define:
      - name: short identifier used on the CLI (`yobitsugi install --platform <name>`)
      - display_name: human-readable name for messages
      - config_dir(): where the platform looks for skills/commands
      - install(): write the slash command / skill files
      - uninstall(): remove them
    """

    name: str = ""
    display_name: str = ""

    @abstractmethod
    def config_dir(self) -> Path:
        """Root config dir for this assistant (e.g. ~/.claude)."""

    @abstractmethod
    def install(self, scope: str = "user") -> InstallResult:
        """Write the slash command. scope='user' or 'project'."""

    @abstractmethod
    def uninstall(self, scope: str = "user") -> InstallResult:
        """Remove the slash command."""

    def is_present(self) -> bool:
        """Heuristic — is this assistant installed on the machine?"""
        return self.config_dir().exists()

    # ---- shared helpers ----

    def _write(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def _remove(self, path: Path) -> Path | None:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return path
        return None


# Registry populated by importing concrete installers.
INSTALLERS: dict[str, type[Installer]] = {}


def register(cls: type[Installer]) -> type[Installer]:
    """Decorator: add a subclass to the global registry."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} has no `name` attribute set")
    INSTALLERS[cls.name] = cls
    return cls


def get_installer(name: str) -> Installer:
    if name not in INSTALLERS:
        valid = ", ".join(sorted(INSTALLERS))
        raise KeyError(f"unknown platform '{name}'. Valid: {valid}")
    return INSTALLERS[name]()


# Trigger concrete-installer registration. Imports are at the bottom to avoid
# circular-import headaches: each concrete file does `from .base import Installer, register`.
from yobitsugi.installers import (  # noqa: E402, F401
    aider,
    claude,
    codex,
    copilot,
    cursor,
    gemini,
    opencode,
)
