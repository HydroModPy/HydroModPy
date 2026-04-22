"""``python -m hydromodpy`` entry point.

The CLI implementation lives in :mod:`hydromodpy._cli`. This module only
forwards execution so that both ``hmp`` / ``hydromodpy`` scripts and
``python -m hydromodpy`` share the same dispatcher.
"""

from __future__ import annotations

from hydromodpy._cli import main

__all__ = ("main",)


if __name__ == "__main__":
    main()
