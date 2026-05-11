"""Unit tests for yobitsugi.core.pipeline — end-to-end orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yobitsugi.core import pipeline


@pytest.fixture
def stub_stages(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """Stub every pipeline stage. Returns a dict tracking what was called."""
    calls: dict[str, list] = {
        "detect": [], "scan": [], "parse": [],
        "generate_fix": [], "apply_diff": [],
        "tests_gen": [], "validate": [],
    }

    def make_stub(name: str, rc: int = 0):
        def stub(argv=None, *args, **kwargs):
            calls[name].append(argv or args or kwargs)
            return rc
        return stub

    monkeypatch.setattr(pipeline.detect, "main", make_stub("detect"))
    monkeypatch.setattr(pipeline.scan, "main", make_stub("scan"))
    monkeypatch.setattr(pipeline.parse, "main", make_stub("parse"))
    monkeypatch.setattr(pipeline.tests_gen, "main", make_stub("tests_gen"))
    monkeypatch.setattr(pipeline.validate, "main", make_stub("validate"))

    def stub_generate(finding, root, **kwargs):
        calls["generate_fix"].append({"finding": finding, "root": root, **kwargs})
        return "--- a/x.py\n+++ b/x.py\n@@\n-a\n+b\n"

    def stub_apply(diff, root, workspace, **kwargs):
        calls["apply_diff"].append({"diff": diff, "root": root, **kwargs})
        return 0

    monkeypatch.setattr(pipeline.fix, "generate_fix", stub_generate)
    monkeypatch.setattr(pipeline.apply_mod, "apply_diff", stub_apply)
    return calls


def _write_findings(workspace: Path, findings: list[dict]) -> None:
    (workspace / "findings.json").write_text(json.dumps(findings))


class TestRunPipeline:
    def test_returns_one_when_root_missing(self, tmp_path: Path) -> None:
        rc = pipeline.run_pipeline(root=tmp_path / "nope")
        assert rc == 1

    def test_all_stages_invoked_in_order(
        self, tmp_repo: Path, tmp_workspace: Path, stub_stages
    ) -> None:
        _write_findings(tmp_workspace, [])

        rc = pipeline.run_pipeline(
            root=tmp_repo, workspace=tmp_workspace, severity=["HIGH"],
        )

        assert rc == 0
        assert stub_stages["detect"]
        assert stub_stages["scan"]
        assert stub_stages["parse"]

    def test_no_findings_skips_fix_and_validate(
        self, tmp_repo: Path, tmp_workspace: Path, stub_stages
    ) -> None:
        _write_findings(tmp_workspace, [])
        pipeline.run_pipeline(root=tmp_repo, workspace=tmp_workspace)
        assert stub_stages["generate_fix"] == []
        # tests + validate are not invoked when there's nothing to fix.
        assert stub_stages["tests_gen"] == []
        assert stub_stages["validate"] == []

    def test_severity_filter_applied(
        self, tmp_repo: Path, tmp_workspace: Path,
        stub_stages, findings_with_severities: list[dict],
    ) -> None:
        _write_findings(tmp_workspace, findings_with_severities)

        pipeline.run_pipeline(
            root=tmp_repo, workspace=tmp_workspace,
            severity=["CRITICAL"], auto=True, allow_dirty=True,
        )

        # Only one finding matches CRITICAL.
        assert len(stub_stages["generate_fix"]) == 1
        assert stub_stages["generate_fix"][0]["finding"]["severity"] == "CRITICAL"

    def test_skip_tests_flag(
        self, tmp_repo: Path, tmp_workspace: Path,
        stub_stages, findings_with_severities: list[dict],
    ) -> None:
        _write_findings(tmp_workspace, findings_with_severities)

        pipeline.run_pipeline(
            root=tmp_repo, workspace=tmp_workspace,
            severity=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
            auto=True, allow_dirty=True, skip_tests=True,
        )
        assert stub_stages["tests_gen"] == []
        # validate still runs.
        assert stub_stages["validate"]

    def test_failed_detect_aborts(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pipeline.detect, "main", lambda argv=None: 1)
        rc = pipeline.run_pipeline(root=tmp_repo, workspace=tmp_workspace)
        assert rc == 1

    def test_failed_fix_continues_to_next(
        self, tmp_repo: Path, tmp_workspace: Path,
        stub_stages, monkeypatch: pytest.MonkeyPatch,
        findings_with_severities: list[dict],
    ) -> None:
        _write_findings(tmp_workspace, findings_with_severities[:2])

        def failing_fix(finding, root, **kwargs):
            raise RuntimeError("LLM exploded")

        monkeypatch.setattr(pipeline.fix, "generate_fix", failing_fix)

        rc = pipeline.run_pipeline(
            root=tmp_repo, workspace=tmp_workspace,
            severity=["CRITICAL", "HIGH"], auto=True, allow_dirty=True,
        )
        assert rc == 0  # pipeline doesn't abort on per-finding LLM errors
        # No diffs were applied because every fix failed.
        assert stub_stages["apply_diff"] == []

    def test_empty_diff_skipped(
        self, tmp_repo: Path, tmp_workspace: Path,
        stub_stages, monkeypatch: pytest.MonkeyPatch,
        findings_with_severities: list[dict],
    ) -> None:
        _write_findings(tmp_workspace, findings_with_severities[:1])
        monkeypatch.setattr(pipeline.fix, "generate_fix", lambda *a, **k: "")

        pipeline.run_pipeline(
            root=tmp_repo, workspace=tmp_workspace,
            severity=["CRITICAL"], auto=True, allow_dirty=True,
        )
        assert stub_stages["apply_diff"] == []


class TestPipelineMain:
    def test_main_calls_run_pipeline(
        self, tmp_repo: Path, tmp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return 0

        monkeypatch.setattr(pipeline, "run_pipeline", fake_run)
        rc = pipeline.main([
            "--root", str(tmp_repo),
            "--workspace", str(tmp_workspace),
            "--severity", "HIGH",
            "--auto", "--allow-dirty", "--skip-tests",
        ])
        assert rc == 0
        assert captured["root"] == tmp_repo
        assert captured["auto"] is True
        assert captured["allow_dirty"] is True
        assert captured["skip_tests"] is True
        assert captured["severity"] == ["HIGH"]
