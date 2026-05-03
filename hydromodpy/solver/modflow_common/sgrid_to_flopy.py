"""Translate HydroModPy ``StructuredGridSpec`` into a FloPy ``StructuredGrid``.

This module is the solver-side boundary where HydroModPy-native grid POPOs
become FloPy objects consumable by MODFLOW-family backends.
"""

from __future__ import annotations

from flopy.discretization import StructuredGrid

from hydromodpy.spatial.mesh.cartesian_grid.sgrid_generation import StructuredGridSpec


def translate(spec: StructuredGridSpec) -> StructuredGrid:
    """Build a FloPy ``StructuredGrid`` from a ``StructuredGridSpec``."""
    return StructuredGrid(
        delc=spec.delc,
        delr=spec.delr,
        top=spec.top,
        botm=spec.botm,
        xoff=spec.xoff,
        yoff=spec.yoff,
        nlay=spec.nlay,
        nrow=spec.nrow,
        ncol=spec.ncol,
        crs=spec.crs,
    )


__all__ = ["translate"]
