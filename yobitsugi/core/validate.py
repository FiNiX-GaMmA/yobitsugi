#!/usr/bin/env python3
"""
validate.py — Re-run scanners after fixes and diff the new findings against the old
ones by Finding.id. Tells you which findings were actually resolved, which weren't,
and whether the fixes introduced any new findings.

Usage:
    python validate.py --workspace workspace/ --root /repo
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    args = p.parse_args(argv)

    findings_path = args.workspace / "findings.json"
    if not findings_path.exists():
        sys.stderr.write(f"[validate] missing {findings_path}\n")
        return 1

    before = {f["id"]: f for f in json.loads(findings_path.read_text())}

    # Re-scan into a fresh subdirectory so we don't clobber the original raw outputs.
    rescan_ws = args.workspace / "rescan"
    rescan_ws.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.workspace / "languages.json", rescan_ws / "languages.json")

    print("[validate] re-running scanners...")
    rc = subprocess.run(
        [sys.executable, "-m", "yobitsugi.core.scan",
         "--workspace", str(rescan_ws), "--root", str(args.root)],
    ).returncode
    if rc != 0:
        sys.stderr.write("[validate] re-scan failed\n")
        return rc

    rc = subprocess.run(
        [sys.executable, "-m", "yobitsugi.core.parse",
         "--workspace", str(rescan_ws)],
    ).returncode
    if rc != 0:
        sys.stderr.write("[validate] re-parse failed\n")
        return rc

    after = {f["id"]: f for f in json.loads(
        (rescan_ws / "findings.json").read_text())}

    fixed_ids = set(before) - set(after)
    still_present_ids = set(before) & set(after)
    newly_introduced_ids = set(after) - set(before)

    summary = {
        "before_count": len(before),
        "after_count": len(after),
        "fixed_count": len(fixed_ids),
        "still_present_count": len(still_present_ids),
        "newly_introduced_count": len(newly_introduced_ids),
        "fixed": [before[i] for i in fixed_ids],
        "still_present": [after[i] for i in still_present_ids],
        "newly_introduced": [after[i] for i in newly_introduced_ids],
    }
    (args.workspace / "validation.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(f"[validate] before:           {summary['before_count']:>4}")
    print(f"[validate] fixed:            {summary['fixed_count']:>4}")
    print(f"[validate] still present:    {summary['still_present_count']:>4}")
    print(f"[validate] newly introduced: {summary['newly_introduced_count']:>4}")
    print(f"[validate] wrote {args.workspace / 'validation.json'}")

    # Useful exit code so CI can gate on it.
    return 0 if not summary["newly_introduced_count"] else 3


if __name__ == "__main__":
    sys.exit(main())
