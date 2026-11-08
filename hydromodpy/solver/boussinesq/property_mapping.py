"""Hydraulic properties of the planar Boussinesq backend.

Boussinesq reads ``K`` as the per-cell hydraulic conductivity and ``Sy`` as the
per-cell storage coefficient, both at depth zero: the backend has one layer.
They come from the mapping every solver shares
(``model.properties.property_table.map_flow_properties``), applied to the
``profiles`` of the ``Model``. An override of K or Sy set by
``Model.with_properties`` wins over the profile, as it does on MODFLOW. An override of a property Boussinesq does not read (Kv, Ss, K22,
the angles of the K tensor) is refused by name rather than dropped.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.properties.property_table import (
    map_flow_properties,
    resolve_flow_property_runtime_overrides,
)

_OUTPUT_NAMES = {"K": "hydraulic_conductivity_m_s", "Sy": "storage_coefficient"}
_MAPPED_NAMES = {"K": "hk_value", "Sy": "sy_value"}


def resolve_flow_property_arrays(
    *,
    profiles: Mapping[str, object],
    domain: object,
    cell_mesh: PlanarCellMesh,
    required_properties: frozenset[str] | set[str] | None = None,
    runtime_property_overrides: Mapping[str, object] | None = None,
) -> dict[str, np.ndarray]:
    """Map the required Boussinesq properties onto ``cell_mesh``, one value per cell.

    ``runtime_property_overrides`` is ``Model.properties.overrides``: its K and Sy
    win over the profiles, and a property the backend does not read is refused
    (``map_flow_properties``).
    """
    required = (
        frozenset(str(name).strip() for name in required_properties)
        if required_properties is not None
        else frozenset({"K", "Sy"})
    )
    properties = tuple(name for name in ("K", "Sy") if name in required)
    mapped = map_flow_properties(
        profiles=profiles,
        domain=domain,
        cell_mesh=cell_mesh,
        layer_depths=np.zeros((1, cell_mesh.n_cells), dtype=float),
        properties=properties,
        required=required,
        runtime_overrides=resolve_flow_property_runtime_overrides(
            runtime_property_overrides,
            nlay=1,
            n_cells=int(cell_mesh.n_cells),
            required_properties=required,
        ),
    )
    return {_OUTPUT_NAMES[name]: mapped[_MAPPED_NAMES[name]] for name in properties}


__all__ = [
    "resolve_flow_property_arrays",
]
