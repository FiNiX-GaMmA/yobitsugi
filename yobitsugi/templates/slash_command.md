# /yobitsugi

Scan the current repository for security vulnerabilities and produce LLM-generated fixes.

## What it does

1. Detects which languages are in use (Python, JS/TS, Go, Java, Ruby, PHP, C/C++, Rust, Shell, ...).
2. Runs the appropriate SAST and SCA scanners — `bandit`, `semgrep`, `safety`, `pip-audit`,
   `eslint`, `npm audit`, `gosec`, `govulncheck`, `brakeman`, `bundler-audit`, `phpstan`,
   `flawfinder`, `cppcheck`, `cargo-audit`, `shellcheck`, `spotbugs`, `trufflehog`.
3. Normalises everything into a unified `findings.json`.
4. For each CRITICAL/HIGH finding, asks the model to produce a unified diff fix.
5. Backs up files, applies the patch with `patch -p1` (falling back to `git apply`),
   asks the user before each apply unless `--auto`.
6. Generates a focused regression test per applied fix.
7. Re-runs the scanners and reports `fixed_ids`, `still_present`, `newly_introduced`.

Everything goes to a workspace dir (defaults to `~/.yobitsugi/<repo>-<timestamp>/`).

## Usage

```
/yobitsugi .                                    # scan, then prompt before each fix
/yobitsugi . --auto                             # apply fixes without confirmation
/yobitsugi . --severity CRITICAL                # only CRITICAL findings
/yobitsugi . --skip-tests                       # don't generate regression tests
/yobitsugi scan ./services/api                  # scan-only, no fixes
/yobitsugi findings ~/.yobitsugi/<workspace>   # view existing findings
/yobitsugi rollback ~/.yobitsugi/<workspace>   # undo all applied fixes
```

## Safety

- Refuses to run on a dirty git tree unless `--allow-dirty` is passed.
- Every modified file gets a `.yobitsugi.bak` sibling.
- An `applied.json` rollback log is appended for every patch.
- The model is asked to return only unified diffs — no inline edits or destructive ops.
- Untrusted code snippets are wrapped in `[BEGIN/END UNTRUSTED USER CODE]` markers
  in the prompt to mitigate prompt-injection from comments/strings in scanned files.
- No auto-fix on findings unless `--auto` is explicitly set.

## Notes for the assistant

When the user invokes this command, run `yobitsugi` from the shell with the arguments
they provided. Then summarise the workspace output (`findings.json`, `validation.json`)
in plain English. If the run produced a `validation.json` with `newly_introduced` ≠ [],
flag that prominently — those are vulnerabilities the patches accidentally created.
