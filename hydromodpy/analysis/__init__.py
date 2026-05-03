"""Analysis layer for HydroModPy.

The legacy ``display`` and ``postprocess`` subpackages were removed in P08:

- Figures live in :mod:`hydromodpy.display` (catalog of registered classes).
- Metrics live in :mod:`hydromodpy.core.metrics`.
- Derived fields live in :mod:`hydromodpy.results.derived`.
- The launcher-managed postprocess workflow is now part of the simulation
  pipeline (see :mod:`hydromodpy.workflow.steps`).

The legacy ``calibration`` subpackage was removed in P09 - calibration now
lives at :mod:`hydromodpy.calibration` (Optuna-first, lightweight, TOML-
simplified). Comparison, batch and capability-gallery helpers remain here.
"""

from __future__ import annotations

import importlib
from typing import Any

_SUBMODULES = {
    "comparison": "hydromodpy.analysis.comparison",
    "batch": "hydromodpy.analysis.batch",
    "stream_networks": "hydromodpy.analysis.stream_networks",
}


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        module = importlib.import_module(_SUBMODULES[name])
        globals()[name] = module
        return module
    raise AttributeError(f"module 'hydromodpy.analysis' has no attribute {name!r}")


__all__ = list(_SUBMODULES)
