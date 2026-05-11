"""Aider installer.

Aider doesn't have a native slash-command system, but it supports `--read` files that
are included in every session. We write a yobitsugi brief there and update the
`.aider.conf.yml` to load it automatically.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from yobitsugi.installers.base import Installer, InstallResult, register
from yobitsugi.installers.utils import load_template


@register
class AiderInstaller(Installer):
    name = "aider"
    display_name = "Aider"

    def config_dir(self) -> Path:
        # Aider's per-user config lives at ~/.aider.conf.yml.
        return Path.home()

    def _brief_path(self, scope: str) -> Path:
        if scope == "project":
            return Path.cwd() / ".aider" / "yobitsugi.md"
        return Path.home() / ".aider" / "yobitsugi.md"

    def _conf_path(self, scope: str) -> Path:
        if scope == "project":
            return Path.cwd() / ".aider.conf.yml"
        return Path.home() / ".aider.conf.yml"

    def is_present(self) -> bool:
        return self._conf_path("user").exists() or self._conf_path("project").exists()

    def install(self, scope: str = "user") -> InstallResult:
        brief = self._brief_path(scope)
        self._write(brief, load_template("slash_command.md"))

        conf_path = self._conf_path(scope)
        conf: dict = {}
        if conf_path.exists():
            conf = yaml.safe_load(conf_path.read_text()) or {}

        reads = conf.get("read", []) or []
        if not isinstance(reads, list):
            reads = [reads]
        if str(brief) not in reads:
            reads.append(str(brief))
        conf["read"] = reads

        conf_path.write_text(yaml.safe_dump(conf, sort_keys=False))

        notes = (
            "Aider has no slash-command system, so yobitsugi is loaded as a `--read` brief.\n"
            "In an aider session, ask: 'run the yobitsugi pipeline on this repo'."
        )
        return InstallResult(self.display_name, [brief, conf_path], notes)

    def uninstall(self, scope: str = "user") -> InstallResult:
        removed: list[Path] = []
        brief = self._brief_path(scope)
        r = self._remove(brief)
        if r:
            removed.append(r)

        conf_path = self._conf_path(scope)
        if conf_path.exists():
            conf = yaml.safe_load(conf_path.read_text()) or {}
            reads = conf.get("read", []) or []
            if isinstance(reads, list):
                reads = [r for r in reads if r != str(brief)]
                if reads:
                    conf["read"] = reads
                else:
                    conf.pop("read", None)
                conf_path.write_text(yaml.safe_dump(conf, sort_keys=False))
                removed.append(conf_path)

        return InstallResult(
            self.display_name,
            removed,
            "" if removed else "nothing to remove.",
            action="uninstalled",
        )
