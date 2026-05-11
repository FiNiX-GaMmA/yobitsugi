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


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan-only: detect → scan → parse, no LLM, no fixes."""
    from yobitsugi.core import detect, parse, scan

    workspace = args.out or (
        Path.home() / ".yobitsugi"
        / f"{args.path.name}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"workspace: {workspace}")

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
    return 0


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


def cmd_rollback(args: argparse.Namespace) -> int:
    from yobitsugi.core import apply as apply_mod

    return apply_mod.main([
        "--rollback",
        "--workspace", str(args.workspace),
        "--root", str(args.root or Path.cwd()),
    ])


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
    p_run.set_defaults(func=cmd_run)

    p_scan = sub.add_parser("scan",
                            help="Scan-only — produce findings.json without applying fixes.")
    p_scan.add_argument("path", type=Path)
    p_scan.add_argument("--out", type=Path,
                        help="Workspace dir (default: ~/.yobitsugi/<name>-<ts>/).")
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

    p_cfg = sub.add_parser("config", help="Show or initialise yobitsugi config.")
    p_cfg.add_argument("--init", action="store_true",
                       help="Write a starter ~/.yobitsugi/config.yaml.")
    p_cfg.add_argument("--force", action="store_true", help="Overwrite existing config.")
    p_cfg.set_defaults(func=cmd_config)

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
