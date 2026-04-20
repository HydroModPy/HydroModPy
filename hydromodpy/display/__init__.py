"""Solver-agnostic figure rendering for HydroModPy simulations.

Figures consume the :class:`~hydromodpy.results.simulation.Simulation` catalog
interface; they never touch a solver, a project state or raw output files.
The same figure code therefore renders MODFLOW-NWT, MODFLOW 6 and Boussinesq
results identically.
"""

from __future__ import annotations

from hydromodpy.display.figure import BaseFigure, Figure, FigureSpec

__all__ = ["BaseFigure", "Figure", "FigureSpec"]
