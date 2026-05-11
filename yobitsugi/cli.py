"""yobitsugi CLI entrypoint.

Subcommands:
  yobitsugi install [--platform <name>] [--scope user|project]
  yobitsugi uninstall [--platform <name>] [--scope user|project]
  yobitsugi list-platforms
  yobitsugi detect-platforms
  yobitsugi run <path> [pipeline flags]
  yobitsugi scan <path> [--out <ws>]
  yobitsugi findings <workspace>
  yobitsugi rollback <workspace>
  yobitsugi config [--print|--init]
  yobitsugi version

Positional shortcut: `yobitsugi <path>` is treated as `yobitsugi run <path>` to mirror
the graphify-style `/yobitsugi .` invocation pattern from inside an assistant.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from yobitsugi import __version__
from yobitsugi.installers import INSTALLERS, get_installer

KNOWN_SUBCOMMANDS = {
    "version", "list-platforms", "detect-platforms", "install", "uninstall",
    "run", "scan", "findings", "rollback", "config",
    "install-scanners", "uninstall-scanners", "list-scanners",
    "summary",
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


def cmd_run(args: argparse.Namespace) -> int:
    from yobitsugi.core.pipeline import run_pipeline

    def _go() -> int:
        return run_pipeline(
            root=args.path,
            workspace=args.workspace,
            severity=args.severity,
            auto=args.auto,
            allow_dirty=args.allow_dirty,
            provider=args.provider,
            model=args.model,
            skip_tests=args.skip_tests,
        )

    return _with_optional_ephemeral_tools(_go, args, root=args.path)


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan-only: detect → scan → parse, no LLM, no fixes."""
    from yobitsugi.core import detect, parse, scan

    workspace = args.out or (
        Path.home() / ".yobitsugi"
        / f"{args.path.name}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"workspace: {workspace}")

    def _go() -> int:
        for label, fn, argv in (
            ("detect", detect.main, ["--root", str(args.path), "--out", str(workspace)]),
            ("scan",   scan.main,   ["--workspace", str(workspace), "--root", str(args.path)]),
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

        # Detailed tabular report — same one `yobitsugi run` emits at completion.
        from yobitsugi.core import summary as summary_mod
        summary_mod.render(workspace, mode="rich")
        return 0

    return _with_optional_ephemeral_tools(_go, args, root=args.path)


def _with_optional_ephemeral_tools(fn, args: argparse.Namespace, root: Path) -> int:
    """If --ephemeral-tools was passed, run `fn` inside an ephemeral venv that
    holds just the pip-installable scanners we need, then delete it. Otherwise
    run `fn` against the persistent ~/.yobitsugi/tools/venv/ (or the user's PATH).

    Both behaviours go through this single wrapper so the slash-command-style
    invocation pattern ("/yobitsugi . — install, scan, fix, clean up") is the
    one-flag path it claims to be.
    """
    if not getattr(args, "ephemeral_tools", False):
        return fn()

    from yobitsugi.core import tools

    # Pre-load the registry and detect languages once so we can install only the
    # scanners the repo will actually use. Detection re-runs inside the pipeline
    # too, but that's cheap and keeps the install step language-aware here.
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
    """Lightweight wrapper around detect.detect so the ephemeral-tools pre-install
    can target the right scanners. Returns [] on any error so the caller falls
    back to installing every pip scanner."""
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
    """Render the workspace's findings/applied/validation/scan_report as tables."""
    from yobitsugi.core import summary as summary_mod

    if not args.workspace.is_dir():
        print(f"[summary] no such workspace: {args.workspace}", file=sys.stderr)
        return 1
    summary_mod.render(args.workspace, mode=args.format)
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    from yobitsugi.core import apply as apply_mod

    return apply_mod.main([
        "--rollback",
        "--workspace", str(args.workspace),
        "--root", str(args.root or Path.cwd()),
    ])


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
        # `installed` means: binary is reachable on PATH OR sits in the managed venv.
        on_path = _shutil.which(plan.name) is not None
        in_venv = venv_bin is not None and (venv_bin / plan.name).exists()
        installed = "yes" if (on_path or in_venv) else "no"
        if in_venv and not on_path:
            installed += " (venv)"
        detail = plan.package or plan.hint or "—"
        print(f"  {plan.name:<12}  {plan.method:<8}  {installed:<11}  {detail}")
    return 0


def cmd_install_scanners(args: argparse.Namespace) -> int:
    """Auto-install the Python scanners into yobitsugi's isolated venv.

    For non-Python scanners, print install hints — yobitsugi won't manage a Node /
    Go / gem / cargo / brew install on the user's behalf.
    """
    import shutil as _shutil

    from yobitsugi.core import tools

    registry = _load_scanner_registry()

    # Filter to "missing" scanners unless --all was passed: a scanner is "missing"
    # when its binary isn't on the user's PATH AND isn't in our managed venv.
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


def cmd_uninstall_scanners(_args: argparse.Namespace) -> int:
    from yobitsugi.core import tools

    removed = tools.uninstall_all()
    if removed:
        print(f"[uninstall-scanners] removed {removed}")
    else:
        print("[uninstall-scanners] nothing to remove.")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    cfg_path = Path.home() / ".yobitsugi" / "config.yaml"

    if args.init:
        if cfg_path.exists() and not args.force:
            print(f"{cfg_path} already exists. Pass --force to overwrite.", file=sys.stderr)
            return 1
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            "# yobitsugi config — see yobitsugi/data/providers.md for options.\n"
            "provider: openai\n"
            "model: gpt-4o-mini\n"
            "# api_key: ...           # prefer env vars: OPENAI_API_KEY, ANTHROPIC_API_KEY, ...\n"
            "# base_url: http://localhost:1234/v1   # for openai-compatible endpoints\n"
        )
        print(f"wrote {cfg_path}")
        return 0

    from yobitsugi.core.llm import resolve_config
    try:
        cfg = resolve_config()
    except SystemExit as e:
        return int(e.code) if e.code else 1
    print(json.dumps({
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "api_key_set": bool(cfg.api_key),
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yobitsugi",
        description=(
            "AI coding assistant skill for finding and fixing repo vulnerabilities. "
            "Works with Claude Code, Codex, Cursor, Gemini CLI, Aider, OpenCode, and more."
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
        "install", help="Register the /yobitsugi command with an AI assistant.")
    p_install.add_argument("--platform", choices=sorted(INSTALLERS),
                           help="Install for one specific assistant. Default: every detected one.")
    p_install.add_argument("--scope", choices=["user", "project"], default="user",
                           help="Install globally (user) or in the current repo (project).")
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="Remove the /yobitsugi command.")
    p_uninstall.add_argument("--platform", choices=sorted(INSTALLERS))
    p_uninstall.add_argument("--scope", choices=["user", "project"], default="user")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_run = sub.add_parser(
        "run", help="End-to-end: detect → scan → parse → fix → apply → tests → validate.")
    p_run.add_argument("path", type=Path, help="Repo root.")
    p_run.add_argument("--workspace", type=Path)
    p_run.add_argument("--severity", nargs="*", default=["CRITICAL", "HIGH"])
    p_run.add_argument("--auto", action="store_true",
                       help="Apply fixes without confirmation. Use cautiously.")
    p_run.add_argument("--allow-dirty", action="store_true",
                       help="Don't refuse to run on a dirty git tree.")
    p_run.add_argument("--provider",
                       help="openai | anthropic | google | ollama | openai-compatible")
    p_run.add_argument("--model", help="Model name (provider-specific).")
    p_run.add_argument("--skip-tests", action="store_true")
    p_run.add_argument(
        "--ephemeral-tools", action="store_true",
        help=(
            "Install required pip scanners into a throwaway venv just for this "
            "run, then delete it when the report is written. Keeps the user's "
            "Python env and ~/.yobitsugi/tools/ untouched. Recommended for the "
            "slash-command-style `/yobitsugi .` invocation."
        ),
    )
    p_run.set_defaults(func=cmd_run)

    p_scan = sub.add_parser("scan",
                            help="Scan-only — produce findings.json without applying fixes.")
    p_scan.add_argument("path", type=Path)
    p_scan.add_argument("--out", type=Path,
                        help="Workspace dir (default: ~/.yobitsugi/<name>-<ts>/).")
    p_scan.add_argument(
        "--ephemeral-tools", action="store_true",
        help=(
            "Install required pip scanners into a throwaway venv just for this "
            "scan, then delete it when findings.json is written."
        ),
    )
    p_scan.set_defaults(func=cmd_scan)

    p_find = sub.add_parser("findings", help="Pretty-print findings.json from a workspace.")
    p_find.add_argument("workspace", type=Path)
    p_find.add_argument("--severity", nargs="*", help="Filter by severity.")
    p_find.add_argument("--type", nargs="*", help="Filter by vuln type.")
    p_find.add_argument("--json", action="store_true", help="Output raw JSON.")
    p_find.set_defaults(func=cmd_findings)

    p_rb = sub.add_parser("rollback",
                          help="Restore .yobitsugi.bak files from a workspace's applied.json.")
    p_rb.add_argument("workspace", type=Path)
    p_rb.add_argument("--root", type=Path, help="Repo root (defaults to CWD).")
    p_rb.set_defaults(func=cmd_rollback)

    p_sum = sub.add_parser(
        "summary",
        help=(
            "Render a detailed post-run report (findings, fix outcomes, validation, "
            "missing scanners, recommended next actions) as tables."
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

    p_cfg = sub.add_parser("config", help="Show or initialise yobitsugi config.")
    p_cfg.add_argument("--init", action="store_true",
                       help="Write a starter ~/.yobitsugi/config.yaml.")
    p_cfg.add_argument("--force", action="store_true", help="Overwrite existing config.")
    p_cfg.set_defaults(func=cmd_config)

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

    return p


def main(argv: list[str] | None = None) -> int:
    # Positional shortcut: `yobitsugi <path>` → `yobitsugi run <path>`.
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] not in KNOWN_SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["run", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
