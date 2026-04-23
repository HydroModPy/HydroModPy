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

import flopy.utils.postprocessing as pp
import numpy as np

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
    Compute the depth to the water table (DEM - water table elevation).

    Parameters
    ----------
    wt_elev : np.ndarray
        Water table elevation array, shape ``(nrow, ncol)``.
    top_elevation : np.ndarray
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

    Returns a binary array: ``1`` where DEM - water table < 0 (seepage),
    ``0`` elsewhere, and ``NODATA`` for inactive cells.

    Parameters
    ----------
    wt_elev : np.ndarray
        Water table elevation, shape ``(nrow, ncol)``.
    top_elevation : np.ndarray
        Top elevation array on the solver grid, shape ``(nrow, ncol)``.
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
# Drain outflow (vectorised - replaces double for-loop)
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


def compute_outlet_discharge_east_side_m3_s(
    constant_head_data: list | None,
    *,
    nrow: int,
    ncol: int,
) -> float:
    """
    Sum east-side constant-head outflow from one MODFLOW-NWT budget record.

    Parameters
    ----------
    constant_head_data : list | None
        Output of ``CellBudgetFile.get_data(text="CONSTANT HEAD", ...)``.
        When missing or empty, the returned discharge is ``0.0``.
    nrow, ncol : int
        Structured-grid dimensions used to map MODFLOW node numbers to the
        east boundary cells.

    Returns
    -------
    float
        Total positive outflow [m3/s] leaving the east-side constant-head
        boundary for the requested stress period.
    """
    if not constant_head_data:
        return 0.0

    record = constant_head_data[0]
    if record is None or len(record) == 0:
        return 0.0

    ncpl = int(nrow) * int(ncol)
    discharge_m3_s = 0.0

    if getattr(record, "dtype", None) is not None and record.dtype.names is not None:
        node_field = "node" if "node" in record.dtype.names else record.dtype.names[0]
        q_field = "q" if "q" in record.dtype.names else record.dtype.names[-1]
        iterator = ((int(item[node_field]), float(item[q_field])) for item in record)
    else:
        iterator = ((int(item[0]), float(item[-1])) for item in record)

    for node, q in iterator:
        if node <= 0:
            continue
        cell_index = (int(node) - 1) % ncpl
        col = cell_index % int(ncol)
        if col != int(ncol) - 1:
            continue
        discharge_m3_s += max(-float(q), 0.0)

    return float(discharge_m3_s)


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
    top_elevation: np.ndarray,
    *,
    cell_area: float | None = None,
    resolution: float | None = None,
) -> np.ndarray:
    """
    Estimate volumetric groundwater storage per cell.

    Storage = (water-table elevation - bottom of aquifer) × cell area × mean Sy.
    Cells where the DEM is below sea level (``dem < 0``) are excluded.

    Parameters
    ----------
    wt_elev : np.ndarray
        Water table elevation, shape ``(nrow, ncol)``.
    zbot : np.ndarray
        Bottom elevations array; ``zbot[-1]`` is the deepest layer bottom.
    sy : np.ndarray
        Specific yield array (``nlay, nrow, ncol``).
    top_elevation : np.ndarray
        Top elevation array on the solver grid, shape ``(nrow, ncol)``.
    cell_area : float | None
        Cell size [m]; cell area = ``resolution²``.

    Returns
    -------
    np.ndarray
        Volumetric groundwater storage per cell [m³].
    """
    wt_sto = wt_elev.copy()
    wt_sto[top_elevation < 0] = np.nan
    if cell_area is None:
        if resolution is None:
            raise ValueError("compute_groundwater_storage requires cell_area or resolution")
        cell_area = float(resolution) ** 2
    wt_sto = (wt_sto - zbot[-1]) * float(cell_area) * np.nanmean(sy)
    return wt_sto
