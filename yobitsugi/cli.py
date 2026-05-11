"""yobitsugi CLI entrypoint — the *thin* binary half of a skill-first tool.

yobitsugi is a **skill / plugin** for agentic AI editors (Claude Code, Codex,
Cursor, Gemini CLI, Aider, OpenCode, GitHub Copilot CLI). The skill lives as
markdown installed into each editor's plugin location and contains the whole
orchestration runbook — it tells the host agent how to walk a security audit
end to end. The host agent does the talking, the explaining, and the
generation-and-application of fixes using its own LLM and edit tools.

This CLI only does the things that genuinely need a binary:

  - Run SAST/SCA scanners that ship as system binaries (bandit, semgrep,
    pip-audit, gosec, brakeman, eslint, …) and normalise their output to a
    unified `findings.json`.
  - Render the workspace as tables / JSON the assistant can paste into chat.
  - Install / uninstall the skill files into each supported editor's plugin
    location.
  - Manage the optional isolated scanner venv at `~/.yobitsugi/tools/venv/`
    (or, with `--ephemeral-tools`, a temp-dir variant that's deleted at the
    end of one invocation).

There is **no `yobitsugi run`**, no `apply`, no `rollback`, no LLM provider
config and no fix generation in the CLI any more. Those responsibilities now
live in the host AI assistant — see `data/SKILL.md` for the runbook.

Subcommands:
  yobitsugi scan <path> [--ephemeral-tools] [--out <ws>]
  yobitsugi summary <workspace> [--format rich|markdown|json]
  yobitsugi findings <workspace> [--severity ...] [--type ...] [--json]
  yobitsugi list-scanners
  yobitsugi install-scanners [--all]
  yobitsugi uninstall-scanners
  yobitsugi install [--platform <name>] [--scope user|project]
  yobitsugi uninstall [--platform <name>] [--scope user|project]
  yobitsugi list-platforms
  yobitsugi detect-platforms
  yobitsugi version

Positional shortcut: `yobitsugi <path>` is rewritten to `yobitsugi scan <path>`
so the slash-command pattern (`/yobitsugi .` inside any supported assistant)
hits the read-only scan path by default.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

from yobitsugi import __version__
from yobitsugi.installers import INSTALLERS, get_installer

KNOWN_SUBCOMMANDS = {
    "version", "list-platforms", "detect-platforms", "install", "uninstall",
    "scan", "findings", "summary",
    "install-scanners", "uninstall-scanners", "list-scanners",
    "bootstrap",
}


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"yobitsugi {__version__}")
    return 0


def cmd_list_platforms(_args: argparse.Namespace) -> int:
    print("Supported platforms:")
    for name, cls in sorted(INSTALLERS.items()):
        inst = cls()
        present = "✓ detected" if inst.is_present() else "  not detected"
        print(f"  {name:12s} {inst.display_name:24s} {present}")
    return 0


def cmd_detect_platforms(_args: argparse.Namespace) -> int:
    detected = [n for n, cls in INSTALLERS.items() if cls().is_present()]
    if not detected:
        print("No supported AI assistants detected on this machine.")
        return 1
    print("Detected:")
    for n in detected:
        print(f"  {n}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    if args.platform:
        platforms = [args.platform]
    else:
        platforms = [n for n, cls in INSTALLERS.items() if cls().is_present()]
        if not platforms:
            print("No supported assistants detected. Pass --platform to force install.",
                  file=sys.stderr)
            return 1
        print(f"Detected assistants: {', '.join(platforms)}")

    for name in platforms:
        try:
            installer = get_installer(name)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(installer.install(scope=args.scope))
        print()
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    platforms = [args.platform] if args.platform else list(INSTALLERS)
    for name in platforms:
        try:
            installer = get_installer(name)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(installer.uninstall(scope=args.scope))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan-only: detect → run scanners → parse to findings.json.

    This is the entire CLI surface that a host agent needs. After this returns,
    the workspace contains `languages.json`, `scan_report.json`, `findings.json`,
    and per-scanner raw outputs under `raw/`. The agent reads findings.json,
    walks the user through each finding, and applies fixes itself.
    """
    from yobitsugi.core import detect, parse, scan

    workspace = args.out or (
        Path.home() / ".yobitsugi"
        / f"{args.path.name}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"workspace: {workspace}")

    # Forward parallelism flags to core.scan.main. Sequential beats concurrency
    # when both are passed (sequential is the explicit "I want a deterministic
    # serial run" escape hatch).
    scan_argv = ["--workspace", str(workspace), "--root", str(args.path)]
    if args.sequential:
        scan_argv.append("--sequential")
    elif args.concurrency is not None:
        scan_argv.extend(["--concurrency", str(args.concurrency)])
    if args.only:
        scan_argv.extend(["--only", *args.only])

    def _go() -> int:
        for label, fn, argv in (
            ("detect", detect.main, ["--root", str(args.path), "--out", str(workspace)]),
            ("scan",   scan.main,   scan_argv),
            ("parse",  parse.main,  ["--workspace", str(workspace)]),
        ):
            print(f"\n=== {label} ===")
            rc = fn(argv)
            if rc != 0:
                return rc

        findings_path = workspace / "findings.json"
        if findings_path.exists():
            findings = json.loads(findings_path.read_text())
            by_sev: dict[str, int] = {}
            for f in findings:
                by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
            print(f"\n{len(findings)} findings: " +
                  ", ".join(f"{k}={v}" for k, v in sorted(by_sev.items())))

        from yobitsugi.core import summary as summary_mod
        summary_mod.render(workspace, mode="rich")
        return 0

    return _with_optional_ephemeral_tools(_go, args, root=args.path)


def _with_optional_ephemeral_tools(fn, args: argparse.Namespace, root: Path) -> int:
    """If --ephemeral-tools was passed, run `fn` inside an ephemeral venv that
    holds just the pip-installable scanners we need, then delete it. Otherwise
    run `fn` against the persistent ~/.yobitsugi/tools/venv/ (or the user's PATH)."""
    if not getattr(args, "ephemeral_tools", False):
        return fn()

    from yobitsugi.core import tools

    registry = _load_scanner_registry()
    languages = _quick_detect_languages(root)

    with tools.ephemeral_tools_dir() as tmp:
        print(f"[ephemeral-tools] managed venv: {tmp / 'venv'}")
        print("[ephemeral-tools] installing scanners for detected languages: "
              f"{', '.join(languages) if languages else '(none yet)'}")
        installed, failed = tools.install_missing_pip_scanners(registry, languages=languages)
        if installed:
            print(f"[ephemeral-tools] installed: {', '.join(installed)}")
        if failed:
            print(f"[ephemeral-tools] failed to install: {', '.join(failed)} "
                  "(scan will continue and mark those scanners as skipped)")
        try:
            return fn()
        finally:
            print(f"[ephemeral-tools] tearing down {tmp}")


def _quick_detect_languages(root: Path) -> list[str]:
    """Pre-sniff languages so the ephemeral install only pulls the scanners
    the repo actually needs. Returns [] on any error so the caller falls back
    to installing every pip scanner."""
    try:
        from yobitsugi.core import detect

        counts, _skipped = detect.detect(root)
        return list(counts.keys())
    except Exception:
        return []


def cmd_findings(args: argparse.Namespace) -> int:
    findings_path = args.workspace / "findings.json"
    if not findings_path.exists():
        print(f"no findings.json in {args.workspace}", file=sys.stderr)
        return 1
    findings = json.loads(findings_path.read_text())
    if args.severity:
        findings = [f for f in findings if f["severity"] in args.severity]
    if args.type:
        findings = [f for f in findings if f["type"] in args.type]
    if args.json:
        print(json.dumps(findings, indent=2))
        return 0
    for f in findings:
        loc = f.get("file") or "?"
        if f.get("line"):
            loc += f":{f['line']}"
        print(f"[{f['severity']:8s}] {f['type']:28s} {loc}  ({f.get('tool', '?')})")
        msg = f.get("description") or f.get("title") or ""
        if msg:
            print(f"           {msg[:120]}")
    print(f"\n{len(findings)} findings")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    """Render the workspace's findings/scan_report as tables."""
    from yobitsugi.core import summary as summary_mod

    if not args.workspace.is_dir():
        print(f"[summary] no such workspace: {args.workspace}", file=sys.stderr)
        return 1
    summary_mod.render(args.workspace, mode=args.format)
    return 0


def _load_scanner_registry() -> dict:
    """Load yobitsugi/data/scanners.yaml without making `yaml` a hard CLI dep."""
    import yaml  # type: ignore

    pkg_root = Path(__file__).resolve().parent
    with (pkg_root / "data" / "scanners.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cmd_list_scanners(_args: argparse.Namespace) -> int:
    """Print every known scanner, its install method, and whether the binary is on PATH."""
    import shutil as _shutil

    from yobitsugi.core import tools

    registry = _load_scanner_registry()
    plans = tools.build_install_plans(registry)
    venv_bin = tools.tools_bin_path() if tools.venv_exists() else None

    print(f"{'scanner':<14}  {'method':<8}  {'installed':<11}  {'package / hint'}")
    print("-" * 90)
    for plan in plans:
        on_path = _shutil.which(plan.name) is not None
        in_venv = venv_bin is not None and (venv_bin / plan.name).exists()
        installed = "yes" if (on_path or in_venv) else "no"
        if in_venv and not on_path:
            installed += " (venv)"
        detail = plan.package or plan.hint or "—"
        print(f"  {plan.name:<12}  {plan.method:<8}  {installed:<11}  {detail}")
    return 0


def cmd_install_scanners(args: argparse.Namespace) -> int:
    """Auto-install the Python scanners into yobitsugi's isolated venv."""
    import shutil as _shutil

    from yobitsugi.core import tools

    registry = _load_scanner_registry()

    if args.all:
        targets = tools.build_install_plans(registry)
    else:
        venv_bin = tools.tools_bin_path() if tools.venv_exists() else None
        missing_binaries = set()
        for _lang, scanners in registry.items():
            for s in scanners:
                binary = s["binary"]
                on_path = _shutil.which(binary) is not None
                in_venv = venv_bin is not None and (venv_bin / binary).exists()
                if not (on_path or in_venv):
                    missing_binaries.add(binary)
        targets = tools.build_install_plans(registry, missing_binaries=missing_binaries)

    pip_targets = [p for p in targets if p.method == "pip" and not p.already_installed]
    other_targets = [p for p in targets if p.method != "pip"]

    if pip_targets:
        print(f"[install-scanners] managed venv: {tools.VENV_DIR}")
        print(f"[install-scanners] installing {len(pip_targets)} Python scanner(s)...")
        tools.ensure_venv()
        failures: list[str] = []
        for plan in pip_targets:
            print(f"  - {plan.name} ({plan.package})", end=" ... ", flush=True)
            ok, msg = tools.install_python_tool(plan.name, plan.package or plan.name)
            print("ok" if ok else "FAILED")
            if not ok:
                print(f"      {msg}")
                failures.append(plan.name)
        if failures:
            print(f"\n[install-scanners] {len(failures)} failed: {', '.join(failures)}")
            return 1
    else:
        print("[install-scanners] no Python scanners need installing.")

    if other_targets:
        print("\n[install-scanners] non-Python scanners (manual install required):")
        for plan in other_targets:
            hint = plan.hint or f"install via {plan.method}"
            print(f"  - {plan.name:<14}  {hint}")

    print(
        "\n[install-scanners] done. `yobitsugi scan` will now find the installed tools "
        "automatically (the managed venv is prepended to PATH for scanner subprocesses)."
    )
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Install the native scanners that can't be packaged inside a Python wheel.

    Right now that's just trufflehog (a Go binary). We delegate to the system
    package manager the user already has (brew on macOS, apt on Debian/Ubuntu,
    dnf/yum on Fedora). The Python-installable scanners are already in the
    wheel — see pyproject.toml's [project] dependencies.
    """
    import platform
    import shutil as _shutil

    # Map: scanner binary name → list of (manager, install command). First
    # manager that's actually on PATH wins.
    candidates: dict[str, list[tuple[str, list[str]]]] = {
        "trufflehog": [
            ("brew",    ["brew", "install", "trufflehog"]),
            ("apt",     ["sudo", "apt-get", "install", "-y", "trufflehog"]),
            ("dnf",     ["sudo", "dnf", "install", "-y", "trufflehog"]),
            ("yum",     ["sudo", "yum", "install", "-y", "trufflehog"]),
        ],
    }

    targets = args.scanner or list(candidates.keys())
    rc = 0
    for name in targets:
        if name not in candidates:
            print(f"[bootstrap] unknown scanner: {name}")
            rc = 1
            continue
        if _shutil.which(name) is not None:
            print(f"[bootstrap] {name}: already installed (on PATH).")
            continue

        plan = None
        for manager, cmd in candidates[name]:
            if _shutil.which(manager):
                plan = (manager, cmd)
                break

        if plan is None:
            mgrs = ", ".join(m for m, _ in candidates[name])
            print(
                f"[bootstrap] {name}: no supported package manager found on PATH "
                f"(looked for: {mgrs}). On {platform.system()}, install manually — "
                f"see https://github.com/trufflesecurity/trufflehog#installation"
            )
            rc = 1
            continue

        manager, cmd = plan
        print(f"[bootstrap] {name}: installing via {manager} → {' '.join(cmd)}")
        if args.dry_run:
            continue
        result = subprocess.run(cmd)  # noqa: S603 — cmd is constructed from the static map above
        if result.returncode != 0:
            print(f"[bootstrap] {name}: install failed (exit {result.returncode}).")
            rc = 1

    return rc


def cmd_uninstall_scanners(_args: argparse.Namespace) -> int:
    from yobitsugi.core import tools

    removed = tools.uninstall_all()
    if removed:
        print(f"[uninstall-scanners] removed {removed}")
    else:
        print("[uninstall-scanners] nothing to remove.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yobitsugi",
        description=(
            "Skill-first SAST/SCA tool. The CLI here only scans and reports — "
            "fix generation and application live in the host AI assistant. "
            "Works with Claude Code, Codex, Cursor, Gemini CLI, Aider, OpenCode, "
            "and GitHub Copilot CLI."
        ),
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("version", help="Print version and exit."
                   ).set_defaults(func=cmd_version)
    sub.add_parser("list-platforms",
                   help="List all supported AI assistants and whether each is installed."
                   ).set_defaults(func=cmd_list_platforms)
    sub.add_parser("detect-platforms",
                   help="Print only the assistants detected on this machine."
                   ).set_defaults(func=cmd_detect_platforms)

    p_install = sub.add_parser(
        "install",
        help="Register the /yobitsugi skill with an AI assistant.",
    )
    p_install.add_argument("--platform", choices=sorted(INSTALLERS),
                           help="Install for one specific assistant. Default: every detected one.")
    p_install.add_argument("--scope", choices=["user", "project"], default="user",
                           help="Install globally (user) or in the current repo (project).")
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="Remove the /yobitsugi skill.")
    p_uninstall.add_argument("--platform", choices=sorted(INSTALLERS))
    p_uninstall.add_argument("--scope", choices=["user", "project"], default="user")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_scan = sub.add_parser(
        "scan",
        help=(
            "Detect languages, run scanners, normalise to findings.json. "
            "This is the only scanning entrypoint — fix generation is owned "
            "by the host AI assistant via the installed skill."
        ),
    )
    p_scan.add_argument("path", type=Path)
    p_scan.add_argument("--out", type=Path,
                        help="Workspace dir (default: ~/.yobitsugi/<name>-<ts>/).")
    p_scan.add_argument(
        "--ephemeral-tools", action="store_true",
        help=(
            "Install required pip scanners into a throwaway venv just for this "
            "scan, then delete it when findings.json is written. Recommended "
            "default for the slash-command-style `/yobitsugi .` invocation."
        ),
    )
    p_scan.add_argument(
        "--concurrency", type=int, default=None,
        help=(
            "Max scanners to run in parallel. Default 6 (overridable via the "
            "YOBITSUGI_SCAN_CONCURRENCY env var). Each scanner is a subprocess "
            "so threads scale fine — the practical cap is disk/CPU on the host."
        ),
    )
    p_scan.add_argument(
        "--sequential", action="store_true",
        help="Force scanners to run one at a time. Useful for debugging.",
    )
    p_scan.add_argument(
        "--only", nargs="*",
        help="Restrict the scan to specific scanner names (e.g. --only bandit semgrep).",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_find = sub.add_parser("findings", help="Pretty-print findings.json from a workspace.")
    p_find.add_argument("workspace", type=Path)
    p_find.add_argument("--severity", nargs="*", help="Filter by severity.")
    p_find.add_argument("--type", nargs="*", help="Filter by vuln type.")
    p_find.add_argument("--json", action="store_true", help="Output raw JSON.")
    p_find.set_defaults(func=cmd_findings)

    p_sum = sub.add_parser(
        "summary",
        help=(
            "Render the workspace report (findings, missing scanners, recommended "
            "next actions) as tables for the host assistant to display."
        ),
    )
    p_sum.add_argument("workspace", type=Path)
    p_sum.add_argument(
        "--format",
        choices=["rich", "markdown", "json"],
        default="rich",
        help="'rich' = colored terminal tables (default), "
             "'markdown' = drop-into-chat markdown tables for AI assistants, "
             "'json' = structured data.",
    )
    p_sum.set_defaults(func=cmd_summary)

    sub.add_parser(
        "list-scanners",
        help="Show every supported scanner, its install method, and whether it's available.",
    ).set_defaults(func=cmd_list_scanners)

    p_is = sub.add_parser(
        "install-scanners",
        help=(
            "Install missing Python scanners (bandit/safety/pip-audit/semgrep/flawfinder) "
            "into yobitsugi's isolated venv at ~/.yobitsugi/tools/venv/. "
            "Prints install hints for non-Python scanners."
        ),
    )
    p_is.add_argument(
        "--all", action="store_true",
        help="Install every supported Python scanner, even ones already on PATH.",
    )
    p_is.set_defaults(func=cmd_install_scanners)

    sub.add_parser(
        "uninstall-scanners",
        help="Delete ~/.yobitsugi/tools/ (managed venv + manifest).",
    ).set_defaults(func=cmd_uninstall_scanners)

    p_boot = sub.add_parser(
        "bootstrap",
        help=(
            "Install native scanners that aren't pip-installable (currently "
            "just trufflehog) via the system package manager. The Python "
            "scanners — bandit, safety, pip-audit, semgrep, flawfinder, and "
            "shellcheck-py — are already bundled in the wheel."
        ),
    )
    p_boot.add_argument(
        "scanner", nargs="*",
        help="Which scanners to install. Default: all not-yet-installed native scanners.",
    )
    p_boot.add_argument(
        "--dry-run", action="store_true",
        help="Print the install command(s) without running them.",
    )
    p_boot.set_defaults(func=cmd_bootstrap)

    return p


def main(argv: list[str] | None = None) -> int:
    # Positional shortcut: `yobitsugi <path>` → `yobitsugi scan <path>`.
    # Previously this aliased to `run`, but the end-to-end pipeline has moved
    # into the skill (the host assistant orchestrates fix generation).
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in KNOWN_SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["scan", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
