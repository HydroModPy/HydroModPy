"""Canonical source of the HydroModPy version string.

The runtime resolves ``__version__`` in this order:

1. ``pyproject.toml`` of the source checkout the package is imported from,
   parsed with :mod:`tomllib`. An editable install writes its metadata once,
   at ``pip install -e .``, and keeps the old number after every later bump;
   the checkout's own file is the one that moves with the code.
2. ``importlib.metadata.version("hydromodpy")`` - the answer for a wheel,
   which ships no ``pyproject.toml`` beside the package.
3. A hard-coded development fallback, kept in sync with ``pyproject.toml``.

Keeping the logic here (rather than inline in ``hydromodpy/__init__.py``)
lets tooling and documentation import it without triggering the package's
heavier bootstrap side effects.
"""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

_FALLBACK_VERSION = "2.0.0a2"

_CHECKOUT_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _checkout_version(pyproject: Path) -> str | None:
    """Return the version of a HydroModPy ``pyproject.toml``, or ``None``."""
    if not pyproject.is_file():
        return None
    try:
        with pyproject.open("rb") as fh:
            project = tomllib.load(fh)["project"]
    except (KeyError, OSError, tomllib.TOMLDecodeError):
        return None
    if project.get("name") != "hydromodpy" or "version" not in project:
        return None
    return str(project["version"])


def _read_version(pyproject: Path = _CHECKOUT_PYPROJECT) -> str:
    checkout = _checkout_version(pyproject)
    if checkout is not None:
        return checkout
    try:
        return metadata.version("hydromodpy")
    except metadata.PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _read_version()

__all__ = ["__version__"]
