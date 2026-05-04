"""CHD-related payload builders for the NWT flow-to-modflow adapter.

This module is private to the NWT package. Functions take an explicit adapter
context (the FlowToModflowAdapter instance) and return the corresponding
solver-side payloads. They never instantiate FLOPY packages.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.core.units import convert_payload_to_m, normalize_length_unit
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_nwt.nwt.flow_to_modflow_adapter import (
        FlowToModflowAdapter,
    )


def is_scalar_number(value: object) -> bool:
    """Return True for numeric scalar values (excluding booleans)."""
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def normalize_boundary_series(
    *,
    value: object,
    label: str,
    nper: int,
) -> np.ndarray | None:
    """Normalize one boundary value payload to an ``nper`` series when needed."""
    if is_scalar_number(value):
        return None
    if not isinstance(value, (np.ndarray, pd.Series, list, tuple)):
        raise TypeError(f"{label} must be numeric or a sequence of numeric values")

    series = np.asarray(value, dtype=float).reshape(-1)
    if series.size == 0:
        raise ValueError(f"{label} cannot be empty when using time series")
    if series.size == 1:
        return np.full(nper, float(series[0]), dtype=float)
    if series.size != nper:
        raise ValueError(f"{label} length ({series.size}) must be 1 or match nper ({nper})")
    return series.astype(float)


def coerce_length_series_to_m(
    *,
    values: object,
    units: object,
    label: str,
) -> np.ndarray:
    """Convert one length payload to metres."""
    source_units = normalize_length_unit(str(units).strip() or "m")
    return np.asarray(
        convert_payload_to_m(values, unit=source_units, label=label),
        dtype=float,
    )


def forcing_units(forcing: object, *, fallback: object) -> object:
    """Return the units field from one forcing object/Mapping."""
    if isinstance(forcing, Mapping):
        return forcing.get("units", fallback)
    return getattr(forcing, "units", fallback)


def resolve_side_boundary_series(
    adapter: FlowToModflowAdapter,
    *,
    boundary: object,
    bc_id: str,
) -> np.ndarray:
    """Resolve one lateral boundary payload to one value per stress period."""
    forcing = getattr(boundary, "forcing", None)
    label = f"flow.bc.{bc_id}.forcing"
    if forcing is not None:
        raw_values = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=adapter.simulation_window,
            nper=adapter.nper,
            label=label,
        )
        return coerce_length_series_to_m(
            values=raw_values,
            units=forcing_units(
                forcing,
                fallback=getattr(boundary, "units", "m"),
            ),
            label=label,
        )

    value = getattr(boundary, "value", None)
    value_label = f"flow.bc.{bc_id}.value"
    series = normalize_boundary_series(
        value=value,
        label=value_label,
        nper=adapter.nper,
    )
    if series is None:
        series = np.full(adapter.nper, float(value), dtype=float)
    return coerce_length_series_to_m(
        values=series,
        units=getattr(boundary, "units", "m"),
        label=value_label,
    )


def side_boundary_is_static(boundary: object) -> bool:
    """Return True only for direct scalar ``value`` side boundaries."""
    return getattr(boundary, "forcing", None) is None and is_scalar_number(
        getattr(boundary, "value", None)
    )


def build_initial_heads_and_sides(
    adapter: FlowToModflowAdapter,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build startup ``ibound`` and ``strt`` arrays from flow IC + side BCs."""
    ibound = np.ones((adapter.nlay, adapter.nrow, adapter.ncol), dtype=float)

    initial_conditions = getattr(adapter.flow, "initial_conditions", None)
    initial_condition = (
        None if initial_conditions is None else getattr(initial_conditions, "h", None)
    )
    if initial_condition is None:
        raise ValueError("flow.initial_conditions.h is required for MODFLOW startup")

    initial_type = str(getattr(initial_condition, "type", "")).strip().lower()
    if initial_type == "top":
        strt = np.ones((adapter.nlay, adapter.nrow, adapter.ncol), dtype=float) * adapter.dem
    elif initial_type == "top_offset":
        head_value = initial_condition.value
        if head_value is None:
            raise ValueError("flow.initial_conditions.h.value is required for top_offset")
        offset_m = float(getattr(head_value, "magnitude", head_value))
        strt = np.ones((adapter.nlay, adapter.nrow, adapter.ncol), dtype=float) * (
            adapter.dem - offset_m
        )
    elif initial_type == "bottom":
        strt = (
            np.ones((adapter.nlay, adapter.nrow, adapter.ncol), dtype=float) * adapter.bottom_layer
        )
    elif initial_type == "custom":
        head_value = initial_condition.value
        head_magnitude = getattr(head_value, "magnitude", head_value)
        strt = np.ones((adapter.nlay, adapter.nrow, adapter.ncol), dtype=float) * float(
            head_magnitude
        )
    else:
        raise ValueError(
            "flow.initial_conditions.h.type must be one of: top, top_offset, bottom, custom"
        )

    boundary_conditions = adapter._boundary_conditions
    west_side = boundary_conditions.get("west_side") if adapter._is_bc_active("west_side") else None
    if west_side is not None:
        west_series = resolve_side_boundary_series(adapter, boundary=west_side, bc_id="west_side")
        if side_boundary_is_static(west_side):
            ibound[:, :, 0] = -1
        strt[:, :, 0] = float(west_series[0])

    east_side = boundary_conditions.get("east_side") if adapter._is_bc_active("east_side") else None
    if east_side is not None:
        east_series = resolve_side_boundary_series(adapter, boundary=east_side, bc_id="east_side")
        if side_boundary_is_static(east_side):
            ibound[:, :, -1] = -1
        strt[:, :, -1] = float(east_series[0])

    north_side = (
        boundary_conditions.get("north_side") if adapter._is_bc_active("north_side") else None
    )
    if north_side is not None:
        north_series = resolve_side_boundary_series(
            adapter, boundary=north_side, bc_id="north_side"
        )
        if side_boundary_is_static(north_side):
            ibound[:, 0, :] = -1
        strt[:, 0, :] = float(north_series[0])

    south_side = (
        boundary_conditions.get("south_side") if adapter._is_bc_active("south_side") else None
    )
    if south_side is not None:
        south_series = resolve_side_boundary_series(
            adapter, boundary=south_side, bc_id="south_side"
        )
        if side_boundary_is_static(south_side):
            ibound[:, -1, :] = -1
        strt[:, -1, :] = float(south_series[0])

    for ilay in range(adapter.nlay):
        ibound[ilay][adapter.inactive_mask] = 0
        strt[ilay][adapter.inactive_mask] = 0.0

    drain_array = np.ones((adapter.nrow, adapter.ncol), dtype=float)
    drain_array[adapter.inactive_mask] = 0.0
    return ibound, strt, drain_array


def build_ocean_chd(
    adapter: FlowToModflowAdapter,
    *,
    ibound: np.ndarray,
    strt: np.ndarray,
    drain_array: np.ndarray,
) -> dict[int, list[list[float]]] | None:
    """Build CHD stress-period data for the ocean boundary when defined.

    Mutates ``ibound``, ``strt`` and ``drain_array`` in place when the ocean
    boundary is active.
    """
    if not adapter._is_bc_active("ocean"):
        return None
    ocean_boundary = adapter._boundary_conditions.get("ocean")
    if ocean_boundary is None:
        return None

    ocean_value = getattr(ocean_boundary, "value", None)
    if is_scalar_number(ocean_value):
        ocean_head_array = coerce_length_series_to_m(
            values=ocean_value,
            units=getattr(ocean_boundary, "units", "m"),
            label="flow.bc.ocean.value",
        )
        ocean_head = float(np.asarray(ocean_head_array, dtype=float).reshape(-1)[0])
        for ilay in range(adapter.nlay):
            ibound[ilay][adapter.dem <= ocean_head] = -1
        strt[ibound == -1] = ocean_head

    ocean_series = normalize_boundary_series(
        value=ocean_value,
        label="flow.bc.ocean.value",
        nper=adapter.nper,
    )
    if ocean_series is None:
        return None
    ocean_series = coerce_length_series_to_m(
        values=ocean_series,
        units=getattr(ocean_boundary, "units", "m"),
        label="flow.bc.ocean.value",
    )

    sea_threshold = float(np.max(ocean_series))
    rows, cols = np.nonzero((adapter.dem < sea_threshold) & (ibound[0] != 0))
    if rows.size:
        drain_array[rows, cols] = 0
    ocean_cells = [(int(row), int(col)) for row, col in zip(rows, cols, strict=False)]
    chd_spd: dict[int, list[list[float]]] = {}
    for kper in range(adapter.nper):
        kper_head = float(ocean_series[kper])
        chd_spd[kper] = [[0, i, j, kper_head, kper_head] for i, j in ocean_cells]
    return chd_spd


def iter_side_boundary_cells(
    adapter: FlowToModflowAdapter,
    bc_id: str,
) -> Iterator[tuple[int, int, int]]:
    """Yield solver cells belonging to one lateral model face."""
    if bc_id == "west_side":
        for ilay in range(adapter.nlay):
            for i in range(adapter.nrow):
                yield ilay, i, 0
        return
    if bc_id == "east_side":
        for ilay in range(adapter.nlay):
            for i in range(adapter.nrow):
                yield ilay, i, adapter.ncol - 1
        return
    if bc_id == "north_side":
        for ilay in range(adapter.nlay):
            for j in range(adapter.ncol):
                yield ilay, 0, j
        return
    if bc_id == "south_side":
        for ilay in range(adapter.nlay):
            for j in range(adapter.ncol):
                yield ilay, adapter.nrow - 1, j
        return
    raise ValueError(f"Unsupported side boundary id: {bc_id}")


def build_side_chd(
    adapter: FlowToModflowAdapter,
) -> dict[int, list[list[float]]] | None:
    """Build CHD stress-period data for transient lateral Dirichlet boundaries."""
    per_period: dict[int, dict[tuple[int, int, int], list[float]]] = {
        kper: {} for kper in range(adapter.nper)
    }
    has_entries = False

    for bc_id in ("west_side", "east_side", "north_side", "south_side"):
        if not adapter._is_bc_active(bc_id):
            continue
        boundary = adapter._boundary_conditions.get(bc_id)
        if boundary is None:
            continue
        if side_boundary_is_static(boundary):
            continue
        series = resolve_side_boundary_series(adapter, boundary=boundary, bc_id=bc_id)
        cells = [
            (ilay, row, col)
            for ilay, row, col in iter_side_boundary_cells(adapter, bc_id)
            if not adapter.inactive_mask[row, col]
        ]

        for kper, head in enumerate(series):
            for ilay, row, col in cells:
                per_period[kper][(ilay, row, col)] = [
                    ilay,
                    row,
                    col,
                    float(head),
                    float(head),
                ]
                has_entries = True

    if not has_entries:
        return None
    return {kper: list(cell_map.values()) for kper, cell_map in per_period.items()}


def merge_chd_payloads(
    nper: int,
    *payloads: dict[int, list[list[float]]] | None,
) -> dict[int, list[list[float]]] | None:
    """Merge CHD payloads with later inputs overriding earlier duplicate cells."""
    merged: dict[int, list[list[float]]] = {}
    has_entries = False

    for kper in range(nper):
        period_map: dict[tuple[int, int, int], list[float]] = {}
        for payload in payloads:
            if payload is None:
                continue
            for row in payload.get(kper, []):
                key = (int(row[0]), int(row[1]), int(row[2]))
                period_map[key] = list(row)
        merged[kper] = list(period_map.values())
        if merged[kper]:
            has_entries = True

    if not has_entries:
        return None
    return merged


def validate_ibound_strt_contract(
    *,
    nlay: int,
    nrow: int,
    ncol: int,
    ibound: np.ndarray,
    strt: np.ndarray,
    drain_array: np.ndarray,
) -> None:
    """Validate BAS-facing ``ibound``/``strt`` arrays before package assembly."""
    expected_3d = (nlay, nrow, ncol)
    expected_2d = (nrow, ncol)

    if ibound.shape != expected_3d:
        raise ValueError(f"ibound shape mismatch: expected {expected_3d}, got {ibound.shape}")
    if strt.shape != expected_3d:
        raise ValueError(f"strt shape mismatch: expected {expected_3d}, got {strt.shape}")
    if drain_array.shape != expected_2d:
        raise ValueError(
            f"drain_array shape mismatch: expected {expected_2d}, got {drain_array.shape}"
        )

    if not np.isfinite(ibound).all():
        raise ValueError("ibound contains non-finite values")
    if not np.isfinite(strt).all():
        raise ValueError("strt contains non-finite values")
    if not np.isfinite(drain_array).all():
        raise ValueError("drain_array contains non-finite values")

    drain_unique = np.unique(drain_array)
    if not np.isin(drain_unique, [0.0, 1.0]).all():
        raise ValueError("drain_array must only contain binary activation values {0, 1}")


__all__ = [
    "build_initial_heads_and_sides",
    "build_ocean_chd",
    "build_side_chd",
    "coerce_length_series_to_m",
    "forcing_units",
    "is_scalar_number",
    "iter_side_boundary_cells",
    "merge_chd_payloads",
    "normalize_boundary_series",
    "resolve_side_boundary_series",
    "side_boundary_is_static",
    "validate_ibound_strt_contract",
]
