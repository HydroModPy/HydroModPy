"""Build shape-aware runtime payloads for MODFLOW-family solvers."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.physical_bounds import (
    validate_physical_array,
    validate_physical_value,
)
from hydromodpy.solver.field_property_mapping import FLOW_PROPERTY_SPECS

logger = get_logger(__name__)


def flow_grid_shape(flow_model: object) -> tuple[int, int, int]:
    """Return one shape tuple for structured or cell-based flow models.

    Structured models return ``(nlay, nrow, ncol)``.
    Cell-based unstructured models return ``(nlay, 1, ncpl)``.
    """

    mf = getattr(flow_model, "mf", None)
    if mf is not None and all(hasattr(mf, name) for name in ("nlay", "nrow", "ncol")):
        return int(mf.nlay), int(mf.nrow), int(mf.ncol)

    if all(hasattr(flow_model, name) for name in ("nlay", "nrow", "ncol")):
        return (
            int(flow_model.nlay),
            int(flow_model.nrow),
            int(flow_model.ncol),
        )

    if all(hasattr(flow_model, name) for name in ("nlay", "ncpl")):
        return int(flow_model.nlay), 1, int(flow_model.ncpl)

    raise ValueError("Could not resolve flow grid shape from dependency model.")


def flow_stress_period_count(flow_model: object) -> int:
    """Return ``nper`` from one resolved upstream flow model."""

    if not hasattr(flow_model, "nper"):
        raise ValueError("Could not resolve stress-period count (nper) from flow model.")
    return int(flow_model.nper)


def _is_scalar_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _as_2d_array(value: object, *, nrow: int, ncol: int) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.shape == (nrow, ncol):
        return array
    if array.size == nrow * ncol:
        return array.reshape(nrow, ncol)
    raise ValueError(
        f"Expected 2D concentration array with shape ({nrow}, {ncol}), got {array.shape}."
    )


def _as_flat_array(value: object, *, ncpl: int) -> np.ndarray:
    array = np.asarray(value, dtype=float).reshape(-1)
    if array.size != ncpl:
        raise ValueError(
            f"Expected concentration payload with {ncpl} cell values, got {array.size}."
        )
    return array


def _normalize_sconc_input(
    raw_value: object,
    *,
    nper: int,
    nrow: int | None,
    ncol: int | None,
    ncpl: int,
    structured: bool,
) -> dict[int, np.ndarray] | None:
    if _is_scalar_number(raw_value):
        scalar = float(raw_value)
        # A single-period (fully steady) run must inject the recharge concentration
        # at period 0; transient multi-period runs keep their per-period split.
        start_sp = 0 if nper == 1 else 1
        if nper == 1 and scalar != 0.0:
            logger.warning("Single-period recharge concentration %.6g applied at period 0.", scalar)
        if structured:
            return {
                sp: np.full((int(nrow), int(ncol)), scalar, dtype=float)
                for sp in range(start_sp, nper)
            }
        return {sp: np.full(ncpl, scalar, dtype=float) for sp in range(start_sp, nper)}

    if not isinstance(raw_value, Mapping):
        return None

    normalized: dict[int, np.ndarray] = {}
    for raw_sp, raw_array in raw_value.items():
        try:
            stress_period = int(raw_sp)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid stress-period key in sconc_input mapping: {raw_sp!r}."
            ) from exc

        if stress_period < 0 or stress_period >= nper:
            raise ValueError(
                f"Stress-period key {stress_period} is outside expected range [0, {nper - 1}]."
            )

        if _is_scalar_number(raw_array):
            if structured:
                normalized[stress_period] = np.full(
                    (int(nrow), int(ncol)), float(raw_array), dtype=float
                )
            else:
                normalized[stress_period] = np.full(ncpl, float(raw_array), dtype=float)
            continue
        if structured:
            normalized[stress_period] = _as_2d_array(raw_array, nrow=int(nrow), ncol=int(ncol))
        else:
            normalized[stress_period] = _as_flat_array(raw_array, ncpl=ncpl)
    return normalized


def build_concentration_runtime_overrides(
    parameters: Mapping[str, object] | None,
    flow_model: object,
) -> dict[str, object]:
    """Build runtime concentration payloads from scalar transport parameters."""

    params = dict(parameters or {})
    nlay, nrow_hint, ncol_hint = flow_grid_shape(flow_model)
    nper = flow_stress_period_count(flow_model)
    structured = all(hasattr(flow_model, name) for name in ("nrow", "ncol")) or (
        getattr(flow_model, "mf", None) is not None
        and all(hasattr(flow_model.mf, name) for name in ("nrow", "ncol"))
    )
    ncpl = int(getattr(flow_model, "ncpl", nrow_hint * ncol_hint))

    overrides: dict[str, object] = {}

    sconc_init = params.get("sconc_init")
    if _is_scalar_number(sconc_init):
        if structured:
            overrides["sconc_init"] = np.full(
                (nlay, nrow_hint, ncol_hint), float(sconc_init), dtype=float
            )
        else:
            overrides["sconc_init"] = np.full((nlay, ncpl), float(sconc_init), dtype=float)

    rate_decay = params.get("rate_decay")
    if _is_scalar_number(rate_decay):
        if structured:
            overrides["rate_decay"] = np.full(
                (nlay, nrow_hint, ncol_hint), float(rate_decay), dtype=float
            )
        else:
            overrides["rate_decay"] = np.full((nlay, ncpl), float(rate_decay), dtype=float)

    normalized_sconc_input = _normalize_sconc_input(
        params.get("sconc_input"),
        nper=nper,
        nrow=nrow_hint if structured else None,
        ncol=ncol_hint if structured else None,
        ncpl=ncpl,
        structured=structured,
    )
    if normalized_sconc_input is not None:
        overrides["sconc_input"] = normalized_sconc_input

    return overrides


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
