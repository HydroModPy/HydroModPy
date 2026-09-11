"""Solver-agnostic figure rendering for HydroModPy simulations.

Figures consume the :class:`~hydromodpy.results.run.Run` catalog
interface; they never touch a solver, a project state or raw output files.
The same figure code therefore renders MODFLOW-NWT, MODFLOW 6 and Boussinesq
results identically.

Public API:

    >>> from hydromodpy.display import get, list_figures, names
    >>> "piezometric_map" in names()
    True
    >>> get("piezometric_map").spec.name
    'piezometric_map'
    >>> len(list_figures()) > 0
    True

    Rendering needs a Run backed by a simulation on disk:

    >>> get("piezometric_map").plot(run, save_path="head.png")  # doctest: +SKIP
"""

from __future__ import annotations

from hydromodpy.display.figure import BaseFigure, Figure, FigureSpec
from hydromodpy.display.figure_registry import get, list_figures, names, register

__all__ = [
    "BaseFigure",
    "Figure",
    "FigureSpec",
    "get",
    "list_figures",
    "names",
    "register",
]
