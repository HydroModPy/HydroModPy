"""Shared helpers for field-based solver property mapping."""

from __future__ import annotations

import numpy as np

from hydromodpy.core.exceptions import DataContractViolation


def coerce_spatial_support_field(zone_obj, *, support_id: str | None = None):
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


def resolve_spatial_support_from_domain(*, domain: object, support_id: str) -> object:
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


def resolve_field_param(*, flow: object, aliases: tuple[str, ...], property_label: str):
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


def require_positive_conductivity(
    hk,
    *,
    active_mask,
    flow: object | None = None,
    property_label: str = "K",
) -> None:
    """Refuse a conductivity that is zero, negative or not finite on an active cell.

    A solver must never receive such a value in silence. MODFLOW 6 stops with a
    bare "K is <= 0" line, and NWT runs on it. A heterogeneous K joined to a
    spatial support gives exactly 0 where no zone of the support covers the
    cell: the weighted average has no term. That happens when the support data
    (a geology map) does not cover the whole active model domain.

    ``active_mask`` is True on active cells and must broadcast to ``hk``.
    Inactive cells are not checked: the solver never reads them.
    """
    values = np.asarray(hk, dtype=float)
    active = np.asarray(active_mask, dtype=bool)
    if active.size == values.size:
        active = active.reshape(values.shape)
    else:
        active = np.broadcast_to(active, values.shape)
    invalid = active & ~(np.isfinite(values) & (values > 0.0))
    n_invalid = int(np.count_nonzero(invalid))
    if n_invalid == 0:
        return

    n_active = int(np.count_nonzero(active))
    n_zero = int(np.count_nonzero(invalid & (values == 0.0)))
    n_nonfinite = int(np.count_nonzero(invalid & ~np.isfinite(values)))
    detail = (
        f"{property_label} is zero, negative or not finite on {n_invalid} of {n_active} "
        f"active cell(s) ({n_zero} zero, {n_nonfinite} not finite)."
    )

    hint = " Check the value given to this parameter in [flow.param]."
    parameters = getattr(flow, "parameters", None)
    param_obj = None
    if isinstance(parameters, dict):
        param_obj = parameters.get(property_label, parameters.get(property_label.lower()))
    if param_obj is not None and getattr(param_obj, "is_heterogeneous", False):
        support_id = getattr(param_obj, "field_spatial_id", None)
        hint = (
            f" {property_label} is heterogeneous on spatial support '{support_id}'. A cell "
            "that no zone of this support covers gets no value, so the support data does "
            "not cover the whole active domain. Make the support source cover the model "
            "extent, or check the values of the zones it does cover."
        )
    raise DataContractViolation(detail + hint)


__all__ = [
    "coerce_spatial_support_field",
    "require_positive_conductivity",
    "resolve_field_param",
    "resolve_spatial_support_from_domain",
]
