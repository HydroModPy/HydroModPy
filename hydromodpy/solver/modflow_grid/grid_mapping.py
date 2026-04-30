"""HydroMesh → MODFLOW DIS / DISV descriptor shim.

MODFLOW-NWT consumes structured ``DIS`` discretisations; MODFLOW 6
consumes either ``DIS`` (structured) or ``DISV`` (vertex-based).
Both backends use ``SolverMesh`` as HydroModPy's internal unified
representation but historically built the DIS/DISV descriptors on
their own.

This module centralises that mapping as a small, read-only descriptor
that each backend can consume via its FloPy-specific package builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

DiscretizationKind = Literal["dis", "disv"]


@dataclass(frozen=True)
class DisDescriptor:
    """Parameters feeding ``flopy.modflow.ModflowDis`` / ``flopy.mf6.ModflowGwfdis``."""

    nlay: int
    nrow: int
    ncol: int
    delr: np.ndarray  # (ncol,) column widths
    delc: np.ndarray  # (nrow,) row heights
    top: np.ndarray  # (nrow, ncol)
    botm: np.ndarray  # (nlay, nrow, ncol)
    xorigin: float
    yorigin: float

    @property
    def kind(self) -> DiscretizationKind:
        return "dis"


@dataclass(frozen=True)
class DisvDescriptor:
    """Parameters feeding ``flopy.mf6.ModflowGwfdisv``."""

    nlay: int
    ncpl: int  # cells per layer
    nvert: int
    vertices: np.ndarray  # (nvert, 3) [iv, x, y]
    cell2d: list[tuple]  # flopy-style per-cell connectivity
    top: np.ndarray  # (ncpl,)
    botm: np.ndarray  # (nlay, ncpl)

    @property
    def kind(self) -> DiscretizationKind:
        return "disv"


def describe_grid(solver_mesh: SolverMesh) -> DisDescriptor | DisvDescriptor:
    """Produce a ``Dis`` / ``Disv`` descriptor from a ``SolverMesh``.

    The dispatch uses ``solver_mesh.is_structured`` because structured
    meshes always carry ``(nrow, ncol)`` and unstructured meshes expose
    a planar ``Mesh2D`` with vertex coordinates and cell connectivity.
    """
    if solver_mesh.is_structured:
        top = np.asarray(solver_mesh.top, dtype=float).reshape(
            solver_mesh.nrow,
            solver_mesh.ncol,
        )
        botm = np.asarray(solver_mesh.botm, dtype=float).reshape(
            solver_mesh.nlay,
            solver_mesh.nrow,
            solver_mesh.ncol,
        )
        bounds = solver_mesh.planar_mesh.bounds()
        delr, delc = solver_mesh.structured_delr_delc()
        return DisDescriptor(
            nlay=solver_mesh.nlay,
            nrow=solver_mesh.nrow,
            ncol=solver_mesh.ncol,
            delr=delr,
            delc=delc,
            top=top,
            botm=botm,
            xorigin=float(bounds[0]),
            yorigin=float(bounds[1]),
        )

    planar = solver_mesh.planar_mesh
    vertices = np.asarray(
        [[i, float(x), float(y)] for i, (x, y) in enumerate(planar.vertex_coordinates())],
        dtype=float,
    )
    cell2d = list(planar.flopy_cell2d())
    ncpl = int(planar.n_cells)
    top = np.asarray(solver_mesh.top, dtype=float).reshape(ncpl)
    botm = np.asarray(solver_mesh.botm, dtype=float).reshape(
        solver_mesh.nlay,
        ncpl,
    )
    return DisvDescriptor(
        nlay=solver_mesh.nlay,
        ncpl=ncpl,
        nvert=int(vertices.shape[0]),
        vertices=vertices,
        cell2d=cell2d,
        top=top,
        botm=botm,
    )


__all__ = [
    "DisDescriptor",
    "DisvDescriptor",
    "DiscretizationKind",
    "describe_grid",
]
