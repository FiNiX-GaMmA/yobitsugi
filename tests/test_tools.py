"""Unit tests for yobitsugi.core.tools — managed venv + install plan computation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from yobitsugi.core import tools
from yobitsugi.core.tools import build_install_plans


@pytest.fixture(autouse=True)
def _isolate_tools_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect TOOLS_DIR / VENV_DIR / MANIFEST_PATH into tmp_path for every test."""
    tools_dir = tmp_path / "yobitsugi_tools"
    venv_dir = tools_dir / "venv"
    manifest = tools_dir / "installed.json"
    monkeypatch.setattr(tools, "TOOLS_DIR", tools_dir)
    monkeypatch.setattr(tools, "VENV_DIR", venv_dir)
    monkeypatch.setattr(tools, "MANIFEST_PATH", manifest)
    yield


SAMPLE_REGISTRY = {
    "Python": [
        {
            "name": "bandit",
            "binary": "bandit",
            "command": "...",
            "install": {"method": "pip", "package": "bandit"},
        },
        {
            "name": "safety",
            "binary": "safety",
            "command": "...",
            "install": {"method": "pip", "package": "safety"},
        },
    ],
    "JavaScript": [
        {
            "name": "eslint",
            "binary": "eslint",
            "command": "...",
            "install": {"method": "npm", "package": "eslint", "hint": "npm install -g eslint"},
        },
    ],
    "Shell": [
        {
            "name": "shellcheck",
            "binary": "shellcheck",
            "command": "...",
            "install": {"method": "system", "hint": "brew install shellcheck"},
        },
    ],
    "_cross_language": [
        {
            "name": "semgrep",
            "binary": "semgrep",
            "command": "...",
            "install": {"method": "pip", "package": "semgrep"},
        },
    ],
}


class TestPaths:
    def test_tools_bin_path_unix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        assert tools.tools_bin_path().name == "bin"

    def test_venv_python_unix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        assert tools.venv_python().name == "python"

    def test_venv_exists_false_initially(self) -> None:
        assert tools.venv_exists() is False


class TestManifest:
    def test_load_empty(self) -> None:
        assert tools.load_manifest() == {}

    def test_save_then_load_roundtrip(self) -> None:
        data = {"bandit": {"package": "bandit", "method": "pip"}}
        tools.save_manifest(data)
        assert tools.load_manifest() == data

    def test_load_handles_corrupt_json(self) -> None:
        tools.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        tools.MANIFEST_PATH.write_text("not json {{{")
        assert tools.load_manifest() == {}


class TestBuildInstallPlans:
    def test_emits_one_plan_per_scanner(self) -> None:
        plans = build_install_plans(SAMPLE_REGISTRY)
        names = {p.name for p in plans}
        assert names == {"bandit", "safety", "eslint", "shellcheck", "semgrep"}

    def test_install_method_recorded(self) -> None:
        plans = {p.name: p for p in build_install_plans(SAMPLE_REGISTRY)}
        assert plans["bandit"].method == "pip"
        assert plans["eslint"].method == "npm"
        assert plans["shellcheck"].method == "system"
        assert plans["semgrep"].method == "pip"

    def test_package_passed_through(self) -> None:
        plans = {p.name: p for p in build_install_plans(SAMPLE_REGISTRY)}
        assert plans["bandit"].package == "bandit"
        assert plans["shellcheck"].package is None  # system installs have no package

    def test_filters_by_missing_binaries(self) -> None:
        plans = build_install_plans(SAMPLE_REGISTRY, missing_binaries={"bandit", "semgrep"})
        names = {p.name for p in plans}
        assert names == {"bandit", "semgrep"}

    def test_deduplicates_by_name(self) -> None:
        registry = {
            "Python":     [{"name": "bandit", "binary": "bandit", "command": "...",
                            "install": {"method": "pip", "package": "bandit"}}],
            "JavaScript": [{"name": "bandit", "binary": "bandit", "command": "...",
                            "install": {"method": "pip", "package": "bandit"}}],
        }
        plans = build_install_plans(registry)
        assert len(plans) == 1

    def test_already_installed_flag_when_in_venv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simulate venv with bandit binary present.
        bin_dir = tools.tools_bin_path()
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "python").write_text("")  # so venv_exists() returns True
        (bin_dir / "bandit").write_text("")

        plans = {p.name: p for p in build_install_plans(SAMPLE_REGISTRY)}
        assert plans["bandit"].already_installed is True
        assert plans["safety"].already_installed is False


class TestPrependToPath:
    def test_no_venv_returns_env_unchanged(self) -> None:
        env = {"PATH": "/usr/bin:/bin"}
        result = tools.prepend_to_path(env)
        assert result["PATH"] == "/usr/bin:/bin"

    def test_with_venv_prepends_bin(self) -> None:
        # Bootstrap a fake venv so venv_exists() is True.
        bin_dir = tools.tools_bin_path()
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "python").write_text("")

        env = {"PATH": "/usr/bin:/bin"}
        result = tools.prepend_to_path(env)
        assert result["PATH"].startswith(str(bin_dir))
        assert "/usr/bin:/bin" in result["PATH"]

    def test_idempotent_when_already_present(self) -> None:
        bin_dir = tools.tools_bin_path()
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "python").write_text("")

        env = {"PATH": f"{bin_dir}{os.pathsep}/usr/bin"}
        result = tools.prepend_to_path(env)
        # Bin dir should appear exactly once.
        assert result["PATH"].split(os.pathsep).count(str(bin_dir)) == 1


class TestInstallPythonTool:
    def test_records_in_manifest_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Stub ensure_venv so we don't actually create a venv,
        # and stub subprocess.run to simulate a successful pip install.
        monkeypatch.setattr(tools, "ensure_venv", lambda: tools.tools_bin_path())
        called: dict = {}

        class FakeResult:
            returncode = 0
            stderr = ""
            stdout = "Successfully installed bandit-1.7.5"

        def fake_run(cmd, capture_output, text):
            called["cmd"] = cmd
            return FakeResult()

        monkeypatch.setattr(tools.subprocess, "run", fake_run)
        ok, msg = tools.install_python_tool("bandit", "bandit")
        assert ok is True
        assert "bandit" in called["cmd"]
        assert tools.load_manifest()["bandit"] == {"package": "bandit", "method": "pip"}

    def test_failure_does_not_update_manifest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tools, "ensure_venv", lambda: tools.tools_bin_path())

        class FakeResult:
            returncode = 1
            stderr = "ERROR: no such package"
            stdout = ""

        monkeypatch.setattr(tools.subprocess, "run", lambda *a, **kw: FakeResult())
        ok, msg = tools.install_python_tool("nonsuch", "nonsuch")
        assert ok is False
        assert "no such package" in msg
        assert "nonsuch" not in tools.load_manifest()


class TestUninstallAll:
    def test_removes_tools_dir(self) -> None:
        tools.TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        (tools.TOOLS_DIR / "stuff").write_text("x")
        removed = tools.uninstall_all()
        assert removed == tools.TOOLS_DIR
        assert not tools.TOOLS_DIR.exists()

    def test_returns_none_when_nothing_to_remove(self) -> None:
        assert tools.uninstall_all() is None


class TestMainCli:
    def test_show_prints_paths(self, capsys: pytest.CaptureFixture) -> None:
        rc = tools.main(["show"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "venv:" in out
        assert "bin dir:" in out

    def test_clean_when_empty(self, capsys: pytest.CaptureFixture) -> None:
        rc = tools.main(["clean"])
        assert rc == 0
        assert "nothing to remove" in capsys.readouterr().out

    def test_clean_removes_existing(self, capsys: pytest.CaptureFixture) -> None:
        tools.TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        rc = tools.main(["clean"])
        assert rc == 0
        assert "removed" in capsys.readouterr().out
