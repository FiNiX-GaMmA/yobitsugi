"""Unit tests for yobitsugi.core.parse — scanner output normalisation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yobitsugi.core import parse
from yobitsugi.core.parse import (
    PARSERS,
    classify_type,
    finding,
    make_id,
    normalize_severity,
)


class TestNormalizeSeverity:
    @pytest.mark.parametrize("raw,expected", [
        ("critical", "CRITICAL"),
        ("CRITICAL", "CRITICAL"),
        ("Crit", "CRITICAL"),
        ("high", "HIGH"),
        ("error", "HIGH"),
        ("medium", "MEDIUM"),
        ("moderate", "MEDIUM"),
        ("warning", "MEDIUM"),
        ("low", "LOW"),
        ("info", "LOW"),
        ("note", "LOW"),
        ("", "UNKNOWN"),
        ("garbage", "GARBAGE"),
    ])
    def test_known_values(self, raw: str, expected: str) -> None:
        assert normalize_severity(raw) == expected

    def test_none_returns_unknown(self) -> None:
        assert normalize_severity(None) == "UNKNOWN"

    def test_whitespace_stripped(self) -> None:
        assert normalize_severity("  high  ") == "HIGH"


class TestClassifyType:
    @pytest.mark.parametrize("text,expected", [
        ("sql injection vulnerability", "SQL_INJECTION"),
        ("Possible XSS in template", "XSS"),
        ("cross-site scripting", "XSS"),
        ("hardcoded password detected", "HARDCODED_SECRET"),
        ("api_key found", "HARDCODED_SECRET"),
        ("Use of weak crypto md5", "WEAK_CRYPTO"),
        ("SHA1 is broken", "WEAK_CRYPTO"),
        ("pickle.loads is unsafe", "INSECURE_DESERIALIZATION"),
        ("SSRF in url fetch", "SSRF"),
        ("open redirect", "OPEN_REDIRECT"),
        ("path traversal", "PATH_TRAVERSAL"),
        ("shell command injection", "COMMAND_INJECTION"),
        ("totally benign", "OTHER"),
        ("", "OTHER"),
    ])
    def test_classification(self, text: str, expected: str) -> None:
        assert classify_type(text) == expected


class TestMakeId:
    def test_deterministic(self) -> None:
        a = make_id("bandit", "app.py", 10, "B608")
        b = make_id("bandit", "app.py", 10, "B608")
        assert a == b

    def test_length_is_16(self) -> None:
        assert len(make_id("a", "b", 1, "c")) == 16

    def test_differs_per_input(self) -> None:
        ids = {
            make_id("bandit", "app.py", 10, "B608"),
            make_id("bandit", "app.py", 11, "B608"),
            make_id("bandit", "other.py", 10, "B608"),
            make_id("semgrep", "app.py", 10, "B608"),
        }
        assert len(ids) == 4

    def test_hex_only(self) -> None:
        result = make_id("a", "b", 1, "c")
        assert all(c in "0123456789abcdef" for c in result)


class TestFindingConstructor:
    def test_required_fields_present(self) -> None:
        f = finding("bandit", file="x.py", line=1)
        required = {
            "id", "tool", "language", "file", "line", "end_line", "rule_id",
            "type", "severity", "confidence", "title", "description", "code_snippet",
            "cwe", "references", "remediation_hint", "package", "fixed_version",
        }
        assert required.issubset(f.keys())

    def test_classifies_from_description(self) -> None:
        f = finding("bandit", description="SQL injection via concatenation")
        assert f["type"] == "SQL_INJECTION"

    def test_type_override_wins(self) -> None:
        f = finding("safety", description="some sql thing", type_override="VULNERABLE_DEPENDENCY")
        assert f["type"] == "VULNERABLE_DEPENDENCY"

    def test_package_without_file_becomes_dependency(self) -> None:
        f = finding("safety", package="requests", file=None)
        assert f["type"] == "VULNERABLE_DEPENDENCY"

    def test_confidence_uppercased(self) -> None:
        f = finding("bandit", confidence="high")
        assert f["confidence"] == "HIGH"

    def test_empty_lists_default(self) -> None:
        f = finding("bandit")
        assert f["cwe"] == []
        assert f["references"] == []


class TestBanditParser:
    def test_basic_finding(self) -> None:
        raw = json.dumps({
            "results": [{
                "filename": "app.py",
                "line_number": 10,
                "line_range": [10],
                "test_id": "B608",
                "test_name": "hardcoded_sql_expressions",
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "issue_text": "Possible SQL injection",
                "code": "query = f\"...\"",
                "issue_cwe": {"id": 89},
                "more_info": "https://bandit.readthedocs.io/B608",
            }]
        })
        out = PARSERS["bandit"](raw, Path("."))
        assert len(out) == 1
        f = out[0]
        assert f["tool"] == "bandit"
        assert f["severity"] == "HIGH"
        assert f["type"] == "SQL_INJECTION"
        assert f["cwe"] == ["CWE-89"]
        assert f["references"] == ["https://bandit.readthedocs.io/B608"]

    def test_empty_results(self) -> None:
        out = PARSERS["bandit"](json.dumps({"results": []}), Path("."))
        assert out == []


class TestSemgrepParser:
    def test_basic_finding(self) -> None:
        raw = json.dumps({
            "results": [{
                "check_id": "python.lang.security.injection.sql-injection",
                "path": "src/app.py",
                "start": {"line": 42},
                "end": {"line": 42},
                "extra": {
                    "severity": "ERROR",
                    "message": "SQL injection",
                    "metadata": {"technology": ["python"]},
                },
            }]
        })
        out = PARSERS["semgrep"](raw, Path("."))
        assert len(out) == 1
        f = out[0]
        assert f["file"] == "src/app.py"
        assert f["line"] == 42
        assert f["severity"] == "HIGH"  # ERROR → HIGH


class TestSafetyParser:
    def test_list_format(self) -> None:
        raw = json.dumps([{
            "package_name": "requests",
            "vulnerability_id": "CVE-2023-1234",
            "advisory": "RCE",
            "fixed_versions": ["2.31.0"],
        }])
        out = PARSERS["safety"](raw, Path("."))
        assert len(out) == 1
        assert out[0]["type"] == "VULNERABLE_DEPENDENCY"
        assert out[0]["package"] == "requests"
        assert out[0]["fixed_version"] == "2.31.0"

    def test_dict_format(self) -> None:
        raw = json.dumps({"vulnerabilities": [{
            "package": "django", "cve": "CVE-2024-0001", "advisory": "XSS",
        }]})
        out = PARSERS["safety"](raw, Path("."))
        assert len(out) == 1
        assert out[0]["package"] == "django"


class TestParseMain:
    def test_writes_findings_json(self, tmp_workspace: Path) -> None:
        raw_dir = tmp_workspace / "raw"
        raw_dir.mkdir()
        (raw_dir / "bandit.json").write_text(json.dumps({
            "results": [{
                "filename": "a.py", "line_number": 1, "test_id": "B608",
                "issue_severity": "HIGH", "test_name": "sqli",
                "issue_text": "SQL injection",
            }]
        }))
        rc = parse.main(["--workspace", str(tmp_workspace)])
        assert rc == 0
        findings = json.loads((tmp_workspace / "findings.json").read_text())
        assert len(findings) == 1
        assert findings[0]["tool"] == "bandit"

    def test_missing_raw_dir_errors(self, tmp_workspace: Path) -> None:
        rc = parse.main(["--workspace", str(tmp_workspace)])
        assert rc == 1

    def test_unknown_scanner_skipped(self, tmp_workspace: Path) -> None:
        raw_dir = tmp_workspace / "raw"
        raw_dir.mkdir()
        (raw_dir / "unknown-tool.json").write_text("{}")
        rc = parse.main(["--workspace", str(tmp_workspace)])
        assert rc == 0
        findings = json.loads((tmp_workspace / "findings.json").read_text())
        assert findings == []

    def test_deduplication(self, tmp_workspace: Path) -> None:
        raw_dir = tmp_workspace / "raw"
        raw_dir.mkdir()
        dup_finding = {
            "results": [
                {"filename": "a.py", "line_number": 1, "test_id": "B608",
                 "issue_severity": "HIGH", "test_name": "x", "issue_text": "x"},
                {"filename": "a.py", "line_number": 1, "test_id": "B608",
                 "issue_severity": "HIGH", "test_name": "x", "issue_text": "x"},
            ]
        }
        (raw_dir / "bandit.json").write_text(json.dumps(dup_finding))
        rc = parse.main(["--workspace", str(tmp_workspace)])
        assert rc == 0
        findings = json.loads((tmp_workspace / "findings.json").read_text())
        assert len(findings) == 1

    def test_empty_raw_file_skipped(self, tmp_workspace: Path) -> None:
        raw_dir = tmp_workspace / "raw"
        raw_dir.mkdir()
        (raw_dir / "bandit.json").write_text("")
        rc = parse.main(["--workspace", str(tmp_workspace)])
        assert rc == 0
        assert json.loads((tmp_workspace / "findings.json").read_text()) == []

    def test_malformed_input_is_caught(self, tmp_workspace: Path) -> None:
        raw_dir = tmp_workspace / "raw"
        raw_dir.mkdir()
        (raw_dir / "bandit.json").write_text("not json {{{")
        rc = parse.main(["--workspace", str(tmp_workspace)])
        # The parser logs and continues — exit code stays 0, findings empty.
        assert rc == 0
        assert json.loads((tmp_workspace / "findings.json").read_text()) == []
