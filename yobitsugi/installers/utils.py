"""Shared helpers for installers."""
from __future__ import annotations

from pathlib import Path


PKG_ROOT = Path(__file__).resolve().parent.parent


def load_template(name: str) -> str:
    """Load a markdown template from yobitsugi/templates/."""
    path = PKG_ROOT / "templates" / name
    return path.read_text()
