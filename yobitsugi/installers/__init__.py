"""Per-platform installers — register the /yobitsugi slash command with each AI assistant."""

from yobitsugi.installers.base import INSTALLERS, Installer, get_installer

__all__ = ["Installer", "INSTALLERS", "get_installer"]
