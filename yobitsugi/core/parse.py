#!/usr/bin/env python3
"""
parse_reports.py — Normalize every scanner's raw output into the unified Finding
schema described in SKILL.md. Writes workspace/findings.json.

Adding a new parser:
  1. Write a function `_parse_<scanner_name>(raw_text: str, root: Path) -> list[Finding]`
  2. Register it in PARSERS at the bottom.
  3. That's it. Stay faithful to the Finding schema.

Usage:
    python parse_reports.py --workspace workspace/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable


SEVERITY_MAP = {
    "critical": "CRITICAL", "crit": "CRITICAL",
    "high": "HIGH", "error": "HIGH", "ERROR": "HIGH",
    "medium": "MEDIUM", "moderate": "MEDIUM", "warning": "MEDIUM", "WARNING": "MEDIUM",
    "low": "LOW", "info": "LOW", "note": "LOW", "INFO": "LOW", "NOTE": "LOW",
    "unknown": "UNKNOWN",
}

# Map common rule patterns → normalized type. Heuristic but useful: it lets the
# fix-generator route requests, e.g. SQL_INJECTION findings get a SQLi-specific prompt.
TYPE_HINTS: list[tuple[str, str]] = [
    ("sql", "SQL_INJECTION"),
    ("injection", "COMMAND_INJECTION"),  # secondary
    ("xss", "XSS"),
    ("cross-site", "XSS"),
    ("hardcoded", "HARDCODED_SECRET"),
    ("secret", "HARDCODED_SECRET"),
    ("password", "HARDCODED_SECRET"),
    ("api_key", "HARDCODED_SECRET"),
    ("crypto", "WEAK_CRYPTO"),
    ("md5", "WEAK_CRYPTO"),
    ("sha1", "WEAK_CRYPTO"),
    ("deserial", "INSECURE_DESERIALIZATION"),
    ("pickle", "INSECURE_DESERIALIZATION"),
    ("ssrf", "SSRF"),
    ("redirect", "OPEN_REDIRECT"),
    ("traversal", "PATH_TRAVERSAL"),
    ("path", "PATH_TRAVERSAL"),  # weak signal
    ("command", "COMMAND_INJECTION"),
    ("shell", "COMMAND_INJECTION"),
    ("exec", "COMMAND_INJECTION"),
]


def normalize_severity(s: Any) -> str:
    if s is None:
        return "UNKNOWN"
    return SEVERITY_MAP.get(str(s).strip().lower(), str(s).strip().upper() or "UNKNOWN")


def classify_type(text: str) -> str:
    text_lc = (text or "").lower()
    for needle, typ in TYPE_HINTS:
        if needle in text_lc:
            return typ
    return "OTHER"


def make_id(*parts: Any) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:16]


def finding(
    tool: str,
    *,
    language: str = "",
    file: str | None = None,
    line: int | None = None,
    end_line: int | None = None,
    rule_id: str = "",
    severity: str = "UNKNOWN",
    confidence: str = "",
    title: str = "",
    description: str = "",
    code_snippet: str = "",
    cwe: list[str] | None = None,
    references: list[str] | None = None,
    remediation_hint: str | None = None,
    package: str | None = None,
    fixed_version: str | None = None,
    type_override: str | None = None,
) -> dict:
    typ = type_override or classify_type(f"{rule_id} {title} {description}")
    if package and not file:
        typ = "VULNERABLE_DEPENDENCY"
    return {
        "id": make_id(tool, file or package or "", line or 0, rule_id),
        "tool": tool,
        "language": language,
        "file": file,
        "line": line,
        "end_line": end_line,
        "rule_id": rule_id,
        "type": typ,
        "severity": normalize_severity(severity),
        "confidence": confidence.upper() if confidence else "",
        "title": title,
        "description": description,
        "code_snippet": code_snippet,
        "cwe": cwe or [],
        "references": references or [],
        "remediation_hint": remediation_hint,
        "package": package,
        "fixed_version": fixed_version,
    }


# ---------- Per-scanner parsers -----------------------------------------------------

def _parse_bandit(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for r in data.get("results", []):
        out.append(finding(
            "bandit",
            language="Python",
            file=r.get("filename"),
            line=r.get("line_number"),
            end_line=r.get("line_range", [None])[-1] if r.get("line_range") else None,
            rule_id=r.get("test_id", ""),
            severity=r.get("issue_severity", ""),
            confidence=r.get("issue_confidence", ""),
            title=r.get("test_name", "") or r.get("issue_text", "")[:80],
            description=r.get("issue_text", ""),
            code_snippet=r.get("code", ""),
            cwe=[f"CWE-{r['issue_cwe']['id']}"] if r.get("issue_cwe") else [],
            references=[r.get("more_info")] if r.get("more_info") else [],
        ))
    return out


def _parse_safety(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    # safety has changed formats a few times; handle both.
    items = data if isinstance(data, list) else data.get("vulnerabilities", [])
    out = []
    for v in items:
        out.append(finding(
            "safety",
            language="Python",
            severity=v.get("severity") or "HIGH",
            rule_id=v.get("vulnerability_id") or v.get("cve") or "",
            title=f"Vulnerable Python package: {v.get('package_name', v.get('package', '?'))}",
            description=v.get("advisory") or v.get("description") or "",
            package=v.get("package_name") or v.get("package"),
            fixed_version=", ".join(v.get("fixed_versions") or []) or v.get("fixed_in"),
            references=[v.get("more_info_url")] if v.get("more_info_url") else [],
            type_override="VULNERABLE_DEPENDENCY",
        ))
    return out


def _parse_pip_audit(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []) or dep.get("vulnerabilities", []):
            out.append(finding(
                "pip-audit",
                language="Python",
                severity=v.get("severity") or "HIGH",
                rule_id=v.get("id", ""),
                title=f"Vulnerable Python package: {dep.get('name', '?')}",
                description=v.get("description") or "",
                package=dep.get("name"),
                fixed_version=", ".join(v.get("fix_versions") or []),
                type_override="VULNERABLE_DEPENDENCY",
            ))
    return out


def _parse_semgrep(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for r in data.get("results", []):
        extra = r.get("extra", {}) or {}
        meta = extra.get("metadata", {}) or {}
        out.append(finding(
            "semgrep",
            language=", ".join(meta.get("technology") or []) or "",
            file=r.get("path"),
            line=r.get("start", {}).get("line"),
            end_line=r.get("end", {}).get("line"),
            rule_id=r.get("check_id", ""),
            severity=extra.get("severity", ""),
            title=extra.get("message", "")[:120],
            description=extra.get("message", ""),
            code_snippet=extra.get("lines", ""),
            cwe=meta.get("cwe") or [],
            references=meta.get("references") or [],
        ))
    return out


def _parse_trufflehog(raw: str, root: Path) -> list[dict]:
    # trufflehog outputs JSON-per-line.
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        fs = r.get("SourceMetadata", {}).get("Data", {}).get("Filesystem", {})
        out.append(finding(
            "trufflehog",
            file=fs.get("file"),
            line=fs.get("line"),
            rule_id=r.get("DetectorName", ""),
            severity="CRITICAL",
            title=f"Detected secret: {r.get('DetectorName', '?')}",
            description=f"Verified={r.get('Verified', False)}. Rotate immediately.",
            code_snippet=r.get("Raw", "")[:200],
            type_override="HARDCODED_SECRET",
        ))
    return out


def _parse_eslint(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for f in data:
        for m in f.get("messages", []):
            sev = "HIGH" if m.get("severity") == 2 else "MEDIUM"
            out.append(finding(
                "eslint",
                language="JavaScript",
                file=f.get("filePath"),
                line=m.get("line"),
                end_line=m.get("endLine"),
                rule_id=m.get("ruleId") or "",
                severity=sev,
                title=m.get("message", "")[:120],
                description=m.get("message", ""),
            ))
    return out


def _parse_npm_audit(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for name, v in (data.get("vulnerabilities") or {}).items():
        out.append(finding(
            "npm-audit",
            language="JavaScript",
            severity=v.get("severity", "HIGH"),
            rule_id=str((v.get("via") or [{}])[0].get("source", "")) if v.get("via") else "",
            title=f"Vulnerable npm package: {name}",
            description=(v.get("via") or [{}])[0].get("title", "") if v.get("via") else "",
            package=name,
            fixed_version=str((v.get("fixAvailable") or {}).get("version", "")) or None,
            type_override="VULNERABLE_DEPENDENCY",
        ))
    return out


def _parse_gosec(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for r in data.get("Issues", []):
        out.append(finding(
            "gosec",
            language="Go",
            file=r.get("file"),
            line=int(r.get("line", "0").split("-")[0]) if r.get("line") else None,
            rule_id=r.get("rule_id", ""),
            severity=r.get("severity", ""),
            confidence=r.get("confidence", ""),
            title=r.get("details", "")[:120],
            description=r.get("details", ""),
            code_snippet=r.get("code", ""),
            cwe=[f"CWE-{r['cwe']['ID']}"] if r.get("cwe") else [],
        ))
    return out


def _parse_govulncheck(raw: str, root: Path) -> list[dict]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "osv" not in r:
            continue
        osv = r["osv"]
        out.append(finding(
            "govulncheck",
            language="Go",
            severity="HIGH",
            rule_id=osv.get("id", ""),
            title=osv.get("summary", "")[:120],
            description=osv.get("details", ""),
            package=", ".join(a.get("package", {}).get("name", "")
                              for a in osv.get("affected", [])) or None,
            references=[ref.get("url", "") for ref in osv.get("references", []) or []],
            type_override="VULNERABLE_DEPENDENCY",
        ))
    return out


def _parse_brakeman(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for w in data.get("warnings", []):
        out.append(finding(
            "brakeman",
            language="Ruby",
            file=w.get("file"),
            line=w.get("line"),
            rule_id=w.get("warning_code", ""),
            severity="HIGH",
            confidence=w.get("confidence", ""),
            title=w.get("warning_type", ""),
            description=w.get("message", ""),
            code_snippet=w.get("code", ""),
        ))
    return out


def _parse_bundler_audit(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for r in (data.get("results") or data if isinstance(data, list) else []):
        adv = r.get("advisory", {})
        out.append(finding(
            "bundler-audit",
            language="Ruby",
            severity=adv.get("criticality") or "HIGH",
            rule_id=adv.get("id", "") or adv.get("cve", ""),
            title=adv.get("title", "")[:120],
            description=adv.get("description", ""),
            package=r.get("gem", {}).get("name"),
            fixed_version=", ".join(adv.get("patched_versions") or []),
            type_override="VULNERABLE_DEPENDENCY",
        ))
    return out


def _parse_phpstan(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for path, info in (data.get("files") or {}).items():
        for m in info.get("messages", []):
            out.append(finding(
                "phpstan",
                language="PHP",
                file=path,
                line=m.get("line"),
                rule_id=m.get("identifier", "") or "",
                severity="MEDIUM",
                title=m.get("message", "")[:120],
                description=m.get("message", ""),
            ))
    return out


def _parse_flawfinder(raw: str, root: Path) -> list[dict]:
    # --dataonly --singleline --columns format: file:line:column: [level] (cat) name: message
    out = []
    for line in raw.splitlines():
        if ": [" not in line:
            continue
        try:
            loc, rest = line.split(": [", 1)
            level, rest = rest.split("]", 1)
            file_part, line_part = loc.rsplit(":", 2)[:2] if loc.count(":") >= 2 else (loc, "0")
            out.append(finding(
                "flawfinder",
                language="C/C++",
                file=file_part,
                line=int(line_part) if line_part.isdigit() else None,
                rule_id=level.strip(),
                severity={"5": "CRITICAL", "4": "HIGH", "3": "MEDIUM",
                          "2": "LOW", "1": "LOW", "0": "LOW"}.get(level.strip(), "MEDIUM"),
                title=rest.strip()[:120],
                description=rest.strip(),
            ))
        except Exception:
            continue
    return out


def _parse_cppcheck(raw: str, root: Path) -> list[dict]:
    out = []
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for err in tree.iter("error"):
        loc = err.find("location")
        out.append(finding(
            "cppcheck",
            language="C/C++",
            file=loc.get("file") if loc is not None else None,
            line=int(loc.get("line", 0)) if loc is not None else None,
            rule_id=err.get("id", ""),
            severity=err.get("severity", ""),
            title=err.get("msg", "")[:120],
            description=err.get("verbose", "") or err.get("msg", ""),
        ))
    return out


def _parse_cargo_audit(raw: str, root: Path) -> list[dict]:
    data = json.loads(raw)
    out = []
    for v in (data.get("vulnerabilities", {}) or {}).get("list", []):
        adv = v.get("advisory", {})
        out.append(finding(
            "cargo-audit",
            language="Rust",
            severity="HIGH",
            rule_id=adv.get("id", ""),
            title=adv.get("title", "")[:120],
            description=adv.get("description", ""),
            package=adv.get("package"),
            fixed_version=", ".join(v.get("versions", {}).get("patched") or []),
            type_override="VULNERABLE_DEPENDENCY",
        ))
    return out


def _parse_shellcheck(raw: str, root: Path) -> list[dict]:
    # shellcheck -f json1 emits JSON-per-line.
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            for r in json.loads(line).get("comments", []):
                out.append(finding(
                    "shellcheck",
                    language="Shell",
                    file=r.get("file"),
                    line=r.get("line"),
                    rule_id=f"SC{r.get('code', '')}",
                    severity=r.get("level", ""),
                    title=r.get("message", "")[:120],
                    description=r.get("message", ""),
                ))
        except json.JSONDecodeError:
            continue
    return out


def _parse_spotbugs(raw: str, root: Path) -> list[dict]:
    out = []
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for bug in tree.iter("BugInstance"):
        sl = bug.find("SourceLine")
        out.append(finding(
            "spotbugs",
            language="Java",
            file=sl.get("sourcepath") if sl is not None else None,
            line=int(sl.get("start", 0)) if sl is not None else None,
            rule_id=bug.get("type", ""),
            severity={"1": "HIGH", "2": "MEDIUM", "3": "LOW"}.get(
                bug.get("priority", "2"), "MEDIUM"
            ),
            title=(bug.findtext("ShortMessage") or "")[:120],
            description=bug.findtext("LongMessage") or "",
        ))
    return out


PARSERS: dict[str, Callable[[str, Path], list[dict]]] = {
    "bandit": _parse_bandit,
    "safety": _parse_safety,
    "pip-audit": _parse_pip_audit,
    "semgrep": _parse_semgrep,
    "trufflehog": _parse_trufflehog,
    "eslint": _parse_eslint,
    "npm-audit": _parse_npm_audit,
    "gosec": _parse_gosec,
    "govulncheck": _parse_govulncheck,
    "brakeman": _parse_brakeman,
    "bundler-audit": _parse_bundler_audit,
    "phpstan": _parse_phpstan,
    "flawfinder": _parse_flawfinder,
    "cppcheck": _parse_cppcheck,
    "cargo-audit": _parse_cargo_audit,
    "shellcheck": _parse_shellcheck,
    "spotbugs": _parse_spotbugs,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--workspace", required=True, type=Path)
    args = p.parse_args(argv)

    raw_dir = args.workspace / "raw"
    if not raw_dir.is_dir():
        sys.stderr.write(f"[parse] no raw/ directory at {raw_dir}\n")
        return 1

    all_findings: list[dict] = []
    for raw_path in sorted(raw_dir.iterdir()):
        scanner_name = raw_path.stem  # e.g. "bandit.json" → "bandit"
        parser = PARSERS.get(scanner_name)
        if not parser:
            sys.stderr.write(f"[parse] no parser for {scanner_name}, skipping\n")
            continue
        try:
            text = raw_path.read_text(encoding="utf-8", errors="ignore")
            if not text.strip():
                continue
            findings = parser(text, args.workspace)
            all_findings.extend(findings)
            print(f"[parse] {scanner_name}: {len(findings)} findings")
        except Exception as e:
            sys.stderr.write(f"[parse] {scanner_name} parser failed: {e}\n")

    # De-duplicate on id.
    seen: dict[str, dict] = {}
    for f in all_findings:
        seen.setdefault(f["id"], f)
    deduped = list(seen.values())

    out_path = args.workspace / "findings.json"
    out_path.write_text(json.dumps(deduped, indent=2), encoding="utf-8")
    print(f"[parse] wrote {len(deduped)} unique findings to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
