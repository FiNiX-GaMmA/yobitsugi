"""Unit tests for yobitsugi.installers — per-platform skill installation."""
from __future__ import annotations

from pathlib import Path

import pytest

from yobitsugi.installers import INSTALLERS, Installer, get_installer
from yobitsugi.installers.base import InstallResult


class TestRegistry:
    def test_all_expected_platforms_registered(self) -> None:
        for name in ("claude", "codex", "cursor", "gemini", "aider", "opencode", "copilot"):
            assert name in INSTALLERS

    def test_each_installer_has_required_attrs(self) -> None:
        for name, cls in INSTALLERS.items():
            inst = cls()
            assert inst.name == name
            assert inst.display_name
            assert callable(inst.config_dir)
            assert callable(inst.install)
            assert callable(inst.uninstall)

    def test_get_installer_returns_instance(self) -> None:
        inst = get_installer("claude")
        assert isinstance(inst, Installer)
        assert inst.name == "claude"

    def test_get_installer_unknown_raises(self) -> None:
        with pytest.raises(KeyError, match="unknown platform"):
            get_installer("notapanormallinstaller")


class TestInstallResult:
    def test_str_with_paths(self, tmp_path: Path) -> None:
        result = InstallResult("Claude", [tmp_path / "a.md"], notes="run it")
        s = str(result)
        assert "Claude" in s
        assert "installed" in s
        assert "a.md" in s
        assert "run it" in s

    def test_str_with_no_paths(self) -> None:
        result = InstallResult("Cursor", [], action="uninstalled")
        s = str(result)
        assert "Cursor" in s
        assert "nothing" in s

    def test_uninstall_action(self, tmp_path: Path) -> None:
        result = InstallResult("Aider", [tmp_path / "x"], action="uninstalled")
        assert "uninstalled" in str(result)


class TestClaudeInstaller:
    def test_install_user_scope(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inst = get_installer("claude")
        result = inst.install(scope="user")
        target = fake_home / ".claude" / "skills" / "yobitsugi" / "SKILL.md"
        assert target.exists()
        assert result.action == "installed"
        assert target in result.installed_paths

    def test_install_project_scope(
        self, fake_home: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.chdir(project)
        inst = get_installer("claude")
        inst.install(scope="project")
        target = project / ".claude" / "skills" / "yobitsugi" / "SKILL.md"
        assert target.exists()

    def test_uninstall_removes(self, fake_home: Path) -> None:
        inst = get_installer("claude")
        inst.install(scope="user")
        result = inst.uninstall(scope="user")
        target_dir = fake_home / ".claude" / "skills" / "yobitsugi"
        assert not target_dir.exists()
        assert result.action == "uninstalled"

    def test_uninstall_when_not_installed(self, fake_home: Path) -> None:
        inst = get_installer("claude")
        result = inst.uninstall(scope="user")
        assert result.installed_paths == []


class TestIsPresent:
    def test_returns_true_when_config_dir_exists(
        self, fake_home: Path
    ) -> None:
        inst = get_installer("claude")
        # config_dir is ~/.claude — create it.
        (fake_home / ".claude").mkdir()
        assert inst.is_present() is True

    def test_returns_false_when_config_dir_absent(
        self, fake_home: Path
    ) -> None:
        inst = get_installer("claude")
        assert inst.is_present() is False


class TestAllInstallersWork:
    """Smoke test: every registered installer should round-trip install→uninstall."""

    @pytest.mark.parametrize("name", sorted(INSTALLERS.keys()))
    def test_install_uninstall_roundtrip(
        self, name: str, fake_home: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        inst = get_installer(name)
        try:
            result = inst.install(scope="user")
            assert result.action == "installed"
            # At least one file should have been written.
            assert any(p and p.exists() for p in result.installed_paths)
        finally:
            inst.uninstall(scope="user")
