"""Hydraulic properties of a MODFLOW solver mesh (NWT and MODFLOW 6).

``resolve_flow_property_arrays`` maps K, Kv, Sy and Ss onto the cells of the
solver mesh at its layer-center depths through the one mapping every solver
shares (``solver.base.properties.map_flow_properties``). The arrays are
flat, ``(nlay, n_cells)`` and ``(n_cells,)``: a backend that writes a structured
grid reshapes them.
"""

from collections.abc import Mapping

import numpy as np

from hydromodpy.solver.base.properties import (
    map_flow_properties,
    resolve_flow_property_runtime_overrides,
)

MODFLOW_PROPERTIES = ("K", "Kv", "Sy", "Ss")
"""The properties both MODFLOW backends read."""


def resolve_flow_property_arrays(
    *,
    flow: object,
    domain: object,
    solver_mesh,
    required_properties: frozenset[str] | set[str] | None = None,
    optional_fill_values: Mapping[str, float] | None = None,
    runtime_property_overrides: Mapping[str, object] | None = None,
    properties: tuple[str, ...] = MODFLOW_PROPERTIES,
) -> dict[str, np.ndarray]:
    """Map ``properties`` (K, Kv, Sy and Ss by default) onto ``solver_mesh``, flat per cell.

    Returns ``hk``, ``kv``, ``sy``, ``ss`` as ``(nlay, n_cells)`` and their values
    at depth zero ``hk_value``, ... as ``(n_cells,)``. A runtime override (a
    calibration trial) wins over the flow parameter. ``kv`` is present only when
    the flow declares a vertical conductivity, and so are ``k22`` and the angles.
    """
    required = (
        frozenset(str(name).strip() for name in required_properties)
        if required_properties is not None
        else frozenset({"K", "Sy", "Ss"})
    )
    return map_flow_properties(
        flow=flow,
        domain=domain,
        cell_mesh=solver_mesh.cell_mesh,
        layer_depths=solver_mesh.layer_center_depths(),
        properties=properties,
        required=required,
        optional_fill_values=optional_fill_values,
        runtime_overrides=resolve_flow_property_runtime_overrides(
            runtime_property_overrides,
            nlay=solver_mesh.nlay,
            n_cells=solver_mesh.n_cells,
            required_properties=required,
            optional_fill_values=optional_fill_values,
        ),
    )


__all__ = [
    "MODFLOW_PROPERTIES",
    "resolve_flow_property_arrays",
]
