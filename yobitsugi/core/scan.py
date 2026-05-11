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
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML is required: pip install pyyaml\n")
    sys.exit(2)

from yobitsugi.core import tools

# Default scanner concurrency. Each scanner spends almost all its wall time in
# a subprocess (the scanner binary itself), so threads are the right shape —
# no GIL contention. Capped at 6 by default to avoid hammering CI runners that
# only have 2 vCPUs. Override with the YOBITSUGI_SCAN_CONCURRENCY env var or
# the --concurrency CLI flag.
DEFAULT_MAX_WORKERS = 6

PKG_ROOT = Path(__file__).resolve().parent.parent
SCANNERS_YAML = PKG_ROOT / "data" / "scanners.yaml"


def load_registry() -> dict:
    if not SCANNERS_YAML.exists():
        sys.stderr.write(f"[scan] missing scanner registry at {SCANNERS_YAML}\n")
        sys.exit(2)
    with SCANNERS_YAML.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def have_tool(binary: str, env: dict[str, str] | None = None) -> bool:
    """`which`-equivalent that respects an overridden PATH (so we see venv tools)."""
    path = (env or os.environ).get("PATH")
    return shutil.which(binary, path=path) is not None


def run_one(
    scanner: dict, root: Path, raw_dir: Path, env: dict[str, str] | None = None,
) -> dict:
    """Run a single scanner. Return a small report dict capturing exit/where output went."""
    name = scanner["name"]
    binary = scanner["binary"]
    cmd_template = scanner["command"]
    out_kind = scanner.get("output", "json")
    out_file = raw_dir / f"{name}.{out_kind if out_kind != 'inline_stdout' else 'txt'}"

    if not have_tool(binary, env):
        report = {"name": name, "status": "skipped_missing_tool", "binary": binary}
        install = scanner.get("install") or {}
        if install:
            report["install_method"] = install.get("method", "manual")
            if install.get("package"):
                report["install_package"] = install["package"]
            if install.get("hint"):
                report["install_hint"] = install["hint"]
        return report

    cmd = cmd_template.format(root=str(root), out=str(out_file))
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=scanner.get("timeout", 600),
            cwd=str(root),
            env=env,
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


def _resolve_max_workers(cli_value: int | None) -> int:
    """CLI flag > env var > DEFAULT_MAX_WORKERS. Always at least 1."""
    if cli_value is not None:
        return max(1, cli_value)
    env_value = os.environ.get("YOBITSUGI_SCAN_CONCURRENCY")
    if env_value:
        try:
            return max(1, int(env_value))
        except ValueError:
            sys.stderr.write(
                f"[scan] ignoring invalid YOBITSUGI_SCAN_CONCURRENCY={env_value!r}\n"
            )
    return DEFAULT_MAX_WORKERS


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument(
        "--only",
        nargs="*",
        help="Restrict to specific scanner names (e.g. --only bandit semgrep).",
    )
    p.add_argument(
        "--concurrency", type=int, default=None,
        help=(
            "Max scanners to run in parallel. Default 6 (overridable via "
            "YOBITSUGI_SCAN_CONCURRENCY). Each scanner is a subprocess, so "
            "threads scale fine — the real cap is disk/CPU on the host."
        ),
    )
    p.add_argument(
        "--sequential", action="store_true",
        help="Force scanners to run one at a time. Useful for debugging.",
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

    # Prepend the yobitsugi-managed venv (if it exists) to PATH so scanners
    # installed via `yobitsugi install-scanners` are visible to subprocesses.
    env = tools.prepend_to_path()

    # Point the eslint command in scanners.yaml at our bundled fallback config
    # and at the node_modules root we installed plugins into. These env vars
    # are no-ops when the user's repo has its own .eslintrc.* — the shell
    # branch in the scanner command short-circuits to the user config in that
    # case.
    pkg_root = Path(__file__).resolve().parent.parent
    fallback_cfg = pkg_root / "data" / "eslint-security.eslintrc.json"
    if fallback_cfg.is_file():
        env["YOBITSUGI_ESLINT_FALLBACK_CONFIG"] = str(fallback_cfg)
    node_root = tools.TOOLS_DIR / "node"
    if (node_root / "node_modules").is_dir():
        env["YOBITSUGI_NODE_MODULES_ROOT"] = str(node_root)

    max_workers = 1 if args.sequential else _resolve_max_workers(args.concurrency)
    max_workers = min(max_workers, len(to_run))

    print(f"[scan] running {len(to_run)} scanners against {args.root}")
    if tools.venv_exists():
        print(f"[scan] managed venv: {tools.VENV_DIR}")
    if max_workers > 1:
        print(f"[scan] concurrency: {max_workers} parallel workers")

    # Preserve registry order in the final report, even though scanners
    # finish out of order. We index each scanner first, then fill in the
    # report at the same index as completions arrive.
    reports: list[dict] = [None] * len(to_run)  # type: ignore[list-item]
    name_w = max(len(s["name"]) for s in to_run)
    started_at = time.monotonic()

    if max_workers == 1:
        # Sequential path — kept for `--sequential` and the one-scanner case.
        # Identical output to the old behaviour for easy diffing.
        for i, s in enumerate(to_run):
            print(f"  - {s['name']:<{name_w}}", end=" ", flush=True)
            rep = run_one(s, args.root, raw_dir, env=env)
            print(rep["status"])
            reports[i] = rep
    else:
        # Parallel path. Each scanner runs in its own thread; threads are fine
        # because every scanner spends its wall time in subprocess.run waiting
        # on a child process — no Python-level work, no GIL contention.
        in_flight: dict = {}  # future → (index, scanner_dict, dispatch_time)
        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="yobi-scan"
        ) as pool:
            for i, s in enumerate(to_run):
                fut = pool.submit(run_one, s, args.root, raw_dir, env=env)
                in_flight[fut] = (i, s, time.monotonic())
                print(f"  → {s['name']:<{name_w}}  dispatched")

            for fut in as_completed(in_flight):
                i, s, t0 = in_flight[fut]
                elapsed = time.monotonic() - t0
                try:
                    rep = fut.result()
                except Exception as e:
                    # run_one already catches its own subprocess errors, so an
                    # exception here is genuinely unexpected. Don't let one bad
                    # scanner crash the whole scan.
                    rep = {"name": s["name"], "status": "error", "error": str(e)}
                print(
                    f"  ✓ {s['name']:<{name_w}}  {rep['status']:<22}  "
                    f"{elapsed:>5.1f}s"
                )
                reports[i] = rep

    total_elapsed = time.monotonic() - started_at
    print(f"[scan] all scanners done in {total_elapsed:.1f}s")

    summary = {
        "root": str(args.root.resolve()),
        "languages": languages,
        "scanners": reports,
    }
    (args.workspace / "scan_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"[scan] wrote {args.workspace / 'scan_report.json'}")

    # ---- Summarise missing tools so the assistant / user can act on it ----
    missing = [r for r in reports if r["status"] == "skipped_missing_tool"]
    if missing:
        auto_installable = [r for r in missing if r.get("install_method") == "pip"]
        manual = [r for r in missing if r.get("install_method") != "pip"]

        print(f"\n[scan] {len(missing)} scanner(s) skipped — binary not found:")
        for r in missing:
            method = r.get("install_method", "manual")
            print(f"  - {r['name']:<14}  install method: {method}")

        if auto_installable:
            names = ", ".join(r["name"] for r in auto_installable)
            print(
                f"\n[scan] {len(auto_installable)} of these are auto-installable into "
                f"yobitsugi's isolated venv:"
            )
            print(f"       {names}")
            print("       Run:  yobitsugi install-scanners")
        if manual:
            print(f"\n[scan] {len(manual)} need a runtime yobitsugi can't manage:")
            for r in manual:
                hint = r.get("install_hint") or f"see install method: {r.get('install_method')}"
                print(f"       - {r['name']:<14}  {hint}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
