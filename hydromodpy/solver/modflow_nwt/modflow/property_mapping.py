# -*- coding: utf-8 -*-
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

from dataclasses import dataclass

import numpy as np

from hydromodpy.tools import get_logger
from hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_fieldparam_discretization import (
    discretize_fieldparam_on_sgrid,
)

logger = get_logger(__name__)


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


def _coerce_geology_field(zone_obj):
    """
    Validate and return the geology field used as mapping support.

    The downstream discretization routine expects the zone object to expose:
    - ``on_mesh(...)`` to project on 2D support,
    - ``identifier`` for spatial-id consistency checks.
    """
    if zone_obj is None:
        raise ValueError("Missing geology zone object in domain")

    if not hasattr(zone_obj, "on_mesh"):
        raise TypeError(
            "Domain geology zone must expose 'on_mesh(...)'. "
            "Expected a GeologyField-compatible object."
        )
    if not hasattr(zone_obj, "identifier"):
        raise TypeError(
            "Domain geology zone must expose 'identifier'. "
            "Expected a GeologyField-compatible object."
        )
    return zone_obj


def _build_property_from_flow_domain(
    *,
    model,
    sgrid,
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
    If one prerequisite is missing (parameter, geology zone, spatial-id
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
        raise ValueError(
            f"Cannot map {property_label}: missing flow parameter among ({aliases})"
        )
    if not hasattr(param_obj, "to_mesh_field"):
        raise TypeError(
            f"Cannot map {property_label}: selected parameter '{selected_name}' "
            "does not expose to_mesh_field(...)"
        )

    # 3) Resolve geology support from Domain.
    #    This must expose at least:
    #    - identifier (for heterogeneous consistency checks),
    #    - on_mesh(...) (for zone-fraction projection on the 2D support).
    zones = getattr(model.domain, "zones", {})
    if not isinstance(zones, dict):
        raise TypeError("domain.zones must be a dictionary")
    geology_zone = zones.get("geology")
    if geology_zone is None:
        raise ValueError("Cannot map property: domain.zones['geology'] is missing")
    geology_field = _coerce_geology_field(geology_zone)

    # 4) For heterogeneous parameters, enforce field spatial-id consistency.
    #    Example:
    #    - param_obj.field_spatial_id == "field_geology"
    #    - geology_field.identifier == "field_geology"
    #    If they differ, mapping is refused to avoid mixing unrelated supports.
    if getattr(param_obj, "is_heterogeneous", False):
        required_field_id = str(getattr(param_obj, "field_spatial_id", "")).strip()
        geology_field_id = str(getattr(geology_field, "identifier", "")).strip()
        if required_field_id and geology_field_id and required_field_id != geology_field_id:
            raise ValueError(
                f"Cannot map {property_label}: field_spatial_id mismatch "
                f"('{required_field_id}' != '{geology_field_id}')"
            )

    # 5) Core discretization call:
    #    - geology_field.on_mesh(...) creates the planar support;
    #    - field_param.to_mesh_field(..., depth=...) is evaluated over layers;
    #    - returned object contains both surface map and full 3D tensor.
    discretized = discretize_fieldparam_on_sgrid(
        geology_field=geology_field,
        field_param=param_obj,
        sgrid=sgrid,
        cell_samples_per_axis=None,
        depth=0.0,
        strict_field_spatial_id_match=True,
    )

    # 6) Persist outputs on the caller object:
    #    - solver-ready 3D tensor (`hk`, `sy`, `ss`),
    #    - surface 2D view kept for legacy logs/plots.
    setattr(model, target_3d_attr, np.asarray(discretized.values_3d, dtype=float))
    setattr(model, target_surface_attr, np.asarray(discretized.values_2d, dtype=float))

    logger.info(
        "%s mapped from flow.%s on domain geology",
        property_label,
        selected_name,
    )


def resolve_flow_property_arrays(
    *,
    flow: object,
    domain: object,
    sgrid: object,
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
        (("K", "k"), "hk", "hk_value", "Hydraulic conductivity"),
        (("Sy", "SY", "sy", "S", "s"), "sy", "sy_value", "Specific yield"),
        (("Ss", "SS", "ss"), "ss", "ss_value", "Specific storage"),
    ]

    # Use a tiny proxy to satisfy mapping helper contract.
    proxy = _PropertyMappingProxy(flow=flow, domain=domain)
    out: dict[str, np.ndarray] = {}
    for aliases, target_3d_attr, target_surface_attr, label in mapping_specs:
        # Mapping writes attributes on the proxy only.
        _build_property_from_flow_domain(
            model=proxy,
            sgrid=sgrid,
            flow_param_candidates=aliases,
            target_3d_attr=target_3d_attr,
            target_surface_attr=target_surface_attr,
            property_label=label,
        )
        # Copy arrays out so downstream code can mutate them safely.
        out[target_3d_attr] = np.asarray(
            getattr(proxy, target_3d_attr), dtype=float
        ).copy()
        out[target_surface_attr] = np.asarray(
            getattr(proxy, target_surface_attr), dtype=float
        ).copy()
    return out
