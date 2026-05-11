#!/usr/bin/env python3
"""
run_scanners.py — For each language detected, run its registered scanners. Skip
scanners that aren't installed (don't error). Write every scanner's raw output
(or its error) to workspace/raw/<scanner>.{json,txt}.

The scanner registry lives in ../references/scanners.yaml so adding a new tool is
a data-only change.

Usage:
    python run_scanners.py --workspace workspace/ --root /path/to/repo
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    sys.stderr.write("PyYAML is required: pip install pyyaml\n")
    sys.exit(2)


PKG_ROOT = Path(__file__).resolve().parent.parent
SCANNERS_YAML = PKG_ROOT / "data" / "scanners.yaml"


def load_registry() -> dict:
    if not SCANNERS_YAML.exists():
        sys.stderr.write(f"[scan] missing scanner registry at {SCANNERS_YAML}\n")
        sys.exit(2)
    with SCANNERS_YAML.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def have_tool(binary: str) -> bool:
    return shutil.which(binary) is not None


def run_one(scanner: dict, root: Path, raw_dir: Path) -> dict:
    """Run a single scanner. Return a small report dict capturing exit/where output went."""
    name = scanner["name"]
    binary = scanner["binary"]
    cmd_template = scanner["command"]
    out_kind = scanner.get("output", "json")
    out_file = raw_dir / f"{name}.{out_kind if out_kind != 'inline_stdout' else 'txt'}"

    if not have_tool(binary):
        return {"name": name, "status": "skipped_missing_tool", "binary": binary}

    cmd = cmd_template.format(root=str(root), out=str(out_file))
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=scanner.get("timeout", 600),
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "timeout"}
    except Exception as e:
        return {"name": name, "status": "error", "error": str(e)}

    # Many scanners exit non-zero when they FIND issues. That's not a real failure.
    # Treat "we got our output file" as success regardless of exit code.
    if out_kind == "inline_stdout":
        out_file.write_text(proc.stdout, encoding="utf-8")

    status = "ok" if out_file.exists() and out_file.stat().st_size > 0 else "no_output"
    return {
        "name": name,
        "status": status,
        "exit_code": proc.returncode,
        "stderr_tail": (proc.stderr or "")[-2000:],
        "output_file": str(out_file) if out_file.exists() else None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument(
        "--only",
        nargs="*",
        help="Restrict to specific scanner names (e.g. --only bandit semgrep).",
    )
    args = p.parse_args(argv)

    languages_file = args.workspace / "languages.json"
    if not languages_file.exists():
        sys.stderr.write(
            f"[scan] {languages_file} not found. Run detect_languages.py first.\n"
        )
        return 1

    with languages_file.open() as f:
        languages = list(json.load(f).get("languages", {}).keys())

    registry = load_registry()
    raw_dir = args.workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Build the set of scanners to run: per-language + cross-language.
    to_run: list[dict] = []
    seen_names: set[str] = set()
    for lang in languages + ["_cross_language"]:
        for scanner in registry.get(lang, []):
            if args.only and scanner["name"] not in args.only:
                continue
            if scanner["name"] in seen_names:
                continue
            seen_names.add(scanner["name"])
            to_run.append(scanner)

    if not to_run:
        print("[scan] no scanners matched detected languages")
        return 0

    print(f"[scan] running {len(to_run)} scanners against {args.root}")
    reports = []
    for s in to_run:
        print(f"  - {s['name']:<14}", end=" ", flush=True)
        rep = run_one(s, args.root, raw_dir)
        print(rep["status"])
        reports.append(rep)

    summary = {
        "root": str(args.root.resolve()),
        "languages": languages,
        "scanners": reports,
    }
    (args.workspace / "scan_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"[scan] wrote {args.workspace / 'scan_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
