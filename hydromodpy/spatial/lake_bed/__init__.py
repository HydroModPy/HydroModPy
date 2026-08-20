"""Lake-bed reconstruction from bathymetry, reconciled to the abacus.

Pure ``spatial`` building blocks the MODFLOW 6 build uses to carve a real lake
basin into the grid instead of a flat reservoir:

* :func:`load_surface_from_raster` - read a bathymetry raster into a ``Surface``.
* :func:`cell_bed_from_surface` - conservative (zonal) raster-to-cell bed.
* :func:`reconcile_bed_to_abacus` - area-weighted quantile map onto the abacus.
* :func:`simulate_abacus` - flood a per-cell bed into a stage-volume-area curve.
* :func:`regrade_column_to_bed` - re-grade one mesh column around the bed.
* :func:`reconstruct_lake_bed` - the regrid + reconcile pipeline for one lake.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from hydromodpy.spatial.lake_bed.abacus_sim import simulate_abacus
from hydromodpy.spatial.lake_bed.carve_math import (
    regrade_column_active_top,
    regrade_column_to_bed,
)
from hydromodpy.spatial.lake_bed.raster_io import load_surface_from_raster
from hydromodpy.spatial.lake_bed.reconcile import reconcile_bed_to_abacus
from hydromodpy.spatial.lake_bed.regrid import cell_bed_from_surface
from hydromodpy.spatial.surface import Surface

__all__ = [
    "cell_bed_from_surface",
    "load_surface_from_raster",
    "reconcile_bed_to_abacus",
    "reconstruct_lake_bed",
    "regrade_column_active_top",
    "regrade_column_to_bed",
    "simulate_abacus",
]


def reconstruct_lake_bed(
    *,
    planar_mesh: object,
    surface: Surface,
    cell_ids: Sequence[int],
    area_by_cell: Mapping[int, float],
    abacus_stage: Sequence[float],
    abacus_sarea: Sequence[float],
    reconcile: bool = True,
    min_pixels: int = 1,
) -> tuple[dict[int, float], dict[str, float]]:
    """Regrid the bathymetry onto the lake cells and reconcile it to the abacus.

    Returns ``({cell_id: bed_elevation}, diagnostics)``. When ``reconcile`` is
    False the raw regridded bed is returned (still gap-filled), which is useful
    to inspect the bathymetry before the abacus remap.
    """
    raw_bed = cell_bed_from_surface(
        planar_mesh=planar_mesh,
        surface=surface,
        cell_ids=cell_ids,
        min_pixels=min_pixels,
    )
    if not reconcile:
        return raw_bed, {"n_cells": float(len(raw_bed)), "area_scale": 1.0}
    return reconcile_bed_to_abacus(
        bed_by_cell=raw_bed,
        area_by_cell=area_by_cell,
        abacus_stage=abacus_stage,
        abacus_sarea=abacus_sarea,
    )
