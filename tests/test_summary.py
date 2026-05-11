"""Unit tests for yobitsugi.core.summary — tabular post-run report."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yobitsugi.core import summary as summary_mod
from yobitsugi.core.summary import build_summary, render_markdown


@pytest.fixture
def ws_full(tmp_path: Path) -> Path:
    """A workspace with findings + applied + validation + scan_report all populated."""
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
    applied = [
        {"finding_id": "a1", "files": ["app.py"], "info": "applied"},
        {"finding_id": "c3", "files": ["requirements.txt"], "info": "applied",
         "rolled_back": True},
    ]
    (ws / "applied.json").write_text(json.dumps(applied))
    validation = {
        "fixed_ids": ["a1"],
        "still_present": ["b2"],
        "newly_introduced": [
            {"id": "z9", "severity": "HIGH", "type": "COMMAND_INJECTION",
             "file": "shell.py", "line": 5},
        ],
    }
    (ws / "validation.json").write_text(json.dumps(validation))
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
        assert totals["applied"] == 1
        assert totals["rolled_back"] == 1
        assert totals["not_attempted"] == 1
        assert totals["fixed"] == 1
        assert totals["still_present"] == 1
        assert totals["newly_introduced"] == 1
        assert totals["missing_scanners"] == 2

    def test_outcome_classification(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        by_id = {r["id"]: r for r in s["findings"]}
        assert by_id["a1"]["outcome"] == "applied"
        assert by_id["b2"]["outcome"] == "not_attempted"
        assert by_id["c3"]["outcome"] == "rolled_back"

    def test_validation_status_mapped(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        by_id = {r["id"]: r for r in s["findings"]}
        assert by_id["a1"]["validation"] == "fixed"
        assert by_id["b2"]["validation"] == "still_present"
        assert by_id["c3"]["validation"] == "n/a"

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


class TestNextActions:
    def test_newly_introduced_triggers_high_priority(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        first = s["next_actions"][0]
        assert first["priority"] == "high"
        assert "Roll back" in first["label"]

    def test_missing_pip_scanners_triggers_install(self, ws_full: Path) -> None:
        s = build_summary(ws_full)
        labels = [a["label"] for a in s["next_actions"]]
        assert any("install" in lbl.lower() and "semgrep" in lbl.lower() for lbl in labels)

    def test_no_missing_means_no_install_action(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "findings.json").write_text("[]")
        s = build_summary(ws)
        assert not any("install-scanners" in a["command"] for a in s["next_actions"])


class TestMarkdownRendering:
    def test_contains_all_table_headers(self, ws_full: Path) -> None:
        md = render_markdown(build_summary(ws_full))
        for header in ("## Run totals", "## Findings by severity", "## Findings",
                       "## Missing scanners", "## What next?"):
            assert header in md

    def test_markdown_tables_well_formed(self, ws_full: Path) -> None:
        md = render_markdown(build_summary(ws_full))
        # Every markdown table has a header separator line `| --- |`.
        assert md.count("| ---") >= 5  # one per table

    def test_newly_introduced_section_loud(self, ws_full: Path) -> None:
        md = render_markdown(build_summary(ws_full))
        assert "newly-introduced" in md.lower()
        assert "⚠" in md

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
        assert data["totals"]["newly_introduced"] == 1

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
