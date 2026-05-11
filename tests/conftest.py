"""Shared pytest fixtures for the yobitsugi test suite."""
from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A temporary git repo with one committed file. Returns the repo root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# tmp repo\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """An empty workspace directory."""
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def sample_finding() -> dict:
    """A canonical SQL-injection finding shaped per the unified Finding schema."""
    return {
        "id": "abc1234567890def",
        "tool": "bandit",
        "language": "Python",
        "file": "app.py",
        "line": 10,
        "end_line": 10,
        "rule_id": "B608",
        "type": "SQL_INJECTION",
        "severity": "HIGH",
        "confidence": "HIGH",
        "title": "hardcoded_sql_expressions",
        "description": "Possible SQL injection via string-based query construction.",
        "code_snippet": "query = f\"SELECT * FROM users WHERE id = {user_id}\"",
        "cwe": ["CWE-89"],
        "references": [],
        "remediation_hint": None,
        "package": None,
        "fixed_version": None,
    }


@pytest.fixture
def findings_with_severities(sample_finding: dict) -> list[dict]:
    """A list of findings across all severity tiers."""
    out = []
    for i, sev in enumerate(["CRITICAL", "HIGH", "MEDIUM", "LOW"]):
        f = dict(sample_finding)
        f["id"] = f"id_{i}"
        f["severity"] = sev
        f["line"] = 10 + i
        out.append(f)
    return out


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox the user's HOME so config writes don't escape the test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip LLM-related env vars so tests don't pick up the developer's keys."""
    for var in (
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
        "VULN_FIXER_PROVIDER", "VULN_FIXER_MODEL", "VULN_FIXER_BASE_URL",
        "OPENAI_COMPATIBLE_API_KEY", "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def write_raw(workspace: Path, name: str, content: str | dict) -> Path:
    """Helper: write a scanner raw output to workspace/raw/<name>."""
    raw = workspace / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    target = raw / name
    if isinstance(content, (dict, list)):
        target.write_text(json.dumps(content))
    else:
        target.write_text(content)
    return target
