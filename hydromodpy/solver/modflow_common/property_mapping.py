"""Hydraulic properties of a MODFLOW solver mesh (NWT and MODFLOW 6).

``resolve_flow_property_arrays`` maps K, Kv, Sy and Ss onto the cells of the
solver mesh at its layer-centre depths through the one mapping every solver
shares (``solver.field_property_mapping.map_flow_properties``). The arrays are
flat, ``(nlay, n_cells)`` and ``(n_cells,)``: a backend that writes a structured
grid reshapes them.
"""

from collections.abc import Mapping

import numpy as np

from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.solver.field_property_mapping import map_flow_properties
from hydromodpy.solver.modflow_common.runtime_arrays import (
    resolve_flow_property_runtime_overrides,
)

_MODFLOW_PROPERTIES = ("K", "Kv", "Sy", "Ss")


def resolve_required_flow_properties(*, flow_regime: str) -> frozenset[str]:
    """Return the minimal hydraulic-property set required for one flow regime."""
    try:
        regime = normalize_flow_regime(flow_regime)
    except ValueError:
        return frozenset({"K", "Sy", "Ss"})
    if regime == "steady":
        return frozenset({"K"})
    return frozenset({"K", "Sy", "Ss"})


def resolve_flow_property_arrays(
    *,
    flow: object,
    domain: object,
    solver_mesh,
    required_properties: frozenset[str] | set[str] | None = None,
    optional_fill_values: Mapping[str, float] | None = None,
    runtime_property_overrides: Mapping[str, object] | None = None,
) -> dict[str, np.ndarray]:
    """Map K, Kv, Sy and Ss onto ``solver_mesh``, flat per cell.

    Returns ``hk``, ``kv``, ``sy``, ``ss`` as ``(nlay, n_cells)`` and their values
    at depth zero ``hk_value``, ... as ``(n_cells,)``. A runtime override (a
    calibration trial) wins over the flow parameter. ``kv`` is present only when
    the flow declares a vertical conductivity.
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
        properties=_MODFLOW_PROPERTIES,
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


__all__ = ["resolve_flow_property_arrays", "resolve_required_flow_properties"]
