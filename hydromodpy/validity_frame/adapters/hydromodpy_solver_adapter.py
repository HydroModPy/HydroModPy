from __future__ import annotations

from typing import Any

from hydromodpy.validity_frame.probes.base import BaseProbe


class HydroModPySolverAdapter(BaseProbe):
    """Adapter that wraps HydroModPy solver-like objects. Imports HydroModPy
    only inside the adapter so the main package remains decoupled.
    """

    def role(self) -> str:
        return "solver"

    @staticmethod
    def collect(source: Any = None) -> dict:
        # Keep behaviour tolerant: try to extract common attributes used
        # by the original SolverProbe implementation.
        if source is None:
            return {}
        solver_name = getattr(source, "solver", None) or getattr(source, "solver_name", None)
        iterations = getattr(source, "iterations", None) or getattr(source, "n_iter", None)
        converged = getattr(source, "converged", None)
        solver_status = getattr(source, "status", None)
        return {
            "solver_name": solver_name,
            "iterations": iterations,
            "converged": converged,
            "solver_status": solver_status,
        }
