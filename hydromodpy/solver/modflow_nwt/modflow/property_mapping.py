"""
Property mapping helpers for MODFLOW solvers (NWT and MF6 interoperability).

This module translates process-level hydraulic properties carried by
``Flow``/``Domain`` objects into solver-ready arrays on a structured grid.

In practice, this covers the canonical mapping:
1. ``K``  -> ``hk`` (+ ``hk_value`` surface snapshot)
2. ``Sy`` -> ``sy`` (+ ``sy_value`` surface snapshot)
3. ``Ss`` -> ``ss`` (+ ``ss_value`` surface snapshot)

Design goals
------------
- Keep mapping logic isolated from solver package assembly.
- Fail fast on inconsistent contracts (missing parameters/zones).
- Expose one explicit high-level entry point for canonical K/Sy/Ss mapping.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_common.runtime_arrays import (
    resolve_flow_property_runtime_overrides,
)
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
    discretize_fieldparam_on_sgrid,
)

logger = get_logger(__name__)


def resolve_required_flow_properties(*, flow_regime: str) -> frozenset[str]:
    """Return the minimal hydraulic-property set required for one flow regime."""
    regime = str(flow_regime).strip().lower()
    if regime == "steady":
        return frozenset({"K"})
    return frozenset({"K", "Sy", "Ss"})


@dataclass
class _PropertyMappingProxy:
    """
    Minimal object exposing ``flow`` and ``domain`` for mapping helpers.

    Pedagogical note
    ----------------
    Mapping utilities historically expect a single object carrying both
    attributes. This tiny proxy lets us reuse that contract without requiring
    a full solver instance.
    """

    flow: object
    domain: object


def _coerce_spatial_support_field(zone_obj, *, support_id: str | None = None):
    """Validate one domain spatial support used for heterogeneous mapping."""
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
    """Resolve one spatial support from domain helpers or raw zone registry."""
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


def _build_property_from_flow_domain(
    *,
    model,
    solver_mesh,
    geometry_cache,
    flow_param_candidates,
    target_3d_attr: str,
    target_surface_attr: str,
    property_label: str,
) -> None:
    """
    Map one Flow parameter to one solver property array on SGrid.

    Design intent
    -------------
    Keep the call site compact, while keeping behavior explicit:
    - one helper call per property (K, Sy, Ss),
    - deterministic output arrays (`target_3d_attr`, `target_surface_attr`),
    - strict contract (no fallback, no silent skip).

    Practical examples
    ------------------
    Example A (hydraulic conductivity):
    - input aliases: `("K", "k")`
    - output attrs: `target_3d_attr="hk"`, `target_surface_attr="hk_value"`
    - expected result:
      `model.hk.shape == (nlay, nrow, ncol)` and
      `model.hk_value.shape == (nrow, ncol)`

    Example B (specific yield):
    - input aliases: `("Sy", "SY", "sy", "S", "s")`
    - output attrs: `target_3d_attr="sy"`, `target_surface_attr="sy_value"`

    Strict behavior (important)
    ---------------------------
    If one prerequisite is missing (parameter, spatial support, spatial-id
    compatibility), this method raises immediately. In mapping mode, there
    is intentionally no historical fallback.
    """
    # 1) Validate object contracts early (fail fast, explicit error message).
    if model.flow is None or not hasattr(model.flow, "parameters"):
        raise ValueError("Missing flow object or flow.parameters for property mapping")
    if model.domain is None or not hasattr(model.domain, "zones"):
        raise ValueError("Missing domain object or domain.zones for property mapping")

    # 2) Read the Flow parameter registry and pick the first matching alias.
    #    Example: with aliases ("K", "k"), prefer "K" if both exist.
    parameters = getattr(model.flow, "parameters", {})
    if not isinstance(parameters, dict):
        raise TypeError("flow.parameters must be a dictionary")

    param_obj = None
    selected_name = None
    for candidate in flow_param_candidates:
        if candidate in parameters:
            param_obj = parameters.get(candidate)
            selected_name = str(candidate)
            break
    if param_obj is None:
        aliases = ", ".join([str(v) for v in flow_param_candidates])
        raise ValueError(f"Cannot map {property_label}: missing flow parameter among ({aliases})")
    if not hasattr(param_obj, "to_mesh_field"):
        raise TypeError(
            f"Cannot map {property_label}: selected parameter '{selected_name}' "
            "does not expose to_mesh_field(...)"
        )

    # 3) Resolve spatial support from Domain only when the parameter actually
    #    needs one. Homogeneous parameters can be mapped directly on the mesh.
    support_field = None
    required_field_id = None
    if getattr(param_obj, "is_heterogeneous", False):
        required_field_id = str(getattr(param_obj, "field_spatial_id", "")).strip()
        support_field = _coerce_spatial_support_field(
            _resolve_spatial_support_from_domain(
                domain=model.domain,
                support_id=required_field_id,
            ),
            support_id=required_field_id,
        )

    # 4) Core discretization call:
    #    - support_field.on_mesh(...) creates the planar support when needed;
    #    - homogeneous parameters are mapped directly on the planar mesh;
    #    - field_param.to_mesh_field(..., depth=...) is evaluated over layers.
    discretized = discretize_fieldparam_on_sgrid(
        support_field=support_field,
        field_param=param_obj,
        sgrid=solver_mesh,
        geometry_cache=geometry_cache,
        cell_samples_per_axis=None,
        depth=0.0,
        strict_field_spatial_id_match=True,
    )

    # 5) Persist outputs on the caller object:
    #    - solver-ready 3D tensor (`hk`, `sy`, `ss`),
    #    - surface 2D view kept for legacy logs/plots.
    setattr(model, target_3d_attr, np.asarray(discretized.values_3d, dtype=float))
    setattr(model, target_surface_attr, np.asarray(discretized.values_2d, dtype=float))

    support_label = (
        f"domain support '{required_field_id}'"
        if required_field_id is not None
        else "direct homogeneous mapping"
    )
    logger.info("%s mapped from flow.%s using %s", property_label, selected_name, support_label)


def _zero_property_arrays(*, solver_mesh) -> tuple[np.ndarray, np.ndarray]:
    """Return zero-filled 3D/2D property arrays matching one solver mesh."""
    nlay = solver_mesh.nlay
    nrow = solver_mesh.nrow
    ncol = solver_mesh.ncol
    return (
        np.zeros((nlay, nrow, ncol), dtype=float),
        np.zeros((nrow, ncol), dtype=float),
    )


def resolve_flow_property_arrays(
    *,
    flow: object,
    domain: object,
    solver_mesh,
    required_properties: frozenset[str] | set[str] | None = None,
    optional_fill_values: Mapping[str, float] | None = None,
    runtime_property_overrides: Mapping[str, object] | None = None,
) -> dict[str, np.ndarray]:
    """
    Resolve canonical K/Sy/Ss arrays for solver consumption.

    Returns
    -------
    dict[str, np.ndarray]
        Dictionary containing both 3D arrays (`hk`, `sy`, `ss`) and 2D
        diagnostic surfaces (`hk_value`, `sy_value`, `ss_value`).

    Notes
    -----
    Mapping is executed in strict mode only: any inconsistency raises
    immediately. Outputs are written on a local proxy object and copied out,
    so caller state is not mutated.
    """
    # Canonical alias-to-target mapping shared by NWT and MF6 code paths.
    mapping_specs = [
        ("K", ("K", "k"), "hk", "hk_value", "Hydraulic conductivity"),
        ("Sy", ("Sy", "SY", "sy", "S", "s"), "sy", "sy_value", "Specific yield"),
        ("Ss", ("Ss", "SS", "ss"), "ss", "ss_value", "Specific storage"),
    ]

    required = (
        {str(name).strip() for name in required_properties}
        if required_properties is not None
        else {"K", "Sy", "Ss"}
    )
    optional_defaults = {
        str(name).strip(): float(value) for name, value in (optional_fill_values or {}).items()
    }

    # Use a tiny proxy to satisfy mapping helper contract.
    proxy = _PropertyMappingProxy(flow=flow, domain=domain)
    # Per-call cache used to reuse geometry discretization across K/Sy/Ss mapping.
    geometry_cache: dict[tuple[object, ...], tuple[object, object | None, np.ndarray]] = {}
    out: dict[str, np.ndarray] = {}
    parameters = getattr(flow, "parameters", {})
    if not isinstance(parameters, dict):
        raise TypeError("flow.parameters must be a dictionary")
    runtime_overrides = resolve_flow_property_runtime_overrides(
        runtime_property_overrides,
        solver_mesh,
        required_properties=required,
        optional_fill_values=optional_fill_values,
    )

    for canonical_name, aliases, target_3d_attr, target_surface_attr, label in mapping_specs:
        if target_3d_attr in runtime_overrides:
            out[target_3d_attr] = np.asarray(
                runtime_overrides[target_3d_attr],
                dtype=float,
            ).copy()
            out[target_surface_attr] = np.asarray(
                runtime_overrides[target_surface_attr],
                dtype=float,
            ).copy()
            continue
        has_parameter = any(candidate in parameters for candidate in aliases)
        if not has_parameter and canonical_name not in required:
            fill_value = optional_defaults.get(canonical_name, None)
            if fill_value is None:
                continue
            values_3d, values_2d = _zero_property_arrays(solver_mesh=solver_mesh)
            if fill_value != 0.0:
                values_3d.fill(fill_value)
                values_2d.fill(fill_value)
            out[target_3d_attr] = values_3d
            out[target_surface_attr] = values_2d
            continue
        # Mapping writes attributes on the proxy only.
        _build_property_from_flow_domain(
            model=proxy,
            solver_mesh=solver_mesh,
            geometry_cache=geometry_cache,
            flow_param_candidates=aliases,
            target_3d_attr=target_3d_attr,
            target_surface_attr=target_surface_attr,
            property_label=label,
        )
        # Copy arrays out so downstream code can mutate them safely.
        out[target_3d_attr] = np.asarray(getattr(proxy, target_3d_attr), dtype=float).copy()
        out[target_surface_attr] = np.asarray(
            getattr(proxy, target_surface_attr), dtype=float
        ).copy()
    return out
