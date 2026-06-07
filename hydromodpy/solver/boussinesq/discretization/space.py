"""Space-discretization descriptors used by the Boussinesq solver."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpaceSchemeSpec:
    """Descriptor for one spatial discretization family."""

    id: str
    mesh_support: str
    unknown_support: str
    flux_family: str
    description: str


FV_TRI_CELL_CENTERED = SpaceSchemeSpec(
    id="fv_tri_cell_centered",
    mesh_support="triangular_planar_mesh",
    unknown_support="cell_centers",
    flux_family="two_point_flux_with_edge_transmissivity",
    description=(
        "Finite-volume balance on triangular cells with cell-centered hydraulic "
        "head unknowns and edge-based transmissive fluxes."
    ),
)


__all__ = ["FV_TRI_CELL_CENTERED", "SpaceSchemeSpec"]
