# yobitsugi (npm wrapper)

> The npm package is a thin wrapper that delegates to the Python CLI via `uvx` or `pipx run`. The real implementation lives in the [Python package](https://pypi.org/project/yobitsugi/).

## Usage

```
npx yobitsugi install                  # auto-detects assistants and registers /yobitsugi
npx yobitsugi scan ./your-repo
npx yobitsugi . --provider anthropic --model claude-opus-4-7
```

That's it. `npx yobitsugi <args>` is functionally equivalent to `uvx yobitsugi <args>`.

## Requirements

Python **3.11+** and one of:

- [`uv`](https://docs.astral.sh/uv/) (recommended) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [`pipx`](https://pipx.pypa.io/stable/installation/)

The wrapper tries `uvx` first, then `pipx run`, then `uv tool run`. If none are available, it prints install instructions and exits.

## Why a wrapper instead of native JS?

Yobitsugi orchestrates language-specific SAST/SCA tooling (bandit, semgrep, gosec, brakeman, ...). Porting that to JS would mean re-implementing 17 parsers against tools that themselves emit Python-friendly JSON. The Python implementation stays canonical; the JS package is just here so JS-native users don't have to learn `pipx`.

## See also

- [Main project README](https://github.com/FiNiX-GaMmA/yobitsugi)
- [PyPI package](https://pypi.org/project/yobitsugi/)
