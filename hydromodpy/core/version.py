"""Canonical source of the HydroModPy version string.

The runtime resolves ``__version__`` in this order:

1. ``importlib.metadata.version("hydromodpy")`` - the authoritative answer
   once the package is installed (wheel / editable install).
2. ``pyproject.toml`` parsed with :mod:`tomllib` - used when HydroModPy is
   imported straight from a source checkout before ``pip install -e .``.
3. A hard-coded development fallback, kept in sync with ``pyproject.toml``.

Keeping the logic here (rather than inline in ``hydromodpy/__init__.py``)
lets tooling and documentation import it without triggering the package's
heavier bootstrap side effects.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

_FALLBACK_VERSION = "0.5.0.dev0"


def _read_version() -> str:
    try:
        return metadata.version("hydromodpy")
    except metadata.PackageNotFoundError:
        try:
            import tomllib
        except ModuleNotFoundError:  # Python < 3.11
            return _FALLBACK_VERSION

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if not pyproject.exists():
            return _FALLBACK_VERSION
        try:
            with pyproject.open("rb") as fh:
                return tomllib.load(fh)["project"]["version"]
        except (KeyError, OSError):
            return _FALLBACK_VERSION


__version__ = _read_version()

__all__ = ["__version__"]
