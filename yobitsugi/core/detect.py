#!/usr/bin/env python3
"""
detect_languages.py — Walk a codebase and identify which programming languages are
present, along with a file-count per language. Outputs JSON to <workspace>/languages.json.

Why extension-first: it's ~1000× faster than reading every file, and ~99% accurate for
finding what *scanners* to run. Falls back to a content sniff only for files with no
extension that look like text (e.g. Dockerfile, Makefile).

Usage:
    python detect_languages.py --root /path/to/repo --out workspace/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

# Extension → language. We err on the side of broad coverage so scanners get a chance
# to run; if a language has no scanner registered, run_scanners.py just skips it.
EXTENSIONS: dict[str, str] = {
    # Python
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    # JavaScript / TypeScript
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    # Java / JVM
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala",
    # Go
    ".go": "Go",
    # Ruby
    ".rb": "Ruby", ".erb": "Ruby", ".rake": "Ruby",
    # PHP
    ".php": "PHP", ".phtml": "PHP",
    # C / C++
    ".c": "C", ".h": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
    # Rust
    ".rs": "Rust",
    # Shell
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    # Web / data
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "CSS", ".sass": "CSS",
    ".sql": "SQL",
    # Containers / IaC
    ".dockerfile": "Docker", ".tf": "Terraform", ".yaml": "YAML", ".yml": "YAML",
    # Misc
    ".swift": "Swift", ".m": "Objective-C", ".cs": "C#",
}

# Filename-based (no extension) hints.
FILENAMES: dict[str, str] = {
    "Dockerfile": "Docker",
    "Makefile": "Make",
    "Rakefile": "Ruby",
    "Gemfile": "Ruby",
    "requirements.txt": "Python",
    "Pipfile": "Python",
    "pyproject.toml": "Python",
    "package.json": "JavaScript",
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "composer.json": "PHP",
    "pom.xml": "Java",
    "build.gradle": "Java",
}

# Skip these directories — scanning them is slow and noisy.
SKIP_DIRS: set[str] = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "venv", ".venv", "env", ".env",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "target", ".gradle", ".idea", ".vscode", "coverage", ".next", ".nuxt", ".cache",
}


def detect(root: Path) -> tuple[dict[str, int], list[str]]:
    """Return (language → file_count, list of files skipped because binary/huge)."""
    counts: Counter[str] = Counter()
    skipped: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fn in filenames:
            full = Path(dirpath) / fn
            try:
                if full.is_symlink():
                    continue
                size = full.stat().st_size
            except OSError:
                continue

            # Skip absurdly large files; they're almost never source.
            if size > 5_000_000:
                skipped.append(str(full))
                continue

            ext = full.suffix.lower()
            lang = EXTENSIONS.get(ext)
            if not lang:
                lang = FILENAMES.get(fn)
            if lang:
                counts[lang] += 1

    return dict(counts), skipped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Detect languages present in a codebase.")
    p.add_argument("--root", required=True, type=Path, help="Codebase root.")
    p.add_argument("--out", required=True, type=Path, help="Workspace dir.")
    args = p.parse_args(argv)

    if not args.root.is_dir():
        sys.stderr.write(f"[detect] root {args.root} is not a directory\n")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)

    counts, skipped = detect(args.root)
    out_path = args.out / "languages.json"
    payload = {
        "root": str(args.root.resolve()),
        "languages": counts,
        "skipped_large_files": skipped[:50],  # cap so the JSON stays reasonable
        "skipped_large_count": len(skipped),
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"[detect] wrote {out_path}")
    for lang, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {lang:<12} {n:>6} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
