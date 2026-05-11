"""Post-scan summary: render findings + missing-scanner status as tables + next-action menu.

Called automatically at the end of `yobitsugi scan` and on demand via
`yobitsugi summary <ws>`. The output is designed to be readable in three contexts:

  1. A terminal — rich tables with colour.
  2. An AI assistant chat — markdown tables (no ANSI codes), so the host
     assistant can surface them verbatim or paraphrase them.
  3. Machine consumption — a JSON variant with the same data, for the assistant
     to drive its own next-action prompt.

Yobitsugi became skill-first in v0.2: fix generation, apply, and validation
live in the host AI assistant, not the CLI. So this summary no longer reports
"fixes applied / rolled back / validated fixed / newly introduced" — those
files (`applied.json`, `validation.json`) aren't written by `yobitsugi scan`
anymore. The schema preserves the keys with zero values so any external
caller that read them still parses cleanly, but the rendered output omits
the zero-only rows.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# `rich` is already a hard dependency declared in pyproject.toml.
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
SEVERITY_COLOR = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "cyan",
    "UNKNOWN": "white",
}


def _read_json(path: Path) -> Any | None:
    """Read a JSON file, return None if it's missing or unreadable."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def build_summary(workspace: Path) -> dict:
    """Aggregate findings + scan_report into one structured dict.

    The output is the single source of truth for both the rich/markdown
    renderers below and the `--json` CLI flag. Every field is JSON-safe.

    Skill-first: this no longer reads applied.json / validation.json — those
    aren't written by the CLI any more. The fix/apply/validate loop lives in
    the host AI assistant. Findings carry no `outcome` or `validation` field
    in the new schema; the assistant tracks per-fix state in the chat
    transcript instead.
    """
    findings = _read_json(workspace / "findings.json") or []
    scan_report = _read_json(workspace / "scan_report.json") or {}

    finding_rows: list[dict] = []
    for f in findings:
        finding_rows.append({
            "id": f.get("id", ""),
            "severity": f.get("severity", "UNKNOWN"),
            "type": f.get("type", "OTHER"),
            "tool": f.get("tool", "?"),
            "file": f.get("file") or "—",
            "line": f.get("line"),
            "title": f.get("title", "") or (f.get("description") or "")[:80],
            "description": f.get("description", ""),
            "code_snippet": f.get("code_snippet", ""),
            "rule_id": f.get("rule_id", ""),
        })

    counts_by_severity = Counter(r["severity"] for r in finding_rows)
    counts_by_type = Counter(r["type"] for r in finding_rows)

    scanner_reports = scan_report.get("scanners") or []
    missing_scanners = [
        {
            "name": s.get("name"),
            "binary": s.get("binary"),
            "install_method": s.get("install_method"),
            "install_package": s.get("install_package"),
            "install_hint": s.get("install_hint"),
        }
        for s in scanner_reports
        if s.get("status") == "skipped_missing_tool"
    ]
    scanner_status_counts = Counter(
        s.get("status", "unknown") for s in scanner_reports
    )

    actions = _suggest_actions(workspace, finding_rows, missing_scanners)

    return {
        "workspace": str(workspace),
        "totals": {
            "findings": len(finding_rows),
            "scanners_ok": scanner_status_counts.get("ok", 0),
            "scanners_skipped_missing_tool": scanner_status_counts.get(
                "skipped_missing_tool", 0
            ),
            "scanners_errored": (
                scanner_status_counts.get("error", 0)
                + scanner_status_counts.get("timeout", 0)
                + scanner_status_counts.get("no_output", 0)
            ),
            "missing_scanners": len(missing_scanners),
        },
        "by_severity": dict(counts_by_severity),
        "by_type": dict(counts_by_type),
        "findings": finding_rows,
        "missing_scanners": missing_scanners,
        "next_actions": actions,
    }


def _suggest_actions(
    workspace: Path,
    findings: list[dict],
    missing_scanners: list[dict],
) -> list[dict]:
    """Produce a ranked list of {label, command, why} suggestions for the host
    AI assistant to choose from.

    Skill-first: there's no "rollback" or "commit the applied fixes" action
    here, because the CLI no longer applies fixes — that's the assistant's job
    via its own edit tool. The actions left here are the scan-side moves:
    install missing scanners, hand the findings JSON over for the fix loop,
    and re-scan to validate.
    """
    actions: list[dict] = []

    auto_installable_missing = [m for m in missing_scanners if m.get("install_method") == "pip"]
    if auto_installable_missing:
        names = ", ".join(m["name"] for m in auto_installable_missing)
        actions.append({
            "label": f"Install {len(auto_installable_missing)} missing Python scanner(s) ({names})",
            "command": "yobitsugi install-scanners",
            "why": (
                "These scanners aren't on PATH yet, so their findings were silently "
                "missing from this run. Installing them into yobitsugi's isolated venv "
                "lets the next scan see those issues. (Or pass --ephemeral-tools "
                "next time and we'll do it in a throwaway venv.)"
            ),
            "priority": "high",
        })

    manual_missing = [m for m in missing_scanners if m.get("install_method") != "pip"]
    if manual_missing:
        hints = "; ".join(
            f"{m['name']} → {m.get('install_hint') or m.get('install_method') or 'manual'}"
            for m in manual_missing
        )
        actions.append({
            "label": f"Install {len(manual_missing)} non-Python scanner(s) via their own runtime",
            "command": "# run each install hint by hand",
            "why": (
                "yobitsugi doesn't manage npm/go/gem/brew installs. Install commands: "
                + hints
            ),
            "priority": "medium",
        })

    high_severity = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH")]
    if high_severity:
        actions.append({
            "label": (
                f"Walk the host AI assistant through the {len(high_severity)} CRITICAL/HIGH "
                f"finding(s) and apply fixes interactively"
            ),
            "command": f"yobitsugi findings {workspace} --severity CRITICAL HIGH --json",
            "why": (
                "The skill instructs the assistant to read findings.json, propose a diff "
                "per finding, ask before applying, and apply with its own edit tool."
            ),
            "priority": "high",
        })

    actions.append({
        "label": "Re-scan to confirm the current state after applying fixes",
        "command": f"yobitsugi scan {workspace.parent} --ephemeral-tools --out {workspace}",
        "why": (
            "Read-only. Compare findings ids against the previous scan: ids gone are "
            "fixed, ids still present are unresolved, ids new are regressions the "
            "assistant's edits introduced."
        ),
        "priority": "low",
    })

    return actions


# ---------------------------------------------------------------------------
#                          Rich (terminal) rendering
# ---------------------------------------------------------------------------

def render_rich(summary: dict, console: Console | None = None) -> None:
    """Pretty-print the summary as rich tables to the terminal."""
    console = console or Console()
    totals = summary["totals"]

    # Header
    console.print()
    console.print(Panel.fit(
        f"[bold]yobitsugi summary[/bold]   workspace: [cyan]{summary['workspace']}[/cyan]",
        border_style="blue",
    ))

    # Totals table
    totals_tbl = Table(title="Run totals", show_header=True, header_style="bold")
    totals_tbl.add_column("Metric", style="cyan")
    totals_tbl.add_column("Count", justify="right")
    totals_tbl.add_row("Findings (total)", str(totals["findings"]))
    totals_tbl.add_row("Scanners ok", f"[green]{totals['scanners_ok']}[/green]")
    totals_tbl.add_row(
        "Scanners skipped (missing)",
        f"[yellow]{totals['scanners_skipped_missing_tool']}[/yellow]",
    )
    totals_tbl.add_row(
        "Scanners errored",
        f"[red]{totals['scanners_errored']}[/red]" if totals["scanners_errored"] else "0",
    )
    console.print(totals_tbl)

    # Severity breakdown
    if summary["by_severity"]:
        sev_tbl = Table(title="Findings by severity", show_header=True, header_style="bold")
        sev_tbl.add_column("Severity")
        sev_tbl.add_column("Count", justify="right")
        for sev in SEVERITY_ORDER:
            n = summary["by_severity"].get(sev, 0)
            if n:
                sev_tbl.add_row(f"[{SEVERITY_COLOR[sev]}]{sev}[/]", str(n))
        console.print(sev_tbl)

    # Per-finding detail
    if summary["findings"]:
        find_tbl = Table(
            title="Findings", show_header=True, header_style="bold",
            row_styles=["", "dim"],
        )
        find_tbl.add_column("Sev", style="bold")
        find_tbl.add_column("Type")
        find_tbl.add_column("Tool")
        find_tbl.add_column("File:Line", overflow="fold")
        find_tbl.add_column("Title", overflow="fold")
        for row in summary["findings"]:
            sev = row["severity"]
            sev_styled = f"[{SEVERITY_COLOR.get(sev, 'white')}]{sev}[/]"
            loc = f"{row['file']}:{row['line']}" if row.get("line") else row["file"]
            find_tbl.add_row(
                sev_styled, row["type"], row["tool"], loc, row["title"],
            )
        console.print(find_tbl)

    # Missing scanners
    if summary["missing_scanners"]:
        ms_tbl = Table(
            title="Missing scanners (skipped during scan)",
            show_header=True, header_style="bold yellow",
        )
        ms_tbl.add_column("Scanner")
        ms_tbl.add_column("Install method")
        ms_tbl.add_column("Install command / hint", overflow="fold")
        for m in summary["missing_scanners"]:
            method = m.get("install_method") or "manual"
            cmd = (
                "yobitsugi install-scanners" if method == "pip"
                else (m.get("install_hint") or "(see project docs)")
            )
            ms_tbl.add_row(m["name"], method, cmd)
        console.print(ms_tbl)

    # Next-action menu
    if summary["next_actions"]:
        act_tbl = Table(
            title="What next?", show_header=True, header_style="bold green",
        )
        act_tbl.add_column("#", justify="right", style="bold")
        act_tbl.add_column("Action")
        act_tbl.add_column("Command", style="cyan", overflow="fold")
        act_tbl.add_column("Why", overflow="fold")
        for i, a in enumerate(summary["next_actions"], 1):
            act_tbl.add_row(str(i), a["label"], a["command"], a["why"])
        console.print(act_tbl)

    console.print()


# ---------------------------------------------------------------------------
#                       Markdown rendering (for assistants)
# ---------------------------------------------------------------------------

def render_markdown(summary: dict) -> str:
    """Render the same data as markdown tables. Safe to drop into a chat message."""
    totals = summary["totals"]
    out: list[str] = []
    out.append(f"# yobitsugi summary — `{summary['workspace']}`")
    out.append("")

    # Totals
    out.append("## Run totals")
    out.append("")
    out.append("| Metric | Count |")
    out.append("| --- | ---: |")
    out.append(f"| Findings (total) | {totals['findings']} |")
    out.append(f"| Scanners ok | {totals['scanners_ok']} |")
    out.append(f"| Scanners skipped (missing tool) | {totals['scanners_skipped_missing_tool']} |")
    out.append(f"| Scanners errored | {totals['scanners_errored']} |")
    out.append(f"| Missing scanners | {totals['missing_scanners']} |")
    out.append("")

    # Severity breakdown
    if summary["by_severity"]:
        out.append("## Findings by severity")
        out.append("")
        out.append("| Severity | Count |")
        out.append("| --- | ---: |")
        for sev in SEVERITY_ORDER:
            n = summary["by_severity"].get(sev, 0)
            if n:
                out.append(f"| {sev} | {n} |")
        out.append("")

    # Per-finding
    if summary["findings"]:
        out.append("## Findings")
        out.append("")
        out.append("| Sev | Type | Tool | File:Line | Title |")
        out.append("| --- | --- | --- | --- | --- |")
        for r in summary["findings"]:
            loc = f"{r['file']}:{r['line']}" if r.get("line") else r["file"]
            title = (r["title"] or "")[:80].replace("|", "\\|")
            out.append(
                f"| {r['severity']} | {r['type']} | {r['tool']} | "
                f"`{loc}` | {title} |"
            )
        out.append("")

    # Missing scanners
    if summary["missing_scanners"]:
        out.append("## Missing scanners")
        out.append("")
        out.append("| Scanner | Install method | Install command / hint |")
        out.append("| --- | --- | --- |")
        for m in summary["missing_scanners"]:
            method = m.get("install_method") or "manual"
            cmd = (
                "`yobitsugi install-scanners`" if method == "pip"
                else (m.get("install_hint") or "(see project docs)")
            )
            out.append(f"| {m['name']} | {method} | {cmd} |")
        out.append("")

    # Next-action menu
    if summary["next_actions"]:
        out.append("## What next?")
        out.append("")
        out.append("| # | Action | Command | Why |")
        out.append("| ---: | --- | --- | --- |")
        for i, a in enumerate(summary["next_actions"], 1):
            why = a["why"].replace("|", "\\|")
            out.append(f"| {i} | {a['label']} | `{a['command']}` | {why} |")
        out.append("")

    return "\n".join(out)


def render(workspace: Path, *, mode: str = "auto", console: Console | None = None) -> None:
    """High-level entry point. mode = 'auto' | 'rich' | 'markdown' | 'json'."""
    summary = build_summary(workspace)

    if mode == "json":
        print(json.dumps(summary, indent=2, default=str))
        return
    if mode == "markdown":
        print(render_markdown(summary))
        return
    # 'rich' or 'auto' both use rich; rich auto-strips ANSI when piped.
    render_rich(summary, console=console)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("workspace", type=Path)
    p.add_argument(
        "--format",
        choices=["rich", "markdown", "json"],
        default="rich",
        help="Output format. 'rich' = colored tables for terminals; "
             "'markdown' = drop-into-chat markdown tables; "
             "'json' = structured data for downstream tools.",
    )
    args = p.parse_args(argv)

    if not args.workspace.is_dir():
        sys.stderr.write(f"[summary] no such workspace: {args.workspace}\n")
        return 1

    render(args.workspace, mode=args.format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
