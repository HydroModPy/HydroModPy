"""Hydraulic-property mapping helpers for the planar Boussinesq backend.

This module mirrors the role played by the MODFLOW property-mapping helpers,
but targets one 2D Gmsh planar mesh instead of a structured grid. The current
contract intentionally stays narrow:

- ``K`` maps to per-cell hydraulic conductivity,
- ``Sy`` maps to the per-cell storage term used by Boussinesq V1.
"""

from __future__ import annotations

from hydromodpy.core.logging import get_logger
import numpy as np


logger = get_logger(__name__)
_DEFAULT_CELL_SAMPLES_PER_AXIS = 8


def resolve_required_flow_properties(*, flow_regime: str) -> frozenset[str]:
    """Return the minimal hydraulic-property set required by Boussinesq."""
    regime = str(flow_regime).strip().lower()
    if regime == "steady":
        return frozenset({"K"})
    return frozenset({"K", "Sy"})


def _coerce_spatial_support_field(zone_obj, *, support_id: str | None = None):
    """Validate one domain support used for heterogeneous parameter mapping."""
    if zone_obj is None:
        support_label = support_id if support_id is not None else "<unspecified>"
        raise ValueError(
            f"Missing spatial support '{support_label}' in domain for heterogeneous mapping"
        )
    if not hasattr(zone_obj, "on_mesh"):
        raise TypeError(
            "Domain spatial support must expose 'on_mesh(...)'. Expected a Field-compatible object."
        )
    if not hasattr(zone_obj, "identifier"):
        raise TypeError(
            "Domain spatial support must expose 'identifier'. Expected a Field-compatible object."
        )
    return zone_obj


def _resolve_spatial_support_from_domain(*, domain: object, support_id: str) -> object:
    """Resolve one support from domain helpers or raw zone registry."""
    normalized_support_id = str(support_id).strip()
    if normalized_support_id == "":
        raise ValueError("field_spatial_id cannot be empty for heterogeneous mapping")

    resolver = getattr(domain, "resolve_spatial_support", None)
    if callable(resolver):
        return resolver(normalized_support_id)

    zones = getattr(domain, "zones", {})
    if not isinstance(zones, dict):
        raise TypeError("domain.zones must be a dictionary")

    by_zone_id = zones.get(normalized_support_id.lower())
    if by_zone_id is not None:
        return by_zone_id

    matches = [
        zone_obj
        for zone_obj in zones.values()
        if str(getattr(zone_obj, "identifier", "")).strip() == normalized_support_id
    ]
    if len(matches) > 1:
        raise ValueError(f"Multiple domain zones match spatial support '{normalized_support_id}'.")
    return matches[0] if matches else None


def _resolve_field_param(*, flow: object, aliases: tuple[str, ...], property_label: str):
    """Return the first Flow parameter matching one alias set."""
    if flow is None or not hasattr(flow, "parameters"):
        raise ValueError("Missing flow object or flow.parameters for property mapping")
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        raise TypeError("flow.parameters must be a dictionary")

    for alias in aliases:
        if alias in parameters:
            param_obj = parameters[alias]
            if not hasattr(param_obj, "to_mesh_field"):
                raise TypeError(
                    f"Cannot map {property_label}: selected parameter '{alias}' "
                    "does not expose to_mesh_field(...)"
                )
            return str(alias), param_obj

    aliases_txt = ", ".join(aliases)
    raise ValueError(f"Cannot map {property_label}: missing flow parameter among ({aliases_txt})")


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
    logger.info(
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
