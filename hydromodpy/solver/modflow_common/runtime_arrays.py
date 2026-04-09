"""Build shape-aware runtime concentration payloads for transport solvers."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np


def flow_grid_shape(flow_model: object) -> tuple[int, int, int]:
    """Return one shape tuple for structured or cell-based flow models.

    Structured models return ``(nlay, nrow, ncol)``.
    Cell-based unstructured models return ``(nlay, 1, ncpl)``.
    """

    mf = getattr(flow_model, "mf", None)
    if mf is not None and all(hasattr(mf, name) for name in ("nlay", "nrow", "ncol")):
        return int(mf.nlay), int(mf.nrow), int(mf.ncol)

    if all(hasattr(flow_model, name) for name in ("nlay", "nrow", "ncol")):
        return int(getattr(flow_model, "nlay")), int(getattr(flow_model, "nrow")), int(
            getattr(flow_model, "ncol")
        )

    if all(hasattr(flow_model, name) for name in ("nlay", "ncpl")):
        return int(getattr(flow_model, "nlay")), 1, int(getattr(flow_model, "ncpl"))

    raise ValueError("Could not resolve flow grid shape from dependency model.")


def flow_stress_period_count(flow_model: object) -> int:
    """Return ``nper`` from one resolved upstream flow model."""

    if not hasattr(flow_model, "nper"):
        raise ValueError("Could not resolve stress-period count (nper) from flow model.")
    return int(getattr(flow_model, "nper"))


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
        if structured:
            return {sp: np.full((int(nrow), int(ncol)), scalar, dtype=float) for sp in range(1, nper)}
        return {sp: np.full(ncpl, scalar, dtype=float) for sp in range(1, nper)}

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
                normalized[stress_period] = np.full((int(nrow), int(ncol)), float(raw_array), dtype=float)
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
            overrides["sconc_init"] = np.full((nlay, nrow_hint, ncol_hint), float(sconc_init), dtype=float)
        else:
            overrides["sconc_init"] = np.full((nlay, ncpl), float(sconc_init), dtype=float)

    rate_decay = params.get("rate_decay")
    if _is_scalar_number(rate_decay):
        if structured:
            overrides["rate_decay"] = np.full((nlay, nrow_hint, ncol_hint), float(rate_decay), dtype=float)
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
