"""MF6 boundary-condition builders (CHD, DRN, side/ocean/stream support)."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real

import numpy as np

from hydromodpy.core.units import (
    convert_payload_to_m,
    factor_to_m2_per_s,
    normalize_length_unit,
)
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing


def is_scalar_number(value: object) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def boundary_conditions_mapping(model) -> Mapping[str, object]:
    boundary_conditions = getattr(model.flow, "boundary_conditions", {})
    if not isinstance(boundary_conditions, Mapping):
        raise TypeError("flow.boundary_conditions must be a mapping")
    return boundary_conditions


def boundary_attr(boundary: object, name: str, default=None):
    """Read one boundary attribute from either a mapping or a typed payload."""
    if isinstance(boundary, Mapping):
        return boundary.get(name, default)
    return getattr(boundary, name, default)


def is_bc_active(model, bc_id: str) -> bool:
    active = getattr(model.flow, "active_bc", [])
    return bc_id in active


def boundary_period_series(model, *, value: object, label: str) -> np.ndarray:
    nper = int(model.nper)
    if is_scalar_number(value):
        return np.full((nper,), float(value), dtype=float)
    if not isinstance(value, (np.ndarray, list, tuple)):
        raise TypeError(f"{label} must be numeric or a sequence of numeric values")
    series = np.asarray(value, dtype=float).reshape(-1)
    if series.size == 0:
        raise ValueError(f"{label} cannot be empty when using time series")
    if series.size == 1:
        return np.full((nper,), float(series[0]), dtype=float)
    if series.size != nper:
        raise ValueError(f"{label} length ({series.size}) must be 1 or match nper ({nper})")
    return series.astype(float)


def coerce_length_series_to_m(*, values: object, units: object, label: str) -> np.ndarray:
    source_units = normalize_length_unit(str(units).strip() or "m")
    return np.asarray(
        convert_payload_to_m(values, unit=source_units, label=label),
        dtype=float,
    )


def forcing_units(forcing: object, *, fallback: object) -> object:
    if isinstance(forcing, Mapping):
        return forcing.get("units", fallback)
    return getattr(forcing, "units", fallback)


def coerce_conductance_series_to_m2_per_s(
    *,
    values: object,
    units: object,
    label: str,
) -> np.ndarray:
    factor = factor_to_m2_per_s(str(units).strip() or "m2/s")
    return np.asarray(values, dtype=float) * float(factor)


def boundary_start_value(model, *, value: object, label: str) -> float:
    return float(boundary_period_series(model, value=value, label=label)[0])


def resolve_side_boundary_series(model, *, boundary: object, bc_id: str) -> np.ndarray:
    forcing = boundary_attr(boundary, "forcing", None)
    if forcing is not None:
        raw_values = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=None if model.time_grid is None else model.time_grid.window,
            nper=int(model.nper),
            label=f"flow.bc.{bc_id}.forcing",
        )
        return coerce_length_series_to_m(
            values=raw_values,
            units=forcing_units(forcing, fallback=boundary_attr(boundary, "units", "m")),
            label=f"flow.bc.{bc_id}.forcing",
        )
    return coerce_length_series_to_m(
        values=boundary_period_series(
            model,
            value=boundary_attr(boundary, "value", None),
            label=f"flow.bc.{bc_id}.value",
        ),
        units=boundary_attr(boundary, "units", "m"),
        label=f"flow.bc.{bc_id}.value",
    )


def _require_runtime_mesh_support(model, *, label: str) -> object:
    support = getattr(model, "runtime_mesh_support", None)
    if support is None:
        raise ValueError(
            f"{label} requires runtime gmsh support metadata but mesh_support is unavailable."
        )
    return support


def boundary_support_cell_ids(model, *, boundary: object, bc_id: str) -> list[int]:
    """Return flat cell ids selected by one BC support definition."""
    solver_mesh = getattr(model, "solver_mesh", None)
    support_label = boundary_attr(boundary, "support_label", None)
    if support_label is not None and not (
        solver_mesh is None or getattr(solver_mesh, "is_structured", False)
    ):
        support = _require_runtime_mesh_support(model, label=f"flow.bc.{bc_id}")
        cell_ids = support.cell_indices_for_label(str(support_label))
        if cell_ids.size == 0:
            raise ValueError(
                f"flow.bc.{bc_id}.support_label='{support_label}' did not match any "
                "runtime mesh support."
            )
        return [int(cell_id) for cell_id in cell_ids.tolist()]
    return side_boundary_cell_ids(model, bc_id)


def side_boundary_cell_ids(model, bc_id: str) -> list[int]:
    """Return flat cell IDs touched by one side boundary."""
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None or getattr(solver_mesh, "is_structured", False):
        nrow, ncol = int(model.nrow), int(model.ncol)
        if bc_id == "west_side":
            return [i * ncol for i in range(nrow)]
        if bc_id == "east_side":
            return [i * ncol + (ncol - 1) for i in range(nrow)]
        if bc_id == "north_side":
            return list(range(ncol))
        if bc_id == "south_side":
            return list(range((nrow - 1) * ncol, nrow * ncol))
        raise ValueError(f"Unsupported side boundary id: {bc_id}")

    support = _require_runtime_mesh_support(model, label=f"flow.bc.{bc_id}")
    return [int(cell_id) for cell_id in support.boundary_cell_indices_for_side(bc_id).tolist()]


def iter_side_boundary_cells(model, bc_id: str):
    """Yield (lay, cell_id) tuples for DISV boundary cells."""
    cell_ids = side_boundary_cell_ids(model, bc_id)
    for ilay in range(int(model.nlay)):
        for cid in cell_ids:
            yield ilay, cid


def apply_side_boundary_start_heads(model, strt: np.ndarray) -> np.ndarray:
    """Apply side boundary start heads on flat (nlay, ncpl) strt array."""
    bc = boundary_conditions_mapping(model)
    for bc_id in ("west_side", "east_side", "north_side", "south_side"):
        if not is_bc_active(model, bc_id):
            continue
        boundary = bc.get(bc_id)
        if boundary is None:
            continue
        start_value = float(resolve_side_boundary_series(model, boundary=boundary, bc_id=bc_id)[0])
        cell_ids = boundary_support_cell_ids(model, boundary=boundary, bc_id=bc_id)
        for ilay in range(strt.shape[0]):
            strt[ilay, cell_ids] = start_value
    return strt


def resolve_ocean_boundary_series(model) -> np.ndarray | None:
    if not is_bc_active(model, "ocean"):
        return None
    boundary = boundary_conditions_mapping(model).get("ocean")
    if boundary is None:
        return None
    forcing = boundary_attr(boundary, "forcing", None)
    if forcing is not None:
        raw_values = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=None if model.time_grid is None else model.time_grid.window,
            nper=int(model.nper),
            label="flow.bc.ocean.forcing",
        )
        return coerce_length_series_to_m(
            values=raw_values,
            units=forcing_units(forcing, fallback=boundary_attr(boundary, "units", "m")),
            label="flow.bc.ocean.forcing",
        )
    return coerce_length_series_to_m(
        values=boundary_period_series(
            model,
            value=boundary_attr(boundary, "value", None),
            label="flow.bc.ocean.value",
        ),
        units=boundary_attr(boundary, "units", "m"),
        label="flow.bc.ocean.value",
    )


def resolve_stream_boundary_series(model) -> np.ndarray | None:
    if not is_bc_active(model, "stream"):
        return None
    boundary = boundary_conditions_mapping(model).get("stream")
    if boundary is None:
        return None
    forcing = boundary_attr(boundary, "forcing", None)
    if forcing is not None:
        raw_values = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=None if model.time_grid is None else model.time_grid.window,
            nper=int(model.nper),
            label="flow.bc.stream.forcing",
        )
        return coerce_length_series_to_m(
            values=raw_values,
            units=forcing_units(forcing, fallback=boundary_attr(boundary, "units", "m")),
            label="flow.bc.stream.forcing",
        )
    return coerce_length_series_to_m(
        values=boundary_period_series(
            model,
            value=boundary_attr(boundary, "value", None),
            label="flow.bc.stream.value",
        ),
        units=boundary_attr(boundary, "units", "m"),
        label="flow.bc.stream.value",
    )


def ocean_chd_support_mask(model, ocean_series: np.ndarray | None) -> np.ndarray:
    """Return flat (ncpl,) boolean mask for ocean CHD cells."""
    if ocean_series is None or np.asarray(ocean_series, dtype=float).size == 0:
        return np.zeros(int(model.ncpl), dtype=bool)
    sea_threshold = float(np.max(np.asarray(ocean_series, dtype=float)))
    dem_flat = np.asarray(model.dem, dtype=float).reshape(-1)
    mask_flat = np.asarray(model.dem_mask, dtype=bool).reshape(-1)
    return (~mask_flat) & (dem_flat <= sea_threshold)


def build_ocean_boundary_chd_spd(
    model,
) -> tuple[dict[int, list[list[float]]], np.ndarray]:
    ocean_series = resolve_ocean_boundary_series(model)
    mask = ocean_chd_support_mask(model, ocean_series)
    spd: dict[int, list[list[float]]] = {kper: [] for kper in range(int(model.nper))}
    if ocean_series is None or not np.any(mask):
        return spd, mask

    cell_ids = np.where(mask)[0]
    for kper, head in enumerate(np.asarray(ocean_series, dtype=float)):
        period_cells: list[list[float]] = []
        for ilay in range(int(model.nlay)):
            for cid in cell_ids.tolist():
                period_cells.append([ilay, cid, float(head)])
        spd[kper] = period_cells
    return spd, mask


def stream_chd_support_mask(model, stream_series: np.ndarray | None) -> np.ndarray:
    """Return flat (ncpl,) boolean mask for stream CHD cells."""
    if stream_series is None or np.asarray(stream_series, dtype=float).size == 0:
        return np.zeros(int(model.ncpl), dtype=bool)
    boundary = boundary_conditions_mapping(model).get("stream")
    support = _require_runtime_mesh_support(model, label="flow.bc.stream")
    support_label = None if boundary is None else boundary_attr(boundary, "support_label", None)
    if support_label is None:
        cell_ids = np.asarray(support.river_cell_indices(), dtype=int).reshape(-1)
    else:
        cell_ids = np.asarray(
            support.cell_indices_for_label(str(support_label)), dtype=int
        ).reshape(-1)
    if cell_ids.size == 0:
        raise ValueError(
            "Boundary 'stream' is active but its selected runtime mesh support is empty."
        )
    mask = np.zeros(int(model.ncpl), dtype=bool)
    mask[cell_ids] = True
    return mask


def build_stream_boundary_chd_spd(
    model,
) -> tuple[dict[int, list[list[float]]], np.ndarray]:
    stream_series = resolve_stream_boundary_series(model)
    mask = stream_chd_support_mask(model, stream_series)
    spd: dict[int, list[list[float]]] = {kper: [] for kper in range(int(model.nper))}
    if stream_series is None or not np.any(mask):
        return spd, mask

    cell_ids = np.where(mask)[0]
    for kper, head in enumerate(np.asarray(stream_series, dtype=float)):
        period_cells: list[list[float]] = []
        for ilay in range(int(model.nlay)):
            for cid in cell_ids.tolist():
                period_cells.append([ilay, cid, float(head)])
        spd[kper] = period_cells
    return spd, mask


def build_side_boundary_chd_spd(model) -> dict[int, list[list[float]]]:
    bc = boundary_conditions_mapping(model)
    dem_mask_flat = np.asarray(model.dem_mask, dtype=bool).reshape(-1)
    spd: dict[int, dict[tuple[int, int], list[float]]] = {
        kper: {} for kper in range(int(model.nper))
    }
    for bc_id in ("west_side", "east_side", "north_side", "south_side"):
        if not is_bc_active(model, bc_id):
            continue
        boundary = bc.get(bc_id)
        if boundary is None:
            continue
        series = resolve_side_boundary_series(model, boundary=boundary, bc_id=bc_id)
        for kper, head in enumerate(series):
            for ilay in range(int(model.nlay)):
                for cid in boundary_support_cell_ids(model, boundary=boundary, bc_id=bc_id):
                    if bool(dem_mask_flat[cid]):
                        continue
                    spd[kper][(ilay, cid)] = [ilay, cid, float(head)]
    return {kper: list(period_map.values()) for kper, period_map in spd.items()}


def resolve_drainage_conductance_series(model) -> np.ndarray | None:
    if not is_bc_active(model, "drainage"):
        return None
    boundary = boundary_conditions_mapping(model).get("drainage")
    if boundary is None:
        return None
    forcing = getattr(boundary, "forcing", None)
    if forcing is not None:
        raw_values = resolve_period_values_from_forcing(
            forcing=forcing,
            simulation_window=None if model.time_grid is None else model.time_grid.window,
            nper=int(model.nper),
            label="flow.bc.drainage.forcing",
        )
        return coerce_conductance_series_to_m2_per_s(
            values=raw_values,
            units=forcing_units(forcing, fallback=getattr(boundary, "units", "m2/s")),
            label="flow.bc.drainage.forcing",
        )
    return coerce_conductance_series_to_m2_per_s(
        values=boundary_period_series(
            model,
            value=getattr(boundary, "value", None),
            label="flow.bc.drainage.value",
        ),
        units=getattr(boundary, "units", "m2/s"),
        label="flow.bc.drainage.value",
    )


def build_drain_stress_period_data(
    model,
    *,
    solver_mesh,
    drainage_cond_series: np.ndarray,
    ocean_support_mask: np.ndarray,
    stream_support_mask: np.ndarray,
) -> dict[int, list[list[float]]]:
    """Build DRN stress-period data, including hk-scaled fallback conductance."""
    drn_spd: dict[int, list[list[float]]] = {}
    top_flat = solver_mesh.top
    dem_mask_flat = np.asarray(model.dem_mask, dtype=bool).reshape(-1)
    ocean_mask_flat = np.asarray(ocean_support_mask, dtype=bool).reshape(-1)
    stream_mask_flat = np.asarray(stream_support_mask, dtype=bool).reshape(-1)
    cell_areas = solver_mesh.cell_areas()
    for kper in range(int(model.nper)):
        period_cells: list[list[float]] = []
        configured_cond_value = float(drainage_cond_series[kper])
        for cid in range(int(model.ncpl)):
            if dem_mask_flat[cid] or ocean_mask_flat[cid] or stream_mask_flat[cid]:
                continue
            if configured_cond_value > 0.0:
                cond_value = max(configured_cond_value, 1e-12)
            else:
                cond_value = max(float(model.hk[0, cid]) * float(cell_areas[cid]), 1e-12)
            period_cells.append([0, cid, float(top_flat[cid]), cond_value])
        drn_spd[kper] = period_cells
    return drn_spd


# Re-exported for the recharge/EVT builder which needs Real-aware coercion.
__all__ = [
    "Real",
    "apply_side_boundary_start_heads",
    "boundary_attr",
    "boundary_conditions_mapping",
    "boundary_period_series",
    "boundary_start_value",
    "boundary_support_cell_ids",
    "build_drain_stress_period_data",
    "build_ocean_boundary_chd_spd",
    "build_side_boundary_chd_spd",
    "build_stream_boundary_chd_spd",
    "coerce_conductance_series_to_m2_per_s",
    "coerce_length_series_to_m",
    "forcing_units",
    "is_bc_active",
    "is_scalar_number",
    "iter_side_boundary_cells",
    "ocean_chd_support_mask",
    "resolve_drainage_conductance_series",
    "resolve_ocean_boundary_series",
    "resolve_side_boundary_series",
    "resolve_stream_boundary_series",
    "side_boundary_cell_ids",
    "stream_chd_support_mask",
]
