"""Unit tests for yobitsugi.cli — argument parsing + subcommand dispatch."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yobitsugi import cli


class TestVersionCommand:
    def test_prints_version(self, capsys: pytest.CaptureFixture) -> None:
        rc = cli.main(["version"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "yobitsugi" in out


class TestListPlatforms:
    def test_lists_all(self, capsys: pytest.CaptureFixture) -> None:
        rc = cli.main(["list-platforms"])
        assert rc == 0
        out = capsys.readouterr().out
        for platform in ("claude", "codex", "cursor", "gemini", "aider", "opencode", "copilot"):
            assert platform in out


class TestDetectPlatforms:
    def test_returns_one_when_none_detected(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force every installer to report not-present.
        for cls in cli.INSTALLERS.values():
            monkeypatch.setattr(cls, "is_present", lambda self: False)
        rc = cli.main(["detect-platforms"])
        assert rc == 1


class TestPositionalShortcut:
    def test_path_becomes_run(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake_run(args):
            captured["path"] = args.path
            return 0

        monkeypatch.setattr(cli, "cmd_run", fake_run)
        rc = cli.main([str(tmp_repo)])
        assert rc == 0
        assert captured["path"] == tmp_repo

    def test_flag_first_arg_still_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Flags shouldn't get reinterpreted as a path.
        # Should hit normal argparse error handling.
        with pytest.raises(SystemExit):
            cli.main(["--badflag"])


class TestConfigCommand:
    def test_init_writes_config(
        self, fake_home: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rc = cli.main(["config", "--init"])
        assert rc == 0
        cfg = fake_home / ".yobitsugi" / "config.yaml"
        assert cfg.exists()
        assert "provider" in cfg.read_text()

    def test_init_refuses_overwrite_without_force(
        self, fake_home: Path
    ) -> None:
        cli.main(["config", "--init"])
        rc = cli.main(["config", "--init"])
        assert rc == 1

    def test_init_with_force_overwrites(self, fake_home: Path) -> None:
        cli.main(["config", "--init"])
        rc = cli.main(["config", "--init", "--force"])
        assert rc == 0

    def test_print_resolves_config(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        rc = cli.main(["config"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["provider"] == "openai"
        assert data["api_key_set"] is True


class TestFindingsCommand:
    def _make_workspace(
        self, tmp_path: Path, findings: list[dict]
    ) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "findings.json").write_text(json.dumps(findings))
        return ws

    def test_missing_findings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        rc = cli.main(["findings", str(ws)])
        assert rc == 1

    def test_severity_filter(
        self, tmp_path: Path, findings_with_severities: list[dict],
        capsys: pytest.CaptureFixture,
    ) -> None:
        ws = self._make_workspace(tmp_path, findings_with_severities)
        cli.main(["findings", str(ws), "--severity", "CRITICAL", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["severity"] == "CRITICAL"

    def test_type_filter(
        self, tmp_path: Path, findings_with_severities: list[dict],
        capsys: pytest.CaptureFixture,
    ) -> None:
        ws = self._make_workspace(tmp_path, findings_with_severities)
        cli.main(["findings", str(ws), "--type", "SQL_INJECTION", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert all(f["type"] == "SQL_INJECTION" for f in data)

    def test_pretty_print_default(
        self, tmp_path: Path, findings_with_severities: list[dict],
        capsys: pytest.CaptureFixture,
    ) -> None:
        ws = self._make_workspace(tmp_path, findings_with_severities)
        rc = cli.main(["findings", str(ws)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "CRITICAL" in out or "HIGH" in out


class TestNoSubcommand:
    def test_prints_help(self, capsys: pytest.CaptureFixture) -> None:
        rc = cli.main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "yobitsugi" in out.lower() or "Usage" in out or "usage" in out


class TestRunCommand:
    def test_run_dispatches_to_pipeline(
        self, tmp_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake_pipeline(**kwargs):
            captured.update(kwargs)
            return 0

        # cmd_run imports run_pipeline lazily, so patch on the module.
        import yobitsugi.core.pipeline as p
        monkeypatch.setattr(p, "run_pipeline", fake_pipeline)
        rc = cli.main(["run", str(tmp_repo), "--auto", "--allow-dirty"])
        assert rc == 0
        assert captured["root"] == tmp_repo
        assert captured["auto"] is True
        assert captured["allow_dirty"] is True


class TestScannerToolingCommands:
    @pytest.fixture(autouse=True)
    def _isolate_tools_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from yobitsugi.core import tools
        tools_dir = tmp_path / "yobi_tools"
        monkeypatch.setattr(tools, "TOOLS_DIR", tools_dir)
        monkeypatch.setattr(tools, "VENV_DIR", tools_dir / "venv")
        monkeypatch.setattr(tools, "MANIFEST_PATH", tools_dir / "installed.json")

    def test_list_scanners_outputs_every_scanner(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        rc = cli.main(["list-scanners"])
        assert rc == 0
        out = capsys.readouterr().out
        for expected in ("bandit", "safety", "semgrep", "eslint", "shellcheck"):
            assert expected in out

    def test_install_scanners_with_nothing_missing(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Make every binary "found" so install-scanners has nothing to do.
        monkeypatch.setattr("shutil.which", lambda _binary: "/usr/local/bin/fake")
        rc = cli.main(["install-scanners"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no Python scanners need installing" in out

    def test_install_scanners_calls_pip(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No binaries on PATH, so every pip-installable scanner is "missing".
        monkeypatch.setattr("shutil.which", lambda _binary: None)

        from yobitsugi.core import tools
        installed: list[str] = []

        def fake_install(name, package):
            installed.append(name)
            return True, "ok"

        monkeypatch.setattr(tools, "ensure_venv", lambda: tools.tools_bin_path())
        monkeypatch.setattr(tools, "install_python_tool", fake_install)
        rc = cli.main(["install-scanners"])
        assert rc == 0
        # bandit / safety / pip-audit / semgrep / flawfinder are all pip-installable.
        for expected in ("bandit", "safety", "pip-audit", "semgrep", "flawfinder"):
            assert expected in installed
        out = capsys.readouterr().out
        # Non-Python scanners should be listed as manual installs.
        assert "non-Python scanners" in out
        assert "eslint" in out
        assert "shellcheck" in out

    def test_install_scanners_reports_failures(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _binary: None)

        from yobitsugi.core import tools

        def fake_install(name, package):
            return False, "boom"

        monkeypatch.setattr(tools, "ensure_venv", lambda: tools.tools_bin_path())
        monkeypatch.setattr(tools, "install_python_tool", fake_install)
        rc = cli.main(["install-scanners"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "failed" in out.lower()

    def test_uninstall_scanners_when_empty(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        rc = cli.main(["uninstall-scanners"])
        assert rc == 0
        assert "nothing to remove" in capsys.readouterr().out
