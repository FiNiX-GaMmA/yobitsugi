"""Unit tests for yobitsugi.core.apply — diff application + rollback."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from yobitsugi.core import apply as apply_mod
from yobitsugi.core.apply import (
    _extract_files,
    _is_cannot_fix,
    apply_diff,
    rollback,
)

SAMPLE_DIFF = """--- a/app.py
+++ b/app.py
@@ -1,3 +1,3 @@
-import os
+import os  # noqa
 def foo():
     pass
"""


class TestIsCannotFix:
    def test_detects_sentinel(self) -> None:
        assert _is_cannot_fix("# CANNOT_FIX: file is binary") == "file is binary"

    def test_detects_with_whitespace(self) -> None:
        assert _is_cannot_fix("  #  CANNOT_FIX:   some reason  ") == "some reason"

    def test_returns_none_for_normal_diff(self) -> None:
        assert _is_cannot_fix(SAMPLE_DIFF) is None

    def test_empty_string(self) -> None:
        assert _is_cannot_fix("") is None


class TestExtractFiles:
    def test_basic_diff(self) -> None:
        assert _extract_files(SAMPLE_DIFF) == ["app.py"]

    def test_multiple_files(self) -> None:
        diff = (
            "--- a/x.py\n+++ b/x.py\n"
            "--- a/y.py\n+++ b/y.py\n"
        )
        assert _extract_files(diff) == ["x.py", "y.py"]

    def test_ignores_dev_null(self) -> None:
        diff = "--- a/x.py\n+++ /dev/null\n"
        assert _extract_files(diff) == []

    def test_deduplicates(self) -> None:
        diff = (
            "--- a/x.py\n+++ b/x.py\n"
            "--- a/x.py\n+++ b/x.py\n"
        )
        assert _extract_files(diff) == ["x.py"]

    def test_handles_plain_plus_paths(self) -> None:
        diff = "+++ src/foo.py\n"
        assert _extract_files(diff) == ["src/foo.py"]

    def test_empty_diff(self) -> None:
        assert _extract_files("") == []


class TestApplyDiffSafety:
    def test_refuses_dirty_tree(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(apply_mod, "_git_is_dirty", lambda root: True)
        rc = apply_diff(SAMPLE_DIFF, tmp_repo, tmp_workspace, auto=True)
        assert rc == 2

    def test_allow_dirty_overrides(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(apply_mod, "_git_is_dirty", lambda root: True)
        # Touch the file so the diff has a backup target.
        (tmp_repo / "app.py").write_text("import os\ndef foo():\n    pass\n")
        monkeypatch.setattr(apply_mod, "_apply_with_patch", lambda r, d: (True, "ok"))
        rc = apply_diff(
            SAMPLE_DIFF, tmp_repo, tmp_workspace, auto=True, allow_dirty=True
        )
        assert rc == 0

    def test_cannot_fix_returns_zero(self, tmp_repo: Path, tmp_workspace: Path) -> None:
        rc = apply_diff("# CANNOT_FIX: too complex", tmp_repo, tmp_workspace, auto=True)
        assert rc == 0

    def test_no_files_in_diff_errors(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(apply_mod, "_git_is_dirty", lambda root: False)
        rc = apply_diff("garbage\nno file markers\n", tmp_repo, tmp_workspace, auto=True)
        assert rc == 2

    def test_skipped_on_no_confirmation(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_repo / "app.py").write_text("import os\ndef foo():\n    pass\n")
        monkeypatch.setattr(apply_mod, "_git_is_dirty", lambda root: False)
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        rc = apply_diff(SAMPLE_DIFF, tmp_repo, tmp_workspace, auto=False)
        assert rc == 0
        # No backup should have been written.
        assert not list(tmp_repo.glob("*.yobitsugi.bak"))


class TestApplyDiffHappyPath:
    def test_writes_backup_and_log(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_repo / "app.py"
        target.write_text("import os\ndef foo():\n    pass\n")
        monkeypatch.setattr(apply_mod, "_git_is_dirty", lambda root: False)
        monkeypatch.setattr(apply_mod, "_apply_with_patch", lambda r, d: (True, "applied"))

        rc = apply_diff(
            SAMPLE_DIFF, tmp_repo, tmp_workspace,
            finding_id="abc123", auto=True, allow_dirty=True,
        )
        assert rc == 0

        # Backup file created.
        backup = target.with_suffix(target.suffix + ".yobitsugi.bak")
        assert backup.exists()
        assert backup.read_text() == "import os\ndef foo():\n    pass\n"

        # applied.json log written.
        log_path = tmp_workspace / "applied.json"
        log = json.loads(log_path.read_text())
        assert len(log) == 1
        assert log[0]["finding_id"] == "abc123"
        assert log[0]["files"] == ["app.py"]

    def test_patch_failure_returns_one(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_repo / "app.py").write_text("import os\n")
        monkeypatch.setattr(apply_mod, "_git_is_dirty", lambda root: False)
        monkeypatch.setattr(apply_mod, "_apply_with_patch", lambda r, d: (False, "hunk failed"))

        rc = apply_diff(SAMPLE_DIFF, tmp_repo, tmp_workspace, auto=True, allow_dirty=True)
        assert rc == 1


class TestRollback:
    def test_restores_backups(self, tmp_repo: Path, tmp_workspace: Path) -> None:
        target = tmp_repo / "app.py"
        target.write_text("MODIFIED\n")
        bak = target.with_suffix(".py.yobitsugi.bak")
        bak.write_text("ORIGINAL\n")

        log = [{
            "finding_id": "x",
            "files": ["app.py"],
            "backups": [{"path": "app.py", "backup": "app.py.yobitsugi.bak"}],
            "info": "applied",
        }]
        (tmp_workspace / "applied.json").write_text(json.dumps(log))

        rc = rollback(tmp_workspace, tmp_repo)
        assert rc == 0
        assert target.read_text() == "ORIGINAL\n"

        # Log should be marked rolled-back, not deleted.
        new_log = json.loads((tmp_workspace / "applied.json").read_text())
        assert new_log[0].get("rolled_back") is True

    def test_no_log_returns_zero(self, tmp_repo: Path, tmp_workspace: Path) -> None:
        rc = rollback(tmp_workspace, tmp_repo)
        assert rc == 0


class TestApplyMainCli:
    def test_rollback_via_main(self, tmp_repo: Path, tmp_workspace: Path) -> None:
        rc = apply_mod.main([
            "--rollback",
            "--workspace", str(tmp_workspace),
            "--root", str(tmp_repo),
        ])
        assert rc == 0

    def test_main_reads_diff_from_file(
        self, tmp_repo: Path, tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_repo / "app.py").write_text("import os\ndef foo():\n    pass\n")
        diff_file = tmp_workspace / "fix.diff"
        diff_file.write_text(SAMPLE_DIFF)
        monkeypatch.setattr(apply_mod, "_git_is_dirty", lambda root: False)
        monkeypatch.setattr(apply_mod, "_apply_with_patch", lambda r, d: (True, "applied"))

        rc = apply_mod.main([
            "--root", str(tmp_repo),
            "--workspace", str(tmp_workspace),
            "--diff-file", str(diff_file),
            "--auto", "--allow-dirty",
        ])
        assert rc == 0
