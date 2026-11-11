"""Solver-agnostic figure rendering for HydroModPy simulations.

Figures consume the :class:`~hydromodpy.results.run.view.Run` catalog
interface; they never touch a solver, a project state or raw output files.
The same figure code therefore renders MODFLOW-NWT, MODFLOW 6 and Boussinesq
results identically.
"""
