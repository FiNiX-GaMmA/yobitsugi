# Parser Recipes

Every parser maps a scanner's idiosyncratic output to the unified Finding schema
documented in `SKILL.md`. The schema is fixed; the parser is whatever shape the tool
hands you.

## Anatomy of a parser

A parser is a plain function:

```python
def _parse_<scanner_name>(raw: str, root: Path) -> list[dict]:
    # parse `raw` however you like
    # return a list of Finding dicts produced via the `finding(...)` helper
```

After writing it, register the function in the `PARSERS` dict at the bottom of
`parse_reports.py`. Use the same key you used in `scanners.yaml` as the scanner name —
that's how `parse_reports.py` maps a raw file (`raw/<scanner>.json`) to its parser.

## The `finding()` helper

Use it for every record. It:
- generates a stable `id` (sha1 over tool + file + line + rule)
- normalizes severity (HIGH/MEDIUM/LOW/CRITICAL/UNKNOWN)
- infers a `type` from the title/description via TYPE_HINTS
- fills in unset optional fields with sensible defaults

Don't construct Finding dicts by hand unless you need to override the inferred type
(use the `type_override=` parameter for that).

## Field tips

| Field            | What goes here                                                          |
|------------------|-------------------------------------------------------------------------|
| `file`           | Relative or absolute path; whatever the scanner gave you                |
| `line`           | int; 1-based                                                            |
| `end_line`       | int or None; only set if the finding spans multiple lines               |
| `rule_id`        | The scanner's stable rule key (e.g. `B608`, `CWE-89`, `S5147`)          |
| `severity`       | Raw string; the helper normalizes it                                    |
| `title`          | One-line headline (~120 chars)                                           |
| `description`    | Full text — can be many lines                                            |
| `code_snippet`   | Lines around the finding (untrusted; downstream wraps it)               |
| `package`        | Only set for dependency findings; leaves file/line null                 |
| `fixed_version`  | String describing the patched version(s)                                |
| `type_override`  | Pass this to bypass the heuristic classifier                            |

## Parsing JSON-per-line outputs

Several tools (trufflehog, govulncheck, shellcheck -f json1) emit JSON-lines, not a
single document. Use the existing examples in `parse_reports.py` as a template:

```python
def _parse_jsonl_tool(raw: str, root: Path) -> list[dict]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        # ... map fields, call finding(...)
        out.append(finding(...))
    return out
```

## Parsing text output

For tools without a structured format (flawfinder default, cppcheck text mode), use
regex carefully — anchor your patterns, handle blank lines, and skip headers:

```python
def _parse_text_tool(raw: str, root: Path) -> list[dict]:
    out = []
    for line in raw.splitlines():
        m = re.match(r"^(?P<file>.+?):(?P<line>\d+):\s*\[(?P<level>\d)\]\s*(?P<msg>.+)$", line)
        if not m:
            continue
        out.append(finding(
            "<tool>",
            file=m["file"], line=int(m["line"]),
            rule_id=m["level"], title=m["msg"][:120], description=m["msg"],
        ))
    return out
```

When in doubt, prefer requesting a structured output format from the tool (most modern
scanners support `--format json`).

## Worked example: adding a new tool `mytool`

1. Add to `references/scanners.yaml`:

   ```yaml
   Python:
     - name: mytool
       binary: mytool
       command: 'mytool {root} --json > {out} || true'
       output: inline_stdout
   ```

2. Add a parser in `scripts/parse_reports.py`:

   ```python
   def _parse_mytool(raw: str, root: Path) -> list[dict]:
       data = json.loads(raw)
       return [
           finding(
               "mytool",
               language="Python",
               file=item["path"],
               line=item["lineno"],
               rule_id=item["check"],
               severity=item["severity"],
               title=item["headline"],
               description=item["explanation"],
           )
           for item in data.get("issues", [])
       ]
   ```

3. Register it:

   ```python
   PARSERS = {
       # ...
       "mytool": _parse_mytool,
   }
   ```

4. Run `run_scanners.py` then `parse_reports.py` — `mytool.json` will appear in
   `workspace/raw/` and its findings in `workspace/findings.json` alongside everything
   else. Downstream workers don't need changes.
