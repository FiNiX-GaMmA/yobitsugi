"""yobitsugi: AI coding assistant skill for finding and fixing repo vulnerabilities."""
from __future__ import annotations

try:
    # _version.py is written by hatch-vcs at build/install time from the latest git tag.
    from yobitsugi._version import __version__
except ImportError:
    # Fallback for direct source-tree use without `pip install -e .`.
    try:
        from importlib.metadata import PackageNotFoundError, version
        __version__ = version("yobitsugi")
    except PackageNotFoundError:
        __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
