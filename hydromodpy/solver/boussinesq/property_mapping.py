"""Hydraulic properties of the planar Boussinesq backend.

Boussinesq reads ``K`` as the per-cell hydraulic conductivity and ``Sy`` as the
per-cell storage coefficient, both at depth zero: the backend has one layer.
They come from the mapping every solver shares
(``solver.field_property_mapping.map_flow_properties``).
"""

from __future__ import annotations

import numpy as np

from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.solver.field_property_mapping import map_flow_properties
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

_OUTPUT_NAMES = {"K": "hydraulic_conductivity_m_s", "Sy": "storage_coefficient"}
_MAPPED_NAMES = {"K": "hk_value", "Sy": "sy_value"}


def resolve_required_flow_properties(*, flow_regime: str) -> frozenset[str]:
    """Return the minimal hydraulic-property set required by Boussinesq."""
    try:
        regime = normalize_flow_regime(flow_regime)
    except ValueError:
        return frozenset({"K", "Sy"})
    if regime == "steady":
        return frozenset({"K"})
    return frozenset({"K", "Sy"})


def resolve_flow_property_arrays(
    *,
    flow: object,
    domain: object,
    cell_mesh: PlanarCellMesh,
    required_properties: frozenset[str] | set[str] | None = None,
) -> dict[str, np.ndarray]:
    """Map the required Boussinesq properties onto ``cell_mesh``, one value per cell."""
    required = (
        frozenset(str(name).strip() for name in required_properties)
        if required_properties is not None
        else frozenset({"K", "Sy"})
    )
    properties = tuple(name for name in ("K", "Sy") if name in required)
    mapped = map_flow_properties(
        flow=flow,
        domain=domain,
        cell_mesh=cell_mesh,
        layer_depths=np.zeros((1, cell_mesh.n_cells), dtype=float),
        properties=properties,
        required=required,
    )
    return {_OUTPUT_NAMES[name]: mapped[_MAPPED_NAMES[name]] for name in properties}


__all__ = [
    "resolve_flow_property_arrays",
    "resolve_required_flow_properties",
]
