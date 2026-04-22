"""Solver-agnostic figure rendering for HydroModPy simulations.

Figures consume the :class:`~hydromodpy.results.run.Run` catalog
interface; they never touch a solver, a project state or raw output files.
The same figure code therefore renders MODFLOW-NWT, MODFLOW 6 and Boussinesq
results identically.

Public API:

    >>> from hydromodpy.display import get, list_figures
    >>> get("piezometric_map").plot(sim, save_path="head.png")
"""

from __future__ import annotations

# Trigger figure registration on package import.
from hydromodpy.display import figures as _figures  # noqa: F401
from hydromodpy.display.catalog import get, list_figures, names, register
from hydromodpy.display.figure import BaseFigure, Figure, FigureSpec

__all__ = [
    "BaseFigure",
    "Figure",
    "FigureSpec",
    "get",
    "list_figures",
    "names",
    "register",
]
