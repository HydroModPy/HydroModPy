"""Residual builders shared by Boussinesq runtimes."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import (
    accumulate_internal_flux_residual,
    boundary_head_edge_flux_from_head,
    drainage_outflow_from_head,
    internal_edge_flux_from_head,
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.assembly.inputs import (
    as_cell_vector,
    finalize_boundary_constrained_residual,
    resolve_boundary_head_inputs,
)
from hydromodpy.solver.boussinesq.assembly.surface import resolve_saturation_excess_rate
from hydromodpy.solver.boussinesq.assembly.types import (
    BoussinesqAssembly,
    _BoussinesqSpatialTerms,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh

_RawResidualBuilder = Callable[[_BoussinesqSpatialTerms], np.ndarray]


def _finalize_assembly(
    mesh: BoussinesqMesh,
    *,
    head_candidate_m: np.ndarray,
    spatial_terms: _BoussinesqSpatialTerms,
    raw_residual_m3_s: np.ndarray,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> BoussinesqAssembly:
    """Apply prescribed-cell constraints and package one assembly object."""
    boundary_inputs = resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_candidate_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    residual, prescribed_head_flux = finalize_boundary_constrained_residual(
        head_m=np.asarray(head_candidate_m, dtype=float),
        raw_residual_m3_s=raw_residual_m3_s,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
    )
    return BoussinesqAssembly(
        head_m=spatial_terms.head_m,
        saturated_thickness_m=spatial_terms.saturated_thickness_m,
        transmissivity_m2_s=spatial_terms.transmissivity_m2_s,
        recharge_rate_m_s=spatial_terms.recharge_rate_m_s,
        well_flux_m3_s=spatial_terms.well_flux_m3_s,
        saturation_excess_rate_m_s=spatial_terms.saturation_excess_rate_m_s,
        internal_edge_flux_m3_s=spatial_terms.internal_edge_flux_m3_s,
        prescribed_head_flux_m3_s=prescribed_head_flux,
        prescribed_head_m_by_cell=boundary_inputs.prescribed_head_m_by_cell,
        boundary_edge_flux_m3_s=spatial_terms.boundary_edge_flux_m3_s,
        drainage_flux_m3_s=spatial_terms.drainage_flux_m3_s,
        residual_m3_s=residual,
    )


def _steady_raw_residual_from_spatial_terms(
    mesh: BoussinesqMesh,
    spatial_terms: _BoussinesqSpatialTerms,
) -> np.ndarray:
    """Return the steady residual before Dirichlet-cell constraint application."""
    return (
        spatial_terms.internal_flux_residual_m3_s
        + spatial_terms.boundary_head_flux_residual_m3_s
        + spatial_terms.drainage_flux_m3_s
        + mesh.cell_area_m2 * spatial_terms.saturation_excess_rate_m_s
        - mesh.cell_area_m2 * spatial_terms.recharge_rate_m_s
        - spatial_terms.well_flux_m3_s
    )


def _transient_raw_residual_from_spatial_terms(
    mesh: BoussinesqMesh,
    spatial_terms: _BoussinesqSpatialTerms,
    head_prev_m: np.ndarray,
    dt_seconds: float,
) -> np.ndarray:
    """Return the transient residual before Dirichlet-cell constraint application."""
    head_prev = np.asarray(head_prev_m, dtype=float)
    temporal_term = (
        mesh.cell_area_m2
        * mesh.storage_coefficient
        * (spatial_terms.head_m - head_prev)
        / float(dt_seconds)
    )
    return (
        temporal_term
        + spatial_terms.internal_flux_residual_m3_s
        + spatial_terms.boundary_head_flux_residual_m3_s
        + spatial_terms.drainage_flux_m3_s
        + mesh.cell_area_m2 * spatial_terms.saturation_excess_rate_m_s
        - mesh.cell_area_m2 * spatial_terms.recharge_rate_m_s
        - spatial_terms.well_flux_m3_s
    )


def _build_steady_raw_residual_callback(
    mesh: BoussinesqMesh,
) -> _RawResidualBuilder:
    """Return the steady raw-residual callback used by the template."""
    return partial(_steady_raw_residual_from_spatial_terms, mesh)


def _build_transient_raw_residual_callback(
    mesh: BoussinesqMesh,
    *,
    head_prev_m: np.ndarray,
    dt_seconds: float,
) -> _RawResidualBuilder:
    """Return the transient raw-residual callback used by the template."""
    if float(dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")
    return partial(
        _transient_raw_residual_from_spatial_terms,
        mesh,
        head_prev_m=np.asarray(head_prev_m, dtype=float),
        dt_seconds=float(dt_seconds),
    )


def assemble_spatial_terms(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    regularization_radius: float,
    saturation_excess_rate_m_s: np.ndarray | float | None = None,
) -> _BoussinesqSpatialTerms:
    """Return the spatial/operator contributions for a candidate head field."""
    boundary_inputs = resolve_boundary_head_inputs(
        mesh,
        head_m=np.asarray(head_m, dtype=float),
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )
    if np.any(np.isfinite(boundary_inputs.boundary_head_m_by_edge)):
        head = boundary_inputs.head_m
        boundary_edge_flux, boundary_head_flux_residual = boundary_head_edge_flux_from_head(
            mesh,
            head,
            boundary_head_m_by_edge=boundary_inputs.boundary_head_m_by_edge,
        )
    else:
        head = boundary_inputs.head_m
        boundary_edge_flux = np.zeros(mesh.n_edges, dtype=float)
        boundary_head_flux_residual = np.zeros(mesh.n_cells, dtype=float)
    saturated_thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = mesh.hydraulic_conductivity_m_s * saturated_thickness
    internal_edge_flux = internal_edge_flux_from_head(mesh, head)
    internal_flux_residual = accumulate_internal_flux_residual(mesh, internal_edge_flux)
    recharge_rate = as_cell_vector(
        recharge_rate_m_s,
        n_cells=mesh.n_cells,
        label="recharge_rate_m_s",
    )
    well_flux = as_cell_vector(
        well_flux_m3_s,
        n_cells=mesh.n_cells,
        label="well_flux_m3_s",
    )
    saturation_excess_rate = resolve_saturation_excess_rate(
        mesh,
        head_m=head,
        lateral_flux_residual_m3_s=(internal_flux_residual + boundary_head_flux_residual),
        recharge_rate_m_s=recharge_rate,
        regularization_radius=float(regularization_radius),
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
    )
    drainage_flux = drainage_outflow_from_head(
        mesh,
        head,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    return _BoussinesqSpatialTerms(
        head_m=head,
        saturated_thickness_m=saturated_thickness,
        transmissivity_m2_s=transmissivity,
        recharge_rate_m_s=recharge_rate,
        well_flux_m3_s=well_flux,
        saturation_excess_rate_m_s=saturation_excess_rate,
        internal_edge_flux_m3_s=internal_edge_flux,
        internal_flux_residual_m3_s=internal_flux_residual,
        boundary_edge_flux_m3_s=boundary_edge_flux,
        boundary_head_flux_residual_m3_s=boundary_head_flux_residual,
        drainage_flux_m3_s=drainage_flux,
    )


def _assemble_residual_template(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    boundary_head_m_by_edge: np.ndarray | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    regularization_radius: float,
    raw_residual_builder: _RawResidualBuilder,
    saturation_excess_rate_m_s: np.ndarray | float | None = None,
) -> BoussinesqAssembly:
    """Assemble one residual by combining shared spatial terms with a callback."""
    candidate_head = np.asarray(head_m, dtype=float)
    spatial_terms = assemble_spatial_terms(
        mesh,
        head_m=candidate_head,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
    )
    raw_residual = raw_residual_builder(spatial_terms)
    return _finalize_assembly(
        mesh,
        head_candidate_m=candidate_head,
        spatial_terms=spatial_terms,
        raw_residual_m3_s=raw_residual,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
    )


def assemble_transient_residual_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble the transient residual for one candidate head field."""
    return _assemble_residual_template(
        mesh,
        head_m=head_m,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
        raw_residual_builder=_build_transient_raw_residual_callback(
            mesh,
            head_prev_m=head_prev_m,
            dt_seconds=float(dt_seconds),
        ),
    )


def assemble_transient_residual_with_saturation_excess_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    saturation_excess_rate_m_s: np.ndarray | float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one transient residual with an externally supplied ``q_ex``."""
    return _assemble_residual_template(
        mesh,
        head_m=head_m,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
        raw_residual_builder=_build_transient_raw_residual_callback(
            mesh,
            head_prev_m=head_prev_m,
            dt_seconds=float(dt_seconds),
        ),
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
    )


def assemble_steady_residual_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble the steady residual for one candidate head field."""
    return _assemble_residual_template(
        mesh,
        head_m=head_m,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
        raw_residual_builder=_build_steady_raw_residual_callback(mesh),
    )


def assemble_steady_residual_with_saturation_excess_generic(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    saturation_excess_rate_m_s: np.ndarray | float,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    boundary_head_m_by_edge: np.ndarray | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> BoussinesqAssembly:
    """Assemble one steady residual with an externally supplied ``q_ex``."""
    return _assemble_residual_template(
        mesh,
        head_m=head_m,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        boundary_head_m_by_edge=boundary_head_m_by_edge,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
        regularization_radius=float(regularization_radius),
        raw_residual_builder=_build_steady_raw_residual_callback(mesh),
        saturation_excess_rate_m_s=saturation_excess_rate_m_s,
    )


__all__ = [
    "assemble_spatial_terms",
    "assemble_steady_residual_generic",
    "assemble_steady_residual_with_saturation_excess_generic",
    "assemble_transient_residual_generic",
    "assemble_transient_residual_with_saturation_excess_generic",
]
