#!/usr/bin/env python3
"""
apply_fix.py — Apply a unified diff to a codebase, with backups and a rollback log.

Safety rails:
  • Refuses to run on a dirty git working tree unless --allow-dirty.
  • Writes a .yobitsugi.bak alongside every patched file.
  • Records every applied diff to workspace/applied.json so rollback is one command.
  • Always shows the diff and prompts unless --auto is passed.

Usage:
    cat fix.diff | python apply_fix.py --root /repo --workspace workspace/ --finding-id abc
    python apply_fix.py --rollback --workspace workspace/         # undo everything
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _git_is_dirty(root: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        )
        return bool(r.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Not a git repo or git not installed → caller's risk; warn but continue.
        return False


def _is_cannot_fix(diff_text: str) -> str | None:
    m = re.match(r"^\s*#\s*CANNOT_FIX:\s*(.+)$", diff_text.strip())
    return m.group(1).strip() if m else None


def _extract_files(diff_text: str) -> list[str]:
    """Pull file paths out of `+++ b/<path>` lines so we can back them up."""
    paths = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            paths.append(line[len("+++ b/"):].strip())
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            paths.append(line[len("+++ "):].strip())
    # Deduplicate, preserve order.
    seen = set()
    uniq = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _backup(root: Path, files: list[str], applied_log: Path) -> list[dict]:
    records = []
    for rel in files:
        target = root / rel
        if not target.is_file():
            continue
        bak = target.with_suffix(target.suffix + ".yobitsugi.bak")
        if not bak.exists():
            shutil.copy2(target, bak)
        records.append({"path": rel, "backup": str(bak.relative_to(root))})
    return records


def _apply_with_patch(root: Path, diff_text: str) -> tuple[bool, str]:
    """Apply with the `patch` binary if available; fall back to `git apply`."""
    for cmd in (["patch", "-p1", "--forward", "--silent"],
                ["git", "apply", "--whitespace=nowarn"]):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            r = subprocess.run(
                cmd, input=diff_text, text=True, capture_output=True, cwd=str(root),
            )
            if r.returncode == 0:
                return True, f"applied via {cmd[0]}"
            else:
                last_err = (r.stderr or r.stdout)[-2000:]
        except Exception as e:
            last_err = str(e)
    return False, f"patch failed; last error: {last_err[-500:]}"


def _show_diff(diff_text: str) -> None:
    # Light colorization for terminals that handle ANSI.
    GREEN, RED, CYAN, RESET = "\033[32m", "\033[31m", "\033[36m", "\033[0m"
    is_tty = sys.stdout.isatty()
    for line in diff_text.splitlines():
        if not is_tty:
            print(line)
        elif line.startswith("+") and not line.startswith("+++"):
            print(GREEN + line + RESET)
        elif line.startswith("-") and not line.startswith("---"):
            print(RED + line + RESET)
        elif line.startswith("@@"):
            print(CYAN + line + RESET)
        else:
            print(line)


def _load_log(applied_log: Path) -> list[dict]:
    if applied_log.exists():
        return json.loads(applied_log.read_text(encoding="utf-8"))
    return []


def _save_log(applied_log: Path, entries: list[dict]) -> None:
    applied_log.parent.mkdir(parents=True, exist_ok=True)
    applied_log.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def rollback(workspace: Path, root: Path) -> int:
    log_path = workspace / "applied.json"
    entries = _load_log(log_path)
    if not entries:
        print("[apply] nothing to roll back")
        return 0
    restored = 0
    for entry in reversed(entries):
        for b in entry.get("backups", []):
            target = root / b["path"]
            bak = root / b["backup"]
            if bak.is_file():
                shutil.copy2(bak, target)
                restored += 1
    print(f"[apply] restored {restored} files from backups")
    # Mark log as rolled back rather than deleting it — useful for audit.
    for e in entries:
        e["rolled_back"] = True
    _save_log(log_path, entries)
    return 0


def apply_diff(
    diff_text: str,
    root: Path,
    workspace: Path,
    finding_id: str | None = None,
    auto: bool = False,
    allow_dirty: bool = False,
) -> int:
    """Apply a unified diff to `root`, recording backups in `workspace/applied.json`."""
    if _git_is_dirty(root) and not allow_dirty:
        sys.stderr.write(
            "[apply] refusing to operate on a dirty git tree. "
            "Commit/stash first, or pass --allow-dirty.\n"
        )
        return 2

    reason = _is_cannot_fix(diff_text)
    if reason:
        print(f"[apply] LLM declined to fix: {reason}")
        return 0

    files = _extract_files(diff_text)
    if not files:
        sys.stderr.write(
            "[apply] no target files found in diff. "
            "Expected lines like `+++ b/path/to/file`.\n"
        )
        return 2

    print(f"[apply] diff touches {len(files)} file(s):")
    for f in files:
        print(f"  - {f}")
    print()
    _show_diff(diff_text)
    print()

    if not auto:
        try:
            answer = input("Apply this fix? (y/n): ").strip().lower()
        except EOFError:
            answer = "n"
        if answer != "y":
            print("[apply] skipped")
            return 0

    backups = _backup(root, files, workspace / "applied.json")
    ok, info = _apply_with_patch(root, diff_text)
    if not ok:
        sys.stderr.write(f"[apply] {info}\n")
        return 1

    entry = {
        "timestamp": dt.datetime.utcnow().isoformat() + "Z",
        "finding_id": finding_id,
        "files": files,
        "backups": backups,
        "info": info,
    }
    log = _load_log(workspace / "applied.json")
    log.append(entry)
    _save_log(workspace / "applied.json", log)
    print(f"[apply] {info}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--finding-id", help="ID of the finding this diff fixes.")
    p.add_argument("--auto", action="store_true",
                   help="Skip confirmation. Use sparingly.")
    p.add_argument("--allow-dirty", action="store_true",
                   help="Permit running on a dirty git tree.")
    p.add_argument("--rollback", action="store_true",
                   help="Restore all backups recorded in this workspace and exit.")
    p.add_argument("--diff-file", type=Path,
                   help="Read diff from a file instead of stdin.")
    args = p.parse_args(argv)

    if args.rollback:
        return rollback(args.workspace, args.root)

    diff_text = (
        args.diff_file.read_text(encoding="utf-8")
        if args.diff_file else sys.stdin.read()
    )
    return apply_diff(
        diff_text, args.root, args.workspace,
        finding_id=args.finding_id, auto=args.auto, allow_dirty=args.allow_dirty,
    )


if __name__ == "__main__":
    sys.exit(main())
