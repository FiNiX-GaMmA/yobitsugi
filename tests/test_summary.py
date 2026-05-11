"""Unit tests for yobitsugi.core.summary — scan-side tabular report.

The summary used to include fix/apply/validation totals (Fixes applied,
Newly introduced, etc.) when yobitsugi shipped a full `run` pipeline. That
pipeline moved into the host AI assistant in v0.2 — the summary is now
purely scan-side: findings, missing scanners, recommended next actions.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yobitsugi.core import summary as summary_mod
from yobitsugi.core.summary import build_summary, render_markdown


@pytest.fixture
def ws_full(tmp_path: Path) -> Path:
    """A workspace with findings + scan_report populated.

    Skill-first: applied.json / validation.json are NOT written by the CLI
    anymore. Fixture mirrors what `yobitsugi scan` actually produces.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    findings = [
        {"id": "a1", "tool": "bandit", "severity": "HIGH", "type": "SQL_INJECTION",
         "file": "app.py", "line": 10, "title": "sqli", "description": "SQL injection"},
        {"id": "b2", "tool": "semgrep", "severity": "MEDIUM", "type": "XSS",
         "file": "view.py", "line": 22, "title": "xss", "description": "XSS"},
        {"id": "c3", "tool": "safety", "severity": "CRITICAL", "type": "VULNERABLE_DEPENDENCY",
         "file": None, "line": None, "title": "vuln pkg", "description": "CVE"},
    ]
    (ws / "findings.json").write_text(json.dumps(findings))
    scan_report = {
        "scanners": [
            {"name": "bandit", "status": "ok"},
            {"name": "semgrep", "status": "skipped_missing_tool", "binary": "semgrep",
             "install_method": "pip", "install_package": "semgrep"},
            {"name": "eslint", "status": "skipped_missing_tool", "binary": "eslint",
             "install_method": "npm", "install_hint": "npm install -g eslint"},
        ],
    }
    (ws / "scan_report.json").write_text(json.dumps(scan_report))
    return ws


class TestBuildSummary:
    def test_empty_workspace(self, tmp_path: Path) -> None:
        ws = tmp_path / "empty"
        ws.mkdir()
        s = build_summary(ws)
        assert s["totals"]["findings"] == 0
        assert s["findings"] == []
        assert s["missing_scanners"] == []
        # Even with nothing, we always suggest at least one next action.
        assert len(s["next_actions"]) >= 1

    def test_totals_aggregated(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        totals = s["totals"]
        assert totals["findings"] == 3
        assert totals["scanners_ok"] == 1
        assert totals["scanners_skipped_missing_tool"] == 2
        assert totals["scanners_errored"] == 0
        assert totals["missing_scanners"] == 2

    def test_finding_fields_preserved(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        by_id = {r["id"]: r for r in s["findings"]}
        assert by_id["a1"]["severity"] == "HIGH"
        assert by_id["a1"]["tool"] == "bandit"
        assert by_id["a1"]["file"] == "app.py"
        assert by_id["a1"]["line"] == 10

    def test_missing_scanners_extracted(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        names = {m["name"] for m in s["missing_scanners"]}
        assert names == {"semgrep", "eslint"}

    def test_corrupt_json_is_treated_as_empty(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "findings.json").write_text("not json {{{")
        s = build_summary(ws)
        assert s["totals"]["findings"] == 0

    def test_no_fix_or_validation_keys_in_totals(self, ws_full: Path) -> None:
        # Regression for the v0.2 trim: confirm none of the old keys leak in.
        s = build_summary(ws_full)
        for key in ("applied", "rolled_back", "not_attempted",
                    "fixed", "still_present", "newly_introduced"):
            assert key not in s["totals"], f"stale fix-side key {key!r} in totals"


class TestNextActions:
    def test_missing_pip_scanners_triggers_install(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        labels = [a["label"] for a in s["next_actions"]]
        assert any("install" in lbl.lower() and "semgrep" in lbl.lower() for lbl in labels)

    def test_missing_npm_scanner_triggers_manual_install_hint(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        labels = [a["label"] for a in s["next_actions"]]
        assert any("non-Python" in lbl or "non-python" in lbl.lower() for lbl in labels)

    def test_high_severity_triggers_fix_handoff(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        labels = [a["label"] for a in s["next_actions"]]
        assert any("Walk the host AI assistant" in lbl for lbl in labels)

    def test_no_missing_means_no_install_action(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "findings.json").write_text("[]")
        s = build_summary(ws)
        assert not any("install-scanners" in a["command"] for a in s["next_actions"])

    def test_no_rollback_suggestion(self, ws_full: Path) -> None:
        # `yobitsugi rollback` was removed in v0.2 — the assistant owns undo.
        # Test the labels (not commands — the workspace path can contain the
        # word "rollback" if the test name does, which is what pytest's
        # tmp_path does).
        s = build_summary(ws_full)
        for a in s["next_actions"]:
            assert "rollback" not in a["label"].lower()
            assert "yobitsugi rollback" not in a["command"]


class TestMarkdownRendering:
    def test_contains_core_headers(self, ws_full: Path) -> None:
        md = render_markdown(build_summary(ws_full))
        for header in ("## Run totals", "## Findings by severity", "## Findings",
                       "## Missing scanners", "## What next?"):
            assert header in md

    def test_markdown_tables_well_formed(self, ws_full: Path) -> None:
        md = render_markdown(build_summary(ws_full))
        # Every markdown table has a header separator line `| --- |`.
        # Run totals + severity + findings + missing scanners + what-next = 5.
        assert md.count("| ---") >= 5

    def test_no_fix_or_validation_columns(self, ws_full: Path) -> None:
        md = render_markdown(build_summary(ws_full))
        for stale in ("Fix outcome", "Validation", "Newly introduced",
                      "rolled back", "newly-introduced"):
            assert stale not in md, f"stale fix-side column {stale!r} still in markdown"

    def test_no_findings_no_findings_table(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        md = render_markdown(build_summary(ws))
        # Sections that have no data shouldn't be emitted.
        assert "## Findings\n" not in md
        assert "## Missing scanners" not in md

    def test_pipe_chars_in_titles_escaped(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "findings.json").write_text(json.dumps([{
            "id": "x", "tool": "bandit", "severity": "HIGH", "type": "SQL_INJECTION",
            "file": "app.py", "line": 1, "title": "a | b | c",
        }]))
        md = render_markdown(build_summary(ws))
        # Pipes inside table cells must be escaped or they'd break the table layout.
        assert "a \\| b \\| c" in md


class TestSummaryMainCli:
    def test_main_errors_on_missing_workspace(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rc = summary_mod.main([str(tmp_path / "nope"), "--format", "json"])
        assert rc == 1

    def test_json_format(self, ws_full: Path, capsys: pytest.CaptureFixture) -> None:
        rc = summary_mod.main([str(ws_full), "--format", "json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["totals"]["findings"] == 3
        assert data["totals"]["scanners_skipped_missing_tool"] == 2

    def test_markdown_format(self, ws_full: Path, capsys: pytest.CaptureFixture) -> None:
        rc = summary_mod.main([str(ws_full), "--format", "markdown"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "## Run totals" in out
        assert "| Sev | Type | Tool | File:Line" in out

    def test_rich_format_produces_output(
        self, ws_full: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rc = summary_mod.main([str(ws_full), "--format", "rich"])
        assert rc == 0
        out = capsys.readouterr().out
        # Rich uses unicode box-drawing for table borders; presence is enough.
        assert "Run totals" in out
        assert "Findings" in out
