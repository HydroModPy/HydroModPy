"""The one mapping of the hydraulic properties of a flow onto a cell mesh.

Every solver reads K, Kv, Sy and Ss from ``map_flow_properties``: one value per
cell, evaluated at each layer-center depth. MODFLOW 6 also reads the rest of the
K tensor, K22 and the three angles, the same way. A homogeneous parameter is its value
times its vertical profile. A heterogeneous one is the zone-weighted mean of its
zone values on the fractions ``zone_fractions`` gives for its spatial support.
MODFLOW passes the layer-center depths of its solver mesh, Boussinesq one layer
at depth zero.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.physical_bounds import (
    validate_physical_array,
    validate_physical_value,
)
from hydromodpy.model.properties.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.model.properties.property_ids import FLOW_PROPERTY_IDS
from hydromodpy.model.properties.zone_fractions import ZoneFractions, zone_fractions
from hydromodpy.model.time.regime import normalize_flow_regime
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

logger = get_logger(__name__)

FLOW_PROPERTY_SPECS: tuple[tuple[str, tuple[str, ...], str, str], ...] = tuple(
    (prop.id, (prop.id,), prop.output, prop.label) for prop in FLOW_PROPERTY_IDS
)
"""Canonical name, flow parameter ids, output name and label of each property."""

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
    active = _cells_like(active_mask, values, dtype=bool)
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
    hint = _value_hint(flow, property_label, (property_label, property_label.lower()))
    raise DataContractViolation(detail + hint)


def require_positive_storage(
    sy,
    ss,
    *,
    active_mask,
    iconvert,
    steady,
    flow: object | None = None,
) -> None:
    """Refuse a storage that a transient period reads and that is zero, negative or not finite.

    The storage only counts in a transient period, so nothing is checked when
    every flag of ``steady`` (one per stress period) is True. A convertible cell
    (``iconvert`` not 0) stores water by its specific yield, so its Sy must be
    positive. A confined cell (``iconvert`` 0) stores it by its specific
    storage, so its Ss must be positive. Ss = 0 on a convertible cell stays
    allowed: it is the Dupuit approximation the unconfined validation cases
    make. As for K, a heterogeneous Sy or Ss gives 0 on a cell that no zone of
    its support covers.

    ``sy`` and ``ss`` have the layer first, ``(nlay, ...)``, or are one layer
    ``(n_cells,)``. ``ss`` is None for a solver without specific storage
    (Boussinesq). ``active_mask`` has their size. ``iconvert`` is one flag, one
    flag per layer or one per cell. Inactive cells are not checked.
    """
    if bool(np.all(np.asarray(steady, dtype=bool))):
        return
    sy_values = _by_layer(sy)
    active = _cells_like(active_mask, sy_values, dtype=bool)
    convertible = _cells_like(iconvert, sy_values, dtype=int) != 0
    _require_positive_storage_cells(sy_values, active & convertible, "Sy", "convertible", flow)
    if ss is not None:
        ss_values = _by_layer(ss)
        _require_positive_storage_cells(ss_values, active & ~convertible, "Ss", "confined", flow)


_STORAGE_ROLES = {
    "Sy": "A convertible cell stores water by its specific yield, so Sy must be positive there.",
    "Ss": "A confined cell stores water by its specific storage, so Ss must be positive there.",
}


def _require_positive_storage_cells(
    values: np.ndarray, read: np.ndarray, label: str, kind: str, flow: object | None
) -> None:
    """Refuse ``label`` on the cells of ``read`` where it is not positive and finite."""
    invalid = read & ~(np.isfinite(values) & (values > 0.0))
    n_invalid = int(np.count_nonzero(invalid))
    if n_invalid == 0:
        return
    per_layer = invalid.reshape(invalid.shape[0], -1).sum(axis=1)
    layers = ", ".join(
        f"layer {layer + 1}: {int(count)}" for layer, count in enumerate(per_layer) if count
    )
    n_zero = int(np.count_nonzero(invalid & (values == 0.0)))
    n_nonfinite = int(np.count_nonzero(invalid & ~np.isfinite(values)))
    aliases = next(names for canonical, names, _, _ in FLOW_PROPERTY_SPECS if canonical == label)
    raise DataContractViolation(
        f"{label} is zero, negative or not finite on {n_invalid} of "
        f"{int(np.count_nonzero(read))} active {kind} cell(s) that a transient period "
        f"reads ({layers}; {n_zero} zero, {n_nonfinite} not finite). {_STORAGE_ROLES[label]}"
        + _value_hint(flow, label, aliases)
    )


def _by_layer(values) -> np.ndarray:
    """``values`` as floats with the layer first; one layer when it is flat."""
    array = np.asarray(values, dtype=float)
    return array.reshape(1, -1) if array.ndim <= 1 else array


def _cells_like(flags, values: np.ndarray, *, dtype) -> np.ndarray:
    """``flags`` on the cells of ``values``: of their size, one per layer, or one."""
    array = np.asarray(flags, dtype=dtype)
    if array.size == values.size:
        return array.reshape(values.shape)
    if array.ndim == 1 and values.ndim > 1 and array.size == values.shape[0]:
        array = array.reshape((-1,) + (1,) * (values.ndim - 1))
    return np.broadcast_to(array, values.shape)


def _value_hint(flow: object | None, label: str, aliases: tuple[str, ...]) -> str:
    """Where to look for the value of ``label``: its zones when it is heterogeneous."""
    parameters = getattr(flow, "parameters", None)
    param_obj = None
    if isinstance(parameters, dict):
        param_obj = next((parameters[name] for name in aliases if name in parameters), None)
    if param_obj is not None and getattr(param_obj, "is_heterogeneous", False):
        support_id = getattr(param_obj, "field_spatial_id", None)
        return (
            f" {label} is heterogeneous on spatial support '{support_id}'. A cell "
            "that no zone of this support covers gets no value, so the support data does "
            "not cover the whole active domain. Make the support source cover the model "
            "extent, or check the values of the zones it does cover."
        )
    return " Check the value given to this parameter in [flow.param]."


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
    layer center. Each mapped property ``p`` gives ``p`` ``(nlay, n_cells)`` and
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
        selected, param = _resolve_field_param(flow=flow, aliases=aliases, property_label=label)
        discretization = None
        if getattr(param, "is_heterogeneous", False):
            support = _heterogeneous_support(param, domain=domain, property_label=label)
            fractions = fractions_by_support.get(id(support))
            if fractions is None:
                fractions = zone_fractions(cell_mesh, support)
                fractions_by_support[id(support)] = fractions
            discretization = WeightedAverageFieldDiscretization(
                mesh=cell_mesh,
                field_id=str(support.identifier),
                zone_keys=fractions.zone_keys,
                fractions_by_zone=fractions.by_zone(),
            )
        out[f"{name}_value"] = _cell_values(param, discretization, cell_mesh, name, 0.0)
        out[name] = np.vstack(
            [_cell_values(param, discretization, cell_mesh, name, depth) for depth in depths]
        )
        logger.debug("%s mapped from flow.%s", label, selected)
    return out


def _heterogeneous_support(param: object, *, domain: object, property_label: str) -> object:
    """The spatial support a heterogeneous parameter names, checked against its id."""
    if domain is None:
        raise ValueError(f"Cannot map {property_label}: missing domain for heterogeneous parameter")
    required_id = str(getattr(param, "field_spatial_id", "")).strip()
    support = _coerce_spatial_support_field(
        _resolve_spatial_support_from_domain(domain=domain, support_id=required_id),
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
    cell_mesh: PlanarCellMesh,
    name: str,
    depth: float | np.ndarray,
) -> np.ndarray:
    """One value per cell of a parameter at one depth (scalar or per cell)."""
    if discretization is None:
        values = param.to_mesh_field(mesh=cell_mesh, label=name, depth=depth)
    else:
        values = param.to_mesh_field(discretization, label=name, depth=depth)
    return np.asarray(values.cell_values, dtype=float).reshape(-1)


_FLOW_PROPERTY_SPECS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = tuple(
    (
        canonical,
        name,
        f"{name}_value",
        aliases if name in aliases else (*aliases, name),
    )
    for canonical, aliases, name, _label in FLOW_PROPERTY_SPECS
)
"""Every property of the shared mapping, K22 and the angles included, so an
override reaches the same arrays as the flow parameter it replaces. The output
name (``hk``, ``kv``, ...) is accepted as one more alias."""


def _coerce_flow_property_override(
    value: object,
    *,
    nlay: int,
    n_cells: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(nlay, n_cells)`` values and their first layer from one override."""
    flat = np.asarray(value, dtype=float).reshape(-1)
    if flat.size == 1:
        surface_values = np.full(n_cells, float(flat[0]), dtype=float)
        return np.repeat(surface_values[None, :], nlay, axis=0), surface_values
    if flat.size == n_cells:
        surface_values = flat.copy()
        return np.repeat(surface_values[None, :], nlay, axis=0), surface_values
    if flat.size == nlay * n_cells:
        values = flat.reshape(nlay, n_cells).copy()
        return values, values[0].copy()
    raise ValueError(
        "Hydraulic runtime override has incompatible size. "
        f"Expected scalar, surface size {n_cells}, or full size {nlay * n_cells}; "
        f"got shape {np.shape(value)}."
    )


_STORAGE_PROPERTIES = frozenset({"Sy", "Ss"})
"""Read by a transient period only: a steady run does not require them."""


def _validate_override_as_written(
    canonical_name: str, raw_value: object, *, nlay: int, n_cells: int
) -> None:
    """Check an override against the physical range of its property, as it was written.

    A scalar is checked once, a per-cell array cell by cell, a full array layer
    by layer. The refusal counts the values as written and names the layer and
    the cell, not a position in the array repeated over the layers.
    """
    flat = np.asarray(raw_value, dtype=float).reshape(-1)
    if flat.size == 1:
        validate_physical_value(
            param_id=canonical_name,
            value=float(flat[0]),
            where="the runtime override, one value for every cell,",
        )
        return
    rows = flat.reshape(-1, n_cells)
    for layer, row in enumerate(rows):
        place = "every layer" if rows.shape[0] == 1 else f"layer {layer + 1} of {nlay}"
        validate_physical_array(
            param_id=canonical_name, values=row, where=f"the runtime override, {place}, by cell"
        )


def _extract_flow_property_mapping(
    parameters: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if not isinstance(parameters, Mapping):
        return {}
    nested = parameters.get("properties")
    if isinstance(nested, Mapping):
        known = {alias for *_, aliases in _FLOW_PROPERTY_SPECS for alias in aliases}
        unknown = sorted(str(key) for key in nested if key not in known)
        if unknown:
            raise ValueError(
                f"Runtime property override(s) {', '.join(unknown)} name no flow property. "
                "An override sets one of "
                f"{', '.join(spec[0] for spec in _FLOW_PROPERTY_SPECS)}."
            )
        return nested
    return parameters


def resolve_flow_property_runtime_overrides(
    parameters: Mapping[str, object] | None,
    *,
    nlay: int,
    n_cells: int,
    required_properties: frozenset[str] | set[str] | None = None,
    optional_fill_values: Mapping[str, float] | None = None,
) -> dict[str, np.ndarray]:
    """Normalize runtime hydraulic overrides to canonical solver arrays.

    Accepted payloads are either:

    - one direct mapping such as ``{"K": [..], "Sy": 0.2}``, or
    - one envelope ``{"properties": {"K": [..], "Sy": 0.2}, ...}``.

    The properties are those of the shared mapping: K, Kv, Sy, Ss, K22 and the
    three angles of the K tensor. A name in the envelope that is none of them
    is refused rather than dropped.

    For each property, callers may provide:

    - one scalar value,
    - one array with one value per planar cell, or
    - one array with one value per model cell (``nlay * n_cells``).

    Arrays of any shape are read in C order, so a grid-shaped ``(nrow, ncol)``
    array reads as its cells, row 0 first. The result is flat:
    ``(nlay, n_cells)`` and ``(n_cells,)``.

    Every value given, in SI, is checked against the physical range of its
    property as it was written, on every cell, since the override carries no
    active mask. Sy and Ss are not checked when ``required_properties`` leaves
    them out: a steady run does not read them. A fill value is the caller's own
    default and is not checked.
    """

    property_mapping = _extract_flow_property_mapping(parameters)
    if not property_mapping:
        return {}

    required = (
        {str(name).strip() for name in required_properties}
        if required_properties is not None
        else {"K", "Sy", "Ss"}
    )
    optional_defaults = {
        str(name).strip(): float(value) for name, value in (optional_fill_values or {}).items()
    }

    out: dict[str, np.ndarray] = {}
    for canonical_name, target_3d_attr, target_surface_attr, aliases in _FLOW_PROPERTY_SPECS:
        raw_value = None
        for alias in aliases:
            if alias in property_mapping and property_mapping[alias] is not None:
                raw_value = property_mapping[alias]
                break

        if raw_value is None:
            if canonical_name in required:
                continue
            fill_value = optional_defaults.get(canonical_name)
            if fill_value is None:
                continue
            values_3d, values_2d = _coerce_flow_property_override(
                float(fill_value), nlay=int(nlay), n_cells=int(n_cells)
            )
        else:
            values_3d, values_2d = _coerce_flow_property_override(
                raw_value, nlay=int(nlay), n_cells=int(n_cells)
            )
            if canonical_name in required or canonical_name not in _STORAGE_PROPERTIES:
                _validate_override_as_written(
                    canonical_name, raw_value, nlay=int(nlay), n_cells=int(n_cells)
                )

        out[target_3d_attr] = values_3d
        out[target_surface_attr] = values_2d
    return out


def resolve_required_flow_properties(
    *, flow_regime: str, storage: tuple[str, ...] = ("Sy", "Ss")
) -> frozenset[str]:
    """The properties a run must find in its flow: K alone when steady, K and ``storage`` otherwise.

    ``storage`` is what the solver stores water by: Sy and Ss for MODFLOW, Sy
    for Boussinesq. An unknown regime asks for the full set.
    """
    try:
        regime = normalize_flow_regime(flow_regime)
    except ValueError:
        regime = "transient"
    if regime == "steady":
        return frozenset({"K"})
    return frozenset({"K", *storage})


__all__ = [
    "FLOW_PROPERTY_SPECS",
    "K_TENSOR_PROPERTIES",
    "k_tensor_parameter_ids",
    "map_flow_properties",
    "require_positive_conductivity",
    "require_positive_storage",
    "resolve_flow_property_runtime_overrides",
    "resolve_required_flow_properties",
]
