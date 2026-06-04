"""Shared builders for the FlowToModflowAdapter forcing/BC unit tests.

Co-located non-test module imported via relative import by the split
test_forcing_* files.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


def _build_solver_mesh(nrow=1, ncol=1, nlay=1, dx=1.0, dy=1.0, xoff=0.0, yoff=0.0):
    """Build a minimal structured SolverMesh for adapter tests."""
    top = np.zeros((nrow, ncol), dtype=float)
    botm = np.zeros((nlay, nrow, ncol), dtype=float) - 10.0
    return SolverMesh.from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=top,
        botm=botm,
        dx=dx,
        dy=dy,
        xoff=xoff,
        yoff=yoff,
    )
