"""End-to-end orchestrator: detect → scan → parse → fix → apply → tests → validate.

All steps run in-process. Each core module also has its own CLI entry point if you
want to run a single step on its own.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from yobitsugi.core import apply as apply_mod
from yobitsugi.core import detect, fix, parse, scan, tests_gen, validate


def _step(label: str) -> None:
    print(f"\n=== {label} ===")


def run_pipeline(
    root: Path,
    workspace: Path | None = None,
    severity: list[str] | None = None,
    auto: bool = False,
    allow_dirty: bool = False,
    provider: str | None = None,
    model: str | None = None,
    skip_tests: bool = False,
) -> int:
    if not root.is_dir():
        sys.stderr.write(f"--root {root} is not a directory\n")
        return 1

    severity = severity or ["CRITICAL", "HIGH"]
    workspace = workspace or (
        Path.home() / ".yobitsugi"
        / f"{root.name}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"[run] workspace: {workspace}")

    _step("detect")
    rc = detect.main(["--root", str(root), "--out", str(workspace)])
    if rc != 0:
        return rc

    _step("scan")
    rc = scan.main(["--workspace", str(workspace), "--root", str(root)])
    if rc != 0:
        return rc

    _step("parse")
    rc = parse.main(["--workspace", str(workspace)])
    if rc != 0:
        return rc

    findings = json.loads((workspace / "findings.json").read_text())
    targets = [f for f in findings if f["severity"] in severity]
    print(f"\n[run] {len(findings)} findings total; "
          f"{len(targets)} match severity filter {severity}")

    if not targets:
        print("[run] nothing to fix.")
        return 0

    for i, f in enumerate(targets, 1):
        print(f"\n--- Finding {i}/{len(targets)}: {f['type']} "
              f"({f['severity']}) in {f.get('file')}:{f.get('line')} ---")
        try:
            diff = fix.generate_fix(f, root, provider=provider, model=model)
        except Exception as e:
            print(f"[run] could not generate fix: {e}")
            continue
        if not diff.strip():
            print("[run] empty diff from LLM, skipping")
            continue
        apply_mod.apply_diff(
            diff, root, workspace,
            finding_id=f.get("id"), auto=auto, allow_dirty=allow_dirty,
        )

    if not skip_tests:
        _step("tests")
        tests_gen.main(["--workspace", str(workspace), "--root", str(root)])

    _step("validate")
    validate.main(["--workspace", str(workspace), "--root", str(root)])

    # Final detailed report (tables: findings × fixes × validation × next actions).
    from yobitsugi.core import summary as summary_mod
    summary_mod.render(workspace, mode="rich")

    print(f"\n[run] done. See {workspace}/ for everything.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--workspace", type=Path,
                   help="Defaults to ~/.yobitsugi/<repo>-<timestamp>.")
    p.add_argument("--severity", nargs="*", default=["CRITICAL", "HIGH"],
                   help="Severities to attempt to fix. Default: CRITICAL HIGH.")
    p.add_argument("--auto", action="store_true",
                   help="Apply fixes without confirmation. Use cautiously.")
    p.add_argument("--allow-dirty", action="store_true")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--skip-tests", action="store_true")
    args = p.parse_args(argv)

    return run_pipeline(
        root=args.root,
        workspace=args.workspace,
        severity=args.severity,
        auto=args.auto,
        allow_dirty=args.allow_dirty,
        provider=args.provider,
        model=args.model,
        skip_tests=args.skip_tests,
    )


if __name__ == "__main__":
    sys.exit(main())
