"""Adapters that bind generic simulation runs to concrete solver APIs.

The single :class:`SolverAdapter` Protocol consumed by the simulation
runner lives in :mod:`hydromodpy.solver.base.protocol`. Adapter classes
are stored in the canonical registry at
:mod:`hydromodpy.solver.base.registry`. Simulation reaches that registry
through :mod:`hydromodpy.simulation._solver_protocol` so it stays free
of any direct ``solver`` import at module-load time.
"""
