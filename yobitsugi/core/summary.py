"""Post-run summary: render findings + fixes + validation as tables + choice menu.

Called automatically at the end of `yobitsugi run` and `yobitsugi scan`. The output
is designed to be readable in three contexts:

  1. A terminal — rich tables with colour.
  2. An AI assistant chat — markdown tables (no ANSI codes), so the assistant can
     surface them verbatim or paraphrase them.
  3. Machine consumption — a JSON variant with the same data, for the assistant
     to drive its own next-action prompt.
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
    """Aggregate findings / applied / validation / scan_report into one structured dict.

    The output is the single source of truth for both the rich/markdown renderers below
    and the `--json` CLI flag. Every field is JSON-safe.
    """
    findings = _read_json(workspace / "findings.json") or []
    applied = _read_json(workspace / "applied.json") or []
    validation = _read_json(workspace / "validation.json") or {}
    scan_report = _read_json(workspace / "scan_report.json") or {}

    # Per-finding outcome: applied / cannot_fix / not_attempted / failed.
    applied_by_fid: dict[str, dict] = {}
    for entry in applied:
        fid = entry.get("finding_id")
        if fid:
            applied_by_fid[fid] = entry

    fixed_ids = set(validation.get("fixed_ids") or [])
    still_present = set(validation.get("still_present") or [])
    newly_introduced = validation.get("newly_introduced") or []

    finding_rows: list[dict] = []
    for f in findings:
        fid = f.get("id", "")
        applied_entry = applied_by_fid.get(fid)
        if applied_entry and applied_entry.get("rolled_back"):
            outcome = "rolled_back"
        elif applied_entry:
            outcome = "applied"
        else:
            outcome = "not_attempted"
        validation_state = (
            "fixed" if fid in fixed_ids
            else "still_present" if fid in still_present
            else "n/a"
        )
        finding_rows.append({
            "id": fid,
            "severity": f.get("severity", "UNKNOWN"),
            "type": f.get("type", "OTHER"),
            "tool": f.get("tool", "?"),
            "file": f.get("file") or "—",
            "line": f.get("line"),
            "title": f.get("title", "") or f.get("description", "")[:80],
            "description": f.get("description", ""),
            "outcome": outcome,
            "validation": validation_state,
            "applied_files": (applied_entry or {}).get("files", []),
        })

    # Severity rollup.
    counts_by_severity = Counter(r["severity"] for r in finding_rows)
    counts_by_type = Counter(r["type"] for r in finding_rows)
    counts_by_outcome = Counter(r["outcome"] for r in finding_rows)

    # Missing scanners from scan_report.json.
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

    # Next-action recommendations, ranked.
    actions = _suggest_actions(
        workspace, finding_rows, newly_introduced, missing_scanners, counts_by_outcome,
    )

    return {
        "workspace": str(workspace),
        "totals": {
            "findings": len(finding_rows),
            "applied": counts_by_outcome.get("applied", 0),
            "rolled_back": counts_by_outcome.get("rolled_back", 0),
            "not_attempted": counts_by_outcome.get("not_attempted", 0),
            "fixed": len(fixed_ids),
            "still_present": len(still_present),
            "newly_introduced": len(newly_introduced),
            "missing_scanners": len(missing_scanners),
        },
        "by_severity": dict(counts_by_severity),
        "by_type": dict(counts_by_type),
        "findings": finding_rows,
        "newly_introduced": newly_introduced,
        "missing_scanners": missing_scanners,
        "next_actions": actions,
    }


def _suggest_actions(
    workspace: Path,
    findings: list[dict],
    newly_introduced: list[dict],
    missing_scanners: list[dict],
    counts_by_outcome: Counter,
) -> list[dict]:
    """Produce a ranked list of {label, command, why} suggestions."""
    actions: list[dict] = []

    if newly_introduced:
        actions.append({
            "label": f"Roll back ALL fixes — {len(newly_introduced)} new vulnerabilities were introduced",
            "command": f"yobitsugi rollback {workspace}",
            "why": (
                "The validate step found vulnerabilities that didn't exist before this "
                "run. The safest move is to undo every patch and review them by hand."
            ),
            "priority": "high",
        })

    auto_installable_missing = [m for m in missing_scanners if m.get("install_method") == "pip"]
    if auto_installable_missing:
        names = ", ".join(m["name"] for m in auto_installable_missing)
        actions.append({
            "label": f"Install {len(auto_installable_missing)} missing Python scanner(s) ({names})",
            "command": "yobitsugi install-scanners",
            "why": (
                "These scanners aren't on PATH yet, so their findings were silently "
                "missing from this run. Installing them into yobitsugi's isolated venv "
                "lets the next scan see those issues."
            ),
            "priority": "high",
        })

    cannot_fix = [f for f in findings if f["outcome"] == "not_attempted"]
    if cannot_fix:
        actions.append({
            "label": f"Investigate {len(cannot_fix)} unfixed finding(s) by hand",
            "command": f"yobitsugi findings {workspace} --severity HIGH CRITICAL --json",
            "why": (
                "These findings were either below the severity threshold or the LLM "
                "returned CANNOT_FIX. Review the raw JSON to decide whether to write "
                "manual fixes."
            ),
            "priority": "medium",
        })

    if counts_by_outcome.get("applied", 0) > 0 and not newly_introduced:
        actions.append({
            "label": "Accept the applied fixes and commit them to git",
            "command": "git diff   # review, then git add . && git commit",
            "why": (
                "Fixes were applied and validation didn't flag any new vulnerabilities. "
                "Make a commit so the change is durable."
            ),
            "priority": "medium",
        })

    actions.append({
        "label": "Re-scan only (no fixes) to confirm the current state",
        "command": f"yobitsugi scan {workspace.parent}",
        "why": "Read-only — useful for a sanity check after applying or rolling back.",
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
    totals_tbl.add_row("Fixes applied", str(totals["applied"]))
    totals_tbl.add_row("Fixes rolled back", str(totals["rolled_back"]))
    totals_tbl.add_row("Findings not attempted", str(totals["not_attempted"]))
    totals_tbl.add_row("Validated fixed", f"[green]{totals['fixed']}[/green]")
    totals_tbl.add_row("Still present", f"[yellow]{totals['still_present']}[/yellow]")
    totals_tbl.add_row(
        "Newly introduced",
        f"[red]{totals['newly_introduced']}[/red]" if totals["newly_introduced"] else "0",
    )
    totals_tbl.add_row("Missing scanners", str(totals["missing_scanners"]))
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
        find_tbl.add_column("Fix outcome")
        find_tbl.add_column("Validation")
        for row in summary["findings"]:
            sev = row["severity"]
            sev_styled = f"[{SEVERITY_COLOR.get(sev, 'white')}]{sev}[/]"
            loc = f"{row['file']}:{row['line']}" if row.get("line") else row["file"]
            outcome_style = {
                "applied": "[green]applied[/green]",
                "rolled_back": "[yellow]rolled back[/yellow]",
                "not_attempted": "[dim]not attempted[/dim]",
            }.get(row["outcome"], row["outcome"])
            valid_style = {
                "fixed": "[green]fixed[/green]",
                "still_present": "[yellow]still present[/yellow]",
                "n/a": "[dim]n/a[/dim]",
            }.get(row["validation"], row["validation"])
            find_tbl.add_row(
                sev_styled, row["type"], row["tool"], loc, row["title"],
                outcome_style, valid_style,
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

    # Newly introduced (loud red panel)
    if summary["newly_introduced"]:
        console.print(Panel(
            "\n".join(
                f"• {n.get('severity', '?')}  {n.get('type', '?')}  "
                f"{n.get('file', '?')}:{n.get('line', '?')}"
                for n in summary["newly_introduced"]
            ),
            title=f"[bold red]⚠  {len(summary['newly_introduced'])} NEWLY INTRODUCED — "
                  f"the patches created these. Review immediately.[/bold red]",
            border_style="red",
        ))

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
    out.append(f"| Fixes applied | {totals['applied']} |")
    out.append(f"| Fixes rolled back | {totals['rolled_back']} |")
    out.append(f"| Findings not attempted | {totals['not_attempted']} |")
    out.append(f"| Validated fixed | {totals['fixed']} |")
    out.append(f"| Still present | {totals['still_present']} |")
    out.append(f"| **Newly introduced** | **{totals['newly_introduced']}** |")
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
        out.append("| Sev | Type | Tool | File:Line | Title | Fix outcome | Validation |")
        out.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in summary["findings"]:
            loc = f"{r['file']}:{r['line']}" if r.get("line") else r["file"]
            title = (r["title"] or "")[:80].replace("|", "\\|")
            out.append(
                f"| {r['severity']} | {r['type']} | {r['tool']} | "
                f"`{loc}` | {title} | {r['outcome']} | {r['validation']} |"
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

    # Newly introduced (loud)
    if summary["newly_introduced"]:
        out.append(f"## ⚠ {len(summary['newly_introduced'])} newly-introduced findings")
        out.append("")
        out.append("These vulnerabilities did not exist before this run — patches created them.")
        out.append("")
        out.append("| Severity | Type | File:Line |")
        out.append("| --- | --- | --- |")
        for n in summary["newly_introduced"]:
            loc = f"{n.get('file', '?')}:{n.get('line', '?')}"
            out.append(f"| {n.get('severity', '?')} | {n.get('type', '?')} | `{loc}` |")
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
