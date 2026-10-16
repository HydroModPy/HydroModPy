"""Readings across sealed runs.

:mod:`hydromodpy.analysis.comparison` compares N sealed runs of one case: it
reads their directories, extracts the observables, computes the differences,
the stability checks and the budget closure, and draws the maps and series.
``hmp report compare`` renders the page on top of it, from
:mod:`hydromodpy.reporting.comparison`.
"""

from __future__ import annotations

import importlib
from typing import Any

_SUBMODULES = {
    "comparison": "hydromodpy.analysis.comparison",
}


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        module = importlib.import_module(_SUBMODULES[name])
        globals()[name] = module
        return module
    raise AttributeError(f"module 'hydromodpy.analysis' has no attribute {name!r}")


__all__ = list(_SUBMODULES)
