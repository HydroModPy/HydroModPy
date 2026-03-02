# -*- coding: utf-8 -*-
"""
* Copyright (C) 2023-2025 Alexandre Gauvain, Ronan Abhervé, Jean-Raynald de Dreuzy
*
* This program and the accompanying materials are made available under the
* terms of the Eclipse Public License 2.0 which is available at
* http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
* which is available at https://www.apache.org/licenses/LICENSE-2.0.
*
* SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
"""

"""Per-timestep post-processing computations for MODFLOW-NWT outputs."""

import numpy as np
import flopy.utils.postprocessing as pp

#: Sentinel value used for inactive / out-of-domain cells.
NODATA: int = -9999


# ---------------------------------------------------------------------------
# Water table
# ---------------------------------------------------------------------------


def compute_watertable_elevation(head: np.ndarray, nlay: int) -> np.ndarray:
    """
    Extract the water table elevation from the 3-D head array.

    For a single-layer model, returns the top-layer head directly.
    For multi-layer models, uses FloPy's ``get_water_table`` helper with
    ``nodata=-100`` to identify the uppermost saturated layer.

    Parameters
    ----------
    head : np.ndarray
        Shape ``(nlay, nrow, ncol)`` head array from FloPy ``HeadFile``.
    nlay : int
        Number of model layers.

    Returns
    -------
    np.ndarray
        Shape ``(nrow, ncol)`` water table elevation array.
    """
    if nlay == 1:
        return head[0].copy()
    return pp.get_water_table(head, -100)


def compute_watertable_depth(
    wt_elev: np.ndarray,
    dem: np.ndarray,
    dem_mask: np.ndarray,
) -> np.ndarray:
    """
    Compute the depth to the water table (DEM − water table elevation).

    Parameters
    ----------
    wt_elev : np.ndarray
        Water table elevation array, shape ``(nrow, ncol)``.
    dem : np.ndarray
        Digital elevation model array, shape ``(nrow, ncol)``.
    dem_mask : np.ndarray
        Boolean mask of inactive/nodata DEM cells (``True`` = nodata).

    Returns
    -------
    np.ndarray
        Depth-to-water-table array; nodata cells are set to ``NODATA``.
    """
    wt_depth = dem - wt_elev.copy()
    wt_depth[dem_mask] = NODATA
    return wt_depth


# ---------------------------------------------------------------------------
# Seepage areas
# ---------------------------------------------------------------------------


def compute_seepage_areas(
    wt_elev: np.ndarray,
    dem: np.ndarray,
    dem_mask: np.ndarray,
) -> np.ndarray:
    """
    Identify seepage areas where the water table is at or above the DEM.

    Returns a binary array: ``1`` where DEM − water table < 0 (seepage),
    ``0`` elsewhere, and ``NODATA`` for inactive cells.

    Parameters
    ----------
    wt_elev : np.ndarray
        Water table elevation, shape ``(nrow, ncol)``.
    dem : np.ndarray
        Digital elevation model, shape ``(nrow, ncol)``.
    dem_mask : np.ndarray
        Boolean nodata mask (``True`` = nodata cell).

    Returns
    -------
    np.ndarray
        Binary seepage area array.
    """
    seep_area = dem - wt_elev.copy()
    seep_area[seep_area >= 0] = 0
    seep_area[seep_area < 0] = 1
    seep_area[dem_mask] = NODATA
    return seep_area


# ---------------------------------------------------------------------------
# Drain outflow (vectorised — replaces double for-loop)
# ---------------------------------------------------------------------------


def compute_outflow_drain(
    drain_data: list,
    drain_array: np.ndarray,
    nrow: int,
    ncol: int,
    dem_mask: np.ndarray,
) -> np.ndarray:
    """
    Map drain-package outflow onto the 2-D model grid (vectorised).

    The FloPy ``CellBudgetFile`` returns drain records ordered the same way
    as the active drain cells in ``drain_array``.  This function uses
    ``np.where`` instead of a double Python for-loop to fill the grid.

    Parameters
    ----------
    drain_data : list
        Output of ``cbb.get_data(text="DRAINS", ...)``.  ``drain_data[0]``
        must be the list/array of per-drain records, each with the outflow
        flux at index ``[1]``.
    drain_array : np.ndarray
        Binary mask of shape ``(nrow, ncol)``; ``1`` where a drain cell is
        active.
    nrow, ncol : int
        Grid dimensions.
    dem_mask : np.ndarray
        Boolean nodata mask (``True`` = nodata cell).

    Returns
    -------
    np.ndarray
        Shape ``(nrow, ncol)`` drain outflow array; nodata cells set to
        ``NODATA``.
    """
    out = np.zeros((nrow, ncol))
    rows, cols = np.where(drain_array == 1)
    fluxes = np.abs([rec[1] for rec in drain_data[0]])
    out[rows, cols] = fluxes
    out[dem_mask] = NODATA
    return out


# ---------------------------------------------------------------------------
# Groundwater flux
# ---------------------------------------------------------------------------


def compute_groundwater_flux(
    cbb,
    kstpkper: tuple,
    time: float,
    nlay: int,
    dem_mask: np.ndarray,
) -> np.ndarray:
    """
    Compute the groundwater flux magnitude at the top layer.

    For a single-layer model: ``|q| = sqrt(frf² + fff²)``.
    For multi-layer models a lower-face component is added:
    ``|q| = sqrt(frf² + fff² + flf²)``.

    Parameters
    ----------
    cbb : flopy.utils.binaryfile.CellBudgetFile
        Open cell-budget binary file.
    kstpkper : tuple
        ``(kstp, kper)`` stress-period identifier.
    time : float
        Simulation time for the target output step.
    nlay : int
        Number of model layers.
    dem_mask : np.ndarray
        Boolean nodata mask (``True`` = nodata cell).

    Returns
    -------
    np.ndarray
        Shape ``(nrow, ncol)`` flux magnitude array at the top layer; nodata
        cells set to ``NODATA``.
    """
    frf = cbb.get_data(text="FLOW RIGHT FACE", kstpkper=kstpkper, totim=time)[0]
    fff = cbb.get_data(text="FLOW FRONT FACE", kstpkper=kstpkper, totim=time)[0]

    if nlay == 1:
        flux = np.sqrt(frf**2 + fff**2)
    else:
        flf = cbb.get_data(text="FLOW LOWER FACE", kstpkper=kstpkper, totim=time)[0]
        flux = np.sqrt(frf**2 + fff**2 + flf**2)

    flux_top = flux[0].copy()
    flux_top[dem_mask] = NODATA
    return flux_top


# ---------------------------------------------------------------------------
# Groundwater storage
# ---------------------------------------------------------------------------


def compute_groundwater_storage(
    wt_elev: np.ndarray,
    zbot: np.ndarray,
    sy: np.ndarray,
    dem: np.ndarray,
    resolution: float,
) -> np.ndarray:
    """
    Estimate volumetric groundwater storage per cell.

    Storage = (water-table elevation − bottom of aquifer) × cell area × mean Sy.
    Cells where the DEM is below sea level (``dem < 0``) are excluded.

    Parameters
    ----------
    wt_elev : np.ndarray
        Water table elevation, shape ``(nrow, ncol)``.
    zbot : np.ndarray
        Bottom elevations array; ``zbot[-1]`` is the deepest layer bottom.
    sy : np.ndarray
        Specific yield array (``nlay, nrow, ncol``).
    dem : np.ndarray
        Digital elevation model, shape ``(nrow, ncol)``.
    resolution : float
        Cell size [m]; cell area = ``resolution²``.

    Returns
    -------
    np.ndarray
        Volumetric groundwater storage per cell [m³].
    """
    wt_sto = wt_elev.copy()
    wt_sto[dem < 0] = np.nan
    wt_sto = (wt_sto - zbot[-1]) * (resolution**2) * np.nanmean(sy)
    return wt_sto
