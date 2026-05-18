"""Small HTML helpers shared by calibration and analysis report builders."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any


def safe_html(value: Any) -> str:
    """Escape *value* for inclusion in static HTML.

    ``None`` becomes an empty string so missing fields render cleanly.
    """
    return html.escape(str(value if value is not None else ""))


def link_relative(web_dir: Path, path: Path) -> str:
    """Return *path* as a POSIX URL relative to *web_dir*.

    Falls back to ``os.path.relpath`` for paths outside *web_dir* and to a
    string representation for paths the OS refuses to resolve.
    """
    try:
        return Path(path).resolve().relative_to(web_dir.resolve()).as_posix()
    except ValueError:
        try:
            return os.path.relpath(Path(path).resolve(), web_dir.resolve()).replace("\\", "/")
        except OSError:
            return str(path)


__all__ = ["link_relative", "safe_html"]
