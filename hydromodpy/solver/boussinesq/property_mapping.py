"""Hydraulic-property mapping helpers for the planar Boussinesq backend.

This module mirrors the role played by the MODFLOW property-mapping helpers,
but targets one 2D Gmsh planar mesh instead of a structured grid. The current
contract intentionally stays narrow:

- ``K`` maps to per-cell hydraulic conductivity,
- ``Sy`` maps to the per-cell storage term used by Boussinesq V1.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.physics.flow.regime import normalize_flow_regime
from hydromodpy.solver.field_property_mapping import (
    coerce_spatial_support_field as _coerce_spatial_support_field,
)
from hydromodpy.solver.field_property_mapping import (
    resolve_field_param as _resolve_field_param,
)
from hydromodpy.solver.field_property_mapping import (
    resolve_spatial_support_from_domain as _resolve_spatial_support_from_domain,
)

logger = get_logger(__name__)
_DEFAULT_CELL_SAMPLES_PER_AXIS = 8


def resolve_required_flow_properties(*, flow_regime: str) -> frozenset[str]:
    """Return the minimal hydraulic-property set required by Boussinesq."""
    try:
        regime = normalize_flow_regime(flow_regime)
    except ValueError:
        return frozenset({"K", "Sy"})
    if regime == "steady":
        return frozenset({"K"})
    return frozenset({"K", "Sy"})


def _resolve_field_discretization(
    *,
    support_field: object,
    solver_mesh,
    geometry_cache: dict[tuple[int, int], object],
) -> object:
    """Reuse one support-on-mesh discretization across multiple properties."""
    cell_samples_per_axis = int(
        getattr(
            support_field,
            "default_cell_samples_per_axis",
            _DEFAULT_CELL_SAMPLES_PER_AXIS,
        )
        or _DEFAULT_CELL_SAMPLES_PER_AXIS
    )
    cache_key = (id(support_field), cell_samples_per_axis)
    cached = geometry_cache.get(cache_key)
    if cached is not None:
        return cached
    discretized = support_field.on_mesh(
        solver_mesh,
        cell_samples_per_axis=cell_samples_per_axis,
    )
    geometry_cache[cache_key] = discretized
    return discretized


def _build_property_from_flow_domain(
    *,
    flow: object,
    domain: object,
    solver_mesh,
    geometry_cache: dict[tuple[int, int], object],
    flow_param_candidates: tuple[str, ...],
    target_attr: str,
    property_label: str,
) -> np.ndarray:
    """Map one Flow parameter to one per-cell property array on a planar mesh."""
    selected_name, param_obj = _resolve_field_param(
        flow=flow,
        aliases=flow_param_candidates,
        property_label=property_label,
    )

    if getattr(param_obj, "is_heterogeneous", False):
        if domain is None:
            raise ValueError(
                f"Cannot map {property_label}: missing domain for heterogeneous parameter"
            )
        required_field_id = str(getattr(param_obj, "field_spatial_id", "")).strip()
        support_field = _coerce_spatial_support_field(
            _resolve_spatial_support_from_domain(
                domain=domain,
                support_id=required_field_id,
            ),
            support_id=required_field_id,
        )
        field_discretization = _resolve_field_discretization(
            support_field=support_field,
            solver_mesh=solver_mesh,
            geometry_cache=geometry_cache,
        )
        mesh_values = param_obj.to_mesh_field(
            field_discretization,
            label=target_attr,
            depth=0.0,
        )
        support_label = f"domain support '{required_field_id}'"
    else:
        mesh_values = param_obj.to_mesh_field(
            mesh=solver_mesh,
            label=target_attr,
            depth=0.0,
        )
        support_label = "direct homogeneous mapping"

    values = np.asarray(solver_mesh.to_cell_values(mesh_values.cell_values), dtype=float)
    logger.debug(
        "%s mapped from flow.%s using %s",
        property_label,
        selected_name,
        support_label,
    )
    return values.copy()


def resolve_flow_property_arrays(
    *,
    flow: object,
    domain: object,
    solver_mesh,
    required_properties: frozenset[str] | set[str] | None = None,
) -> dict[str, np.ndarray]:
    """Resolve canonical Boussinesq property arrays on one planar mesh."""
    mapping_specs = [
        ("K", ("K", "k"), "hydraulic_conductivity_m_s", "Hydraulic conductivity"),
        ("Sy", ("Sy", "SY", "sy", "S", "s"), "storage_coefficient", "Specific yield"),
    ]

    required = (
        {str(name).strip() for name in required_properties}
        if required_properties is not None
        else {"K", "Sy"}
    )
    geometry_cache: dict[tuple[int, int], object] = {}
    out: dict[str, np.ndarray] = {}

    for canonical_name, aliases, target_attr, label in mapping_specs:
        if canonical_name not in required:
            continue
        out[target_attr] = _build_property_from_flow_domain(
            flow=flow,
            domain=domain,
            solver_mesh=solver_mesh,
            geometry_cache=geometry_cache,
            flow_param_candidates=aliases,
            target_attr=target_attr,
            property_label=label,
        )
    return out


__all__ = [
    "resolve_flow_property_arrays",
    "resolve_required_flow_properties",
]
