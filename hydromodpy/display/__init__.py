"""Solver-agnostic figure rendering for HydroModPy simulations.

A figure is a request (``request.py``) that ``render.py`` draws from a
:class:`~hydromodpy.results.run.view.Run` and ``output.py`` writes. It never
touches a solver, a project state or raw output files, so it renders MODFLOW-NWT,
MODFLOW 6 and Boussinesq results identically.
"""
