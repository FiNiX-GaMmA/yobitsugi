"""Unit tests for yobitsugi.core.detect — language detection."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yobitsugi.core import detect


class TestDetectFunction:
    def test_empty_directory(self, tmp_path: Path) -> None:
        counts, skipped = detect.detect(tmp_path)
        assert counts == {}
        assert skipped == []

    def test_single_language(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("print('hi')")
        (tmp_path / "b.py").write_text("x = 1")
        counts, _ = detect.detect(tmp_path)
        assert counts == {"Python": 2}

    def test_mixed_languages(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.js").write_text("")
        (tmp_path / "c.ts").write_text("")
        (tmp_path / "d.go").write_text("")
        (tmp_path / "e.rs").write_text("")
        counts, _ = detect.detect(tmp_path)
        assert counts["Python"] == 1
        assert counts["JavaScript"] == 1
        assert counts["TypeScript"] == 1
        assert counts["Go"] == 1
        assert counts["Rust"] == 1

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.js").write_text("")
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "ignored.js").write_text("")
        counts, _ = detect.detect(tmp_path)
        assert counts["JavaScript"] == 1

    @pytest.mark.parametrize("skip_dir", [".git", "__pycache__", "venv", ".venv", "dist", "build"])
    def test_skips_well_known_dirs(self, tmp_path: Path, skip_dir: str) -> None:
        (tmp_path / "a.py").write_text("")
        skip = tmp_path / skip_dir
        skip.mkdir()
        (skip / "ignored.py").write_text("")
        counts, _ = detect.detect(tmp_path)
        assert counts["Python"] == 1

    def test_filename_based_detection(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:3.12")
        (tmp_path / "Makefile").write_text("all:")
        (tmp_path / "go.mod").write_text("module x")
        counts, _ = detect.detect(tmp_path)
        assert "Docker" in counts
        assert "Make" in counts
        assert "Go" in counts

    def test_large_file_skipped(self, tmp_path: Path) -> None:
        big = tmp_path / "big.py"
        big.write_bytes(b"#" * (5_000_001))
        counts, skipped = detect.detect(tmp_path)
        assert counts.get("Python", 0) == 0
        assert any("big.py" in s for s in skipped)

    def test_symlinks_ignored(self, tmp_path: Path) -> None:
        real = tmp_path / "real.py"
        real.write_text("")
        link = tmp_path / "link.py"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")
        counts, _ = detect.detect(tmp_path)
        # Only the real file should be counted.
        assert counts.get("Python") == 1

    def test_unknown_extension_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "data.xyz").write_text("")
        counts, _ = detect.detect(tmp_path)
        assert counts == {}


class TestDetectMain:
    def test_writes_languages_json(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "a.py").write_text("")
        out = tmp_path / "ws"
        out.mkdir()

        rc = detect.main(["--root", str(repo), "--out", str(out)])

        assert rc == 0
        data = json.loads((out / "languages.json").read_text())
        assert data["languages"]["Python"] == 1

    def test_nonexistent_root_returns_error(self, tmp_path: Path) -> None:
        out = tmp_path / "ws"
        out.mkdir()
        rc = detect.main(["--root", str(tmp_path / "nope"), "--out", str(out)])
        assert rc != 0
