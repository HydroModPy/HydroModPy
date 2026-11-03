"""Readings across sealed runs.

:mod:`hydromodpy.analysis.comparison` compares sealed runs of one site through
the public ``Run`` API, for ``hmp report compare`` and ``hmp.compare``.
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
