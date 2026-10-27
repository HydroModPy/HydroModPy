"""The one mapping of the hydraulic properties of a flow onto a cell mesh.

Every solver reads K, Kv, Sy and Ss from ``map_flow_properties``: one value per
cell, evaluated at each layer-centre depth. MODFLOW 6 also reads the rest of the
K tensor, K22 and the three angles, the same way. A homogeneous parameter is its value
times its vertical profile. A heterogeneous one is the zone-weighted mean of its
zone values on the fractions ``zone_fractions`` gives for its spatial support.
MODFLOW passes the layer-centre depths of its solver mesh, Boussinesq one layer
at depth zero.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)
from hydromodpy.spatial.field.meshes.field_mesh_adapter import to_field_mesh
from hydromodpy.spatial.field.zone_fractions import ZoneFractions, zone_fractions
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

logger = get_logger(__name__)

FLOW_PROPERTY_SPECS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("K", ("K", "k"), "hk", "Hydraulic conductivity"),
    ("Kv", ("Kv", "kv", "K33", "k33"), "kv", "Vertical hydraulic conductivity"),
    ("Sy", ("Sy", "SY", "sy", "S", "s"), "sy", "Specific yield"),
    ("Ss", ("Ss", "SS", "ss"), "ss", "Specific storage"),
    ("K22", ("K22", "k22"), "k22", "Hydraulic conductivity along the second tensor axis"),
    ("angle1", ("angle1",), "angle1", "Turn of the first K axis from east towards north (degrees)"),
    ("angle2", ("angle2",), "angle2", "Rise of the first K axis above the horizontal (degrees)"),
    ("angle3", ("angle3",), "angle3", "Rotation of the K tensor about its first axis (degrees)"),
)
"""Canonical name, flow parameter aliases, output name and label of each property."""

K_TENSOR_PROPERTIES: tuple[str, ...] = ("K22", "angle1", "angle2", "angle3")
"""The part of the K tensor past K and Kv, which only MODFLOW 6 reads."""


def k_tensor_parameter_ids(parameters: Mapping[str, object]) -> list[str]:
    """The flow parameter ids in ``parameters`` that set K22 or an angle."""
    aliases = {
        alias
        for canonical, names, _, _ in FLOW_PROPERTY_SPECS
        if canonical in K_TENSOR_PROPERTIES
        for alias in names
    }
    return [str(param_id) for param_id in parameters if param_id in aliases]


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


def map_flow_properties(
    *,
    flow: object,
    domain: object,
    cell_mesh: PlanarCellMesh,
    layer_depths: np.ndarray,
    properties: tuple[str, ...],
    required: frozenset[str] | set[str],
    optional_fill_values: Mapping[str, float] | None = None,
    runtime_overrides: Mapping[str, np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """Map the flow properties named in ``properties`` onto the cells of ``cell_mesh``.

    ``layer_depths`` is ``(nlay, n_cells)``, the depth below the top of each
    layer centre. Each mapped property ``p`` gives ``p`` ``(nlay, n_cells)`` and
    ``p_value`` ``(n_cells,)``, the values at depth zero (``hk``, ``hk_value``,
    ...). A property with no flow parameter is mapped from
    ``optional_fill_values`` when it is not required, and left out when no fill
    value is given. ``runtime_overrides`` are arrays already shaped as the output
    (``resolve_flow_property_runtime_overrides``); they win over the flow. An
    override of a property outside ``properties`` is refused, since the solver
    would drop it.
    """
    depths = np.asarray(layer_depths, dtype=float)
    n_cells = int(cell_mesh.n_cells)
    if depths.ndim != 2 or depths.shape[1] != n_cells:
        raise ValueError(f"layer_depths must have shape (nlay, {n_cells}), got {depths.shape}")
    parameters = getattr(flow, "parameters", None)
    if not isinstance(parameters, dict):
        raise TypeError("flow.parameters must be a dictionary")
    overrides = dict(runtime_overrides or {})
    unread = [
        canonical
        for canonical, _, name, _ in FLOW_PROPERTY_SPECS
        if name in overrides and canonical not in properties
    ]
    if unread:
        raise ValueError(
            f"A runtime override sets {', '.join(unread)}, which this solver does not "
            f"read: it reads {', '.join(properties)}. Remove the override, or run a "
            "solver that reads it (MODFLOW 6 for K22 and the angles)."
        )
    fill_values = {str(name): float(value) for name, value in (optional_fill_values or {}).items()}
    field_mesh = to_field_mesh(cell_mesh.mesh)
    fractions_by_support: dict[int, ZoneFractions] = {}

    out: dict[str, np.ndarray] = {}
    for canonical, aliases, name, label in FLOW_PROPERTY_SPECS:
        if canonical not in properties:
            continue
        if name in overrides:
            out[name] = np.asarray(overrides[name], dtype=float).copy()
            out[f"{name}_value"] = np.asarray(overrides[f"{name}_value"], dtype=float).copy()
            continue
        if not any(alias in parameters for alias in aliases) and canonical not in required:
            fill = fill_values.get(canonical)
            if fill is not None:
                out[name] = np.full(depths.shape, fill, dtype=float)
                out[f"{name}_value"] = np.full(n_cells, fill, dtype=float)
            continue
        selected, param = resolve_field_param(flow=flow, aliases=aliases, property_label=label)
        discretization = None
        if getattr(param, "is_heterogeneous", False):
            support = _heterogeneous_support(param, domain=domain, property_label=label)
            fractions = fractions_by_support.get(id(support))
            if fractions is None:
                fractions = zone_fractions(cell_mesh, support)
                fractions_by_support[id(support)] = fractions
            discretization = WeightedAverageFieldDiscretization(
                mesh=field_mesh,
                field_id=str(support.identifier),
                zone_keys=fractions.zone_keys,
                fractions_by_zone=fractions.by_zone(),
            )
        out[f"{name}_value"] = _cell_values(param, discretization, field_mesh, name, 0.0)
        out[name] = np.vstack(
            [_cell_values(param, discretization, field_mesh, name, depth) for depth in depths]
        )
        logger.debug("%s mapped from flow.%s", label, selected)
    return out


def _heterogeneous_support(param: object, *, domain: object, property_label: str) -> object:
    """The spatial support a heterogeneous parameter names, checked against its id."""
    if domain is None:
        raise ValueError(f"Cannot map {property_label}: missing domain for heterogeneous parameter")
    required_id = str(getattr(param, "field_spatial_id", "")).strip()
    support = coerce_spatial_support_field(
        resolve_spatial_support_from_domain(domain=domain, support_id=required_id),
        support_id=required_id,
    )
    support_id = str(getattr(support, "identifier", "")).strip()
    if support_id and support_id != required_id:
        raise ValueError(
            "field_param.field_spatial_id does not match support_field.identifier: "
            f"{required_id!r} != {support_id!r}"
        )
    return support


def _cell_values(
    param: object,
    discretization: WeightedAverageFieldDiscretization | None,
    field_mesh: object,
    name: str,
    depth: float | np.ndarray,
) -> np.ndarray:
    """One value per cell of a parameter at one depth (scalar or per cell)."""
    if discretization is None:
        values = param.to_mesh_field(mesh=field_mesh, label=name, depth=depth)
    else:
        values = param.to_mesh_field(discretization, label=name, depth=depth)
    return np.asarray(values.cell_values, dtype=float).reshape(-1)


__all__ = [
    "FLOW_PROPERTY_SPECS",
    "K_TENSOR_PROPERTIES",
    "coerce_spatial_support_field",
    "k_tensor_parameter_ids",
    "map_flow_properties",
    "require_positive_conductivity",
    "resolve_field_param",
    "resolve_spatial_support_from_domain",
]
