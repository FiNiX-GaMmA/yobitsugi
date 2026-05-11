"""Isolated installation of scanner binaries into a yobitsugi-managed venv.

Why a separate venv:
    Scanners like semgrep pull in heavy dependency trees. If we `pip install` them into
    the user's main Python env we risk version conflicts; if we `pipx install` we add a
    pipx dependency and global state we don't fully control. Owning our own venv at
    ~/.yobitsugi/tools/venv/ keeps everything sandboxed and easy to wipe.

Only Python scanners (install.method == "pip") are auto-installed. For other runtimes
(npm/go/gem/cargo/system), we print the install hint and let the user (or the assistant
calling us) decide how to bootstrap them.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

TOOLS_DIR = Path.home() / ".yobitsugi" / "tools"
VENV_DIR = TOOLS_DIR / "venv"
MANIFEST_PATH = TOOLS_DIR / "installed.json"


@dataclass
class InstallPlan:
    """What `yobitsugi install-scanners` will do for one scanner."""

    name: str
    method: str          # "pip" | "npm" | "go" | "gem" | "cargo" | "system" | "manual"
    package: str | None  # package identifier for pip/npm/go/cargo
    hint: str | None     # human-readable install command for non-pip methods
    already_installed: bool = False


def tools_bin_path() -> Path:
    """Return the directory the venv's installed CLIs land in."""
    return VENV_DIR / ("Scripts" if os.name == "nt" else "bin")


def venv_python() -> Path:
    """Path to the Python interpreter inside the managed venv."""
    return tools_bin_path() / ("python.exe" if os.name == "nt" else "python")


def venv_exists() -> bool:
    return venv_python().is_file()


def ensure_venv() -> Path:
    """Create the managed venv if it doesn't exist. Returns its bin/Scripts path."""
    if not venv_exists():
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        builder = venv.EnvBuilder(with_pip=True, clear=False, symlinks=os.name != "nt")
        builder.create(str(VENV_DIR))
        # Newly created venvs ship with the bundled pip; bring it up to date so the
        # scanner installs themselves run against a known-good resolver.
        subprocess.run(
            [str(venv_python()), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
            check=False,
        )
    return tools_bin_path()


def load_manifest() -> dict[str, dict]:
    if not MANIFEST_PATH.is_file():
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_manifest(manifest: dict[str, dict]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def install_python_tool(name: str, package: str) -> tuple[bool, str]:
    """`pip install` a single package into the managed venv.

    Returns (success, message). Updates the manifest on success.
    """
    ensure_venv()
    result = subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--upgrade", package],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[-1000:]

    manifest = load_manifest()
    manifest[name] = {"package": package, "method": "pip"}
    save_manifest(manifest)
    return True, f"installed {package} into {VENV_DIR}"


def uninstall_all() -> Path | None:
    """Wipe the managed venv entirely. Returns the path that was removed, or None."""
    if not TOOLS_DIR.exists():
        return None
    shutil.rmtree(TOOLS_DIR)
    return TOOLS_DIR


def build_install_plans(
    registry: dict, missing_binaries: Iterable[str] | None = None
) -> list[InstallPlan]:
    """Walk the scanners registry, return one InstallPlan per scanner.

    If `missing_binaries` is provided, the plan list is filtered to only those whose
    binary is in that set.
    """
    bin_dir = tools_bin_path() if venv_exists() else None
    seen: set[str] = set()
    plans: list[InstallPlan] = []
    for _lang, scanners in registry.items():
        for scanner in scanners:
            name = scanner["name"]
            if name in seen:
                continue
            seen.add(name)
            if missing_binaries is not None and scanner["binary"] not in missing_binaries:
                continue
            install = scanner.get("install") or {}
            method = install.get("method", "manual")
            already = False
            if method == "pip" and bin_dir is not None:
                candidate = bin_dir / scanner["binary"]
                if candidate.exists():
                    already = True
            plans.append(
                InstallPlan(
                    name=name,
                    method=method,
                    package=install.get("package"),
                    hint=install.get("hint"),
                    already_installed=already,
                )
            )
    return plans


def prepend_to_path(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of `env` (or os.environ) with the managed venv bin prepended to PATH."""
    base = dict(env if env is not None else os.environ)
    if venv_exists():
        bin_str = str(tools_bin_path())
        existing = base.get("PATH", "")
        if bin_str not in existing.split(os.pathsep):
            base["PATH"] = bin_str + os.pathsep + existing
    return base


def main(argv: list[str] | None = None) -> int:
    """`python -m yobitsugi.core.tools` — small CLI for debugging the venv state."""
    import argparse

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("show", help="Print venv path and installed tools.")
    sub.add_parser("clean", help="Delete the managed venv and manifest.")
    args = p.parse_args(argv)

    if args.cmd == "clean":
        removed = uninstall_all()
        print(f"removed: {removed}" if removed else "nothing to remove")
        return 0

    # default: show
    print(f"venv:      {VENV_DIR}")
    print(f"exists:    {venv_exists()}")
    print(f"bin dir:   {tools_bin_path()}")
    print(f"manifest:  {MANIFEST_PATH}")
    print("installed:")
    for name, meta in load_manifest().items():
        print(f"  {name:<14}  {meta.get('package', '?')}  ({meta.get('method', '?')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
