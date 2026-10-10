"""Surface-interaction helpers for the Boussinesq assembly.

The regularized partition releases at the land surface a share of the water a
cell receives. The share depends on the depth of the water table below the
land surface, in metres, so that a water table far below the ground keeps all
its water whatever the thickness of the aquifer.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.boussinesq.assembly.inputs import as_cell_vector
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


def partition_release_share(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    regularization_radius: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the released share ``exp(-d / r)`` and its derivative with head.

    ``d`` is the depth of the water table below the land surface, in metres,
    capped by the cell thickness: zero at or above the top, the whole thickness
    in a dry cell. ``r`` is ``regularization_radius``, a depth in metres. The
    derivative is zero at and above the top and below the bottom.
    """
    radius_m = float(regularization_radius)
    if not radius_m > 0.0:
        raise ValueError("regularization_radius must be a strictly positive depth in metres.")
    max_thickness = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    raw_thickness = np.asarray(head_m, dtype=float) - mesh.z_bottom_m
    depth_m = max_thickness - np.clip(raw_thickness, 0.0, max_thickness)
    share = np.exp(-depth_m / radius_m)
    inside = (raw_thickness > 0.0) & (raw_thickness < max_thickness)
    dshare_dh = np.where(inside, share / radius_m, 0.0)
    return share, dshare_dh


def partition_vertical_supply_rate_m_s(
    mesh: BoussinesqMesh,
    *,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return the recharge plus the wells of each cell, per unit area, signed.

    A pumping well is negative. With the lateral inflow, this is the water a
    cell receives besides its storage, its drain and its release.
    """
    recharge = as_cell_vector(recharge_rate_m_s, n_cells=mesh.n_cells, label="recharge_rate_m_s")
    wells = as_cell_vector(well_flux_m3_s, n_cells=mesh.n_cells, label="well_flux_m3_s")
    area = np.asarray(mesh.cell_area_m2, dtype=float)
    well_rate = np.divide(wells, area, out=np.zeros(mesh.n_cells, dtype=float), where=area > 0.0)
    return recharge + well_rate


def regularized_partition_surface_rate_from_balance(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    lateral_flux_residual_m3_s: np.ndarray,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
    prescribed_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return the regularized partition release, in m/s.

    The release is ``exp(-d / r) max(n, 0)``: ``n`` is the lateral inflow per
    unit area plus ``surface_input_rate_m_s`` (recharge and wells, signed), ``d``
    the depth of the water table below the land surface and ``r`` a depth in
    metres. A cell with a prescribed head releases nothing: its constant-head
    flux carries the water it receives.
    """
    share, _ = partition_release_share(
        mesh,
        head_m,
        regularization_radius=regularization_radius,
    )
    surface_input = as_cell_vector(
        surface_input_rate_m_s,
        n_cells=mesh.n_cells,
        label="surface_input_rate_m_s",
    )
    area = np.asarray(mesh.cell_area_m2, dtype=float)
    lateral_inflow_rate = np.divide(
        -np.asarray(lateral_flux_residual_m3_s, dtype=float),
        area,
        out=np.zeros(mesh.n_cells, dtype=float),
        where=area > 0.0,
    )
    release = share * np.maximum(lateral_inflow_rate + surface_input, 0.0)
    if prescribed_mask is not None:
        release[np.asarray(prescribed_mask, dtype=bool)] = 0.0
    return release


def resolve_saturation_excess_rate(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    lateral_flux_residual_m3_s: np.ndarray,
    recharge_rate_m_s: np.ndarray,
    well_flux_m3_s: np.ndarray,
    prescribed_mask: np.ndarray,
    regularization_radius: float,
    saturation_excess_rate_m_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return the saturation-excess rate used by one residual assembly."""
    if saturation_excess_rate_m_s is not None:
        return as_cell_vector(
            saturation_excess_rate_m_s,
            n_cells=mesh.n_cells,
            label="saturation_excess_rate_m_s",
        )
    return regularized_partition_surface_rate_from_balance(
        mesh,
        head_m,
        lateral_flux_residual_m3_s=lateral_flux_residual_m3_s,
        surface_input_rate_m_s=partition_vertical_supply_rate_m_s(
            mesh,
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
        ),
        regularization_radius=float(regularization_radius),
        prescribed_mask=prescribed_mask,
    )


__all__ = [
    "partition_release_share",
    "partition_vertical_supply_rate_m_s",
    "regularized_partition_surface_rate_from_balance",
    "resolve_saturation_excess_rate",
]
