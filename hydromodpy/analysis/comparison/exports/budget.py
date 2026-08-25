"""Budget CSV exports and boussinesq/MF6 budget loaders."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.analysis.comparison.runtime.mesh import resolve_bundle_cells
from hydromodpy.core.logging import get_logger
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.units.scalar import parse_scalar_and_unit
from hydromodpy.core.units.volumetric_flow import factor_to_m3_per_s
from hydromodpy.physics.flow.history_contract import build_transient_time_axes

from .base import (
    _as_float,
    _completed_simulation_summaries,
    _write_csv,
)

if TYPE_CHECKING:
    from hydromodpy.results.catalog import SimulationCatalog

logger = get_logger(__name__)


def _history_matrix(payload: Mapping[str, Any], key: str) -> np.ndarray | None:
    if key not in payload:
        return None
    values = np.asarray(payload[key], dtype=float)
    if values.ndim == 1:
        return values.reshape(1, -1)
    if values.ndim == 2:
        return values
    return None


def _budget_field_total_series(payload: Mapping[str, Any], key: str) -> np.ndarray | None:
    """Return a total m3/s series from a persisted budget field.

    Boussinesq stores canonical budget fields in the Zarr ``budget`` group as
    volumetric fluxes.  The first dimension is time; all other dimensions are
    spatial/support dimensions that can be summed for a basin-scale balance.
    """
    if key not in payload:
        return None
    values = np.asarray(payload[key], dtype=float)
    if values.ndim == 0:
        return None
    if values.ndim == 1:
        return values.reshape(-1)
    matrix = values.reshape(int(values.shape[0]), -1)
    return np.nansum(matrix, axis=1, dtype=float)


def _residual_total_series_m3_s(
    values: np.ndarray | None,
    *,
    n_snapshots: int,
) -> np.ndarray | None:
    if values is None or values.ndim != 2 or values.shape[0] != int(n_snapshots):
        return None
    return np.nansum(values, axis=1, dtype=float)


def _all_finite_zero(values: np.ndarray | None) -> bool:
    if values is None:
        return False
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    return bool(finite.size > 0 and np.allclose(finite, 0.0))


def _saturated_thickness_from_head_history(
    *,
    head_history_m: np.ndarray | None,
    z_top_m: np.ndarray | None,
    z_bottom_m: np.ndarray | None,
) -> np.ndarray | None:
    if head_history_m is None or z_top_m is None or z_bottom_m is None:
        return None
    head = np.asarray(head_history_m, dtype=float)
    if head.ndim != 2:
        return None
    z_top = np.asarray(z_top_m, dtype=float).reshape(-1)
    z_bottom = np.asarray(z_bottom_m, dtype=float).reshape(-1)
    if not (head.shape[1] == z_top.size == z_bottom.size):
        return None
    aquifer_thickness = np.maximum(z_top - z_bottom, 0.0)
    return np.clip(head - z_bottom[None, :], 0.0, aquifer_thickness[None, :])


def _elapsed_seconds_axis(period_lengths: np.ndarray, *, n_snapshots: int) -> np.ndarray:
    if n_snapshots <= 0:
        return np.asarray([], dtype=float)
    if period_lengths.size == n_snapshots - 1:
        elapsed = np.concatenate(
            (np.asarray([0.0], dtype=float), np.cumsum(period_lengths, dtype=float))
        )
        return np.asarray(elapsed, dtype=float)
    if period_lengths.size == n_snapshots:
        return np.asarray(np.cumsum(period_lengths, dtype=float), dtype=float)
    return np.arange(n_snapshots, dtype=float)


def _is_degenerate_time_axis(values: np.ndarray) -> bool:
    return int(values.size) > 1 and bool(np.allclose(values, values[0]))


def _period_lengths_from_root_time(
    payload: Mapping[str, Any],
    *,
    n_snapshots: int,
) -> np.ndarray | None:
    if "time" not in payload:
        return None
    try:
        root_time = np.asarray(payload["time"], dtype=float).reshape(-1)
    except Exception:
        return None
    if root_time.size != int(n_snapshots) or _is_degenerate_time_axis(root_time):
        return None
    lengths = np.diff(root_time)
    if lengths.size != int(n_snapshots) - 1:
        return None
    if not np.all(np.isfinite(lengths)) or np.any(lengths <= 0.0):
        return None
    return np.asarray(lengths, dtype=float)


def _budget_period_metadata(
    *,
    elapsed_seconds: np.ndarray,
    period_lengths_seconds: np.ndarray,
    n_snapshots: int,
    time_index: int,
) -> tuple[int, float, float] | None:
    """Return period index and bounds for one budget row.

    Boussinesq histories may include an explicit initial state at index 0.
    Budgets are interval values, so that initial state is not a budget period.
    """
    has_initial_state = period_lengths_seconds.size == n_snapshots - 1
    if has_initial_state:
        if time_index <= 0:
            return None
        period_index = time_index - 1
        period_start = float(elapsed_seconds[time_index - 1])
        period_end = float(elapsed_seconds[time_index])
        return period_index, period_start, period_end

    period_index = time_index
    period_end = (
        float(elapsed_seconds[time_index])
        if time_index < int(elapsed_seconds.size)
        else float(time_index)
    )
    if time_index > 0 and time_index - 1 < int(elapsed_seconds.size):
        period_start = float(elapsed_seconds[time_index - 1])
    elif period_lengths_seconds.size > 0:
        period_start = period_end - float(period_lengths_seconds[0])
    else:
        period_start = 0.0
    return period_index, period_start, period_end


def _namespace_from_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return SimpleNamespace(
            **{str(key): _namespace_from_mapping(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return [_namespace_from_mapping(item) for item in value]
    return value


def _step_end_elapsed_seconds_from_config(
    config_path: Path | None,
    *,
    n_steps: int,
) -> np.ndarray:
    if config_path is None or n_steps <= 0:
        return np.arange(max(n_steps, 0), dtype=float)
    try:
        from hydromodpy.core.time import resolve_simulation_time_grid

        payload = load_toml_with_base_config(config_path)
        grid = resolve_simulation_time_grid(_namespace_from_mapping(payload))
    except Exception:
        return np.arange(n_steps, dtype=float)
    if grid is None:
        return np.arange(n_steps, dtype=float)
    axes = build_transient_time_axes(grid.period_lengths_seconds)
    if axes.n_steps == n_steps:
        return np.asarray(axes.step_end_elapsed_seconds, dtype=float)
    return np.arange(n_steps, dtype=float)


def _homogeneous_sy_from_config(config_path: Path | None) -> float | None:
    """Read a homogeneous `Sy` value from one generated simulation config."""
    if config_path is None:
        return None
    try:
        payload = load_toml_with_base_config(config_path)
    except Exception:
        return None
    flow = payload.get("flow")
    if not isinstance(flow, Mapping):
        return None
    params = flow.get("param")
    if not isinstance(params, Mapping):
        return None
    sy_payload = params.get("Sy") or params.get("sy") or params.get("S") or params.get("s")
    if not isinstance(sy_payload, Mapping):
        return None

    candidates: list[Any] = []
    field = sy_payload.get("field")
    if isinstance(field, Mapping) and "value" in field:
        candidates.append(field.get("value"))
    if "value" in sy_payload:
        candidates.append(sy_payload.get("value"))

    for candidate in candidates:
        try:
            scalar, _ = parse_scalar_and_unit(
                candidate,
                default_unit="-",
                location="flow.param.Sy",
            )
            value = float(scalar)
        except Exception:
            continue
        if math.isfinite(value):
            return value
    return None


def _flux_factor_to_m3_s(unit: str) -> float:
    """Return a factor to normalize a volumetric budget unit to m3/s."""
    text = str(unit or "m3/s").strip()
    if text == "":
        return 1.0
    try:
        return float(factor_to_m3_per_s(text))
    except Exception:
        return 1.0


def _catalog_budget_factor_to_m3_s(*, solver: str, unit: str) -> float:
    """Return the catalog budget conversion factor for one solver row."""
    unit_text = str(unit or "").strip().lower()
    solver_key = str(solver or "").strip().lower()
    if solver_key == "modflow6" and unit_text in {"m3/d", "m3/day", "m^3/day"}:
        return 1.0
    return _flux_factor_to_m3_s(unit)


def _storage_change_series_m3_s(
    *,
    head_history_m: np.ndarray | None,
    saturated_thickness_history_m: np.ndarray | None,
    area_m2: np.ndarray | None,
    storage_coefficient: np.ndarray | None,
    period_lengths_seconds: np.ndarray,
) -> np.ndarray | None:
    if (
        head_history_m is None
        or area_m2 is None
        or storage_coefficient is None
        or head_history_m.ndim != 2
    ):
        return None
    if not (head_history_m.shape[1] == area_m2.size == storage_coefficient.size):
        return None
    storage_state_m = head_history_m
    if (
        saturated_thickness_history_m is not None
        and saturated_thickness_history_m.ndim == 2
        and saturated_thickness_history_m.shape == head_history_m.shape
    ):
        storage_state_m = saturated_thickness_history_m

    n_snapshots = int(storage_state_m.shape[0])
    storage_change = np.full(n_snapshots, np.nan, dtype=float)
    if n_snapshots == 0:
        return storage_change

    if period_lengths_seconds.size == n_snapshots - 1:
        storage_change[0] = 0.0
        for index in range(1, n_snapshots):
            dt_seconds = float(period_lengths_seconds[index - 1])
            if dt_seconds <= 0.0 or not math.isfinite(dt_seconds):
                continue
            delta_storage_state_m = storage_state_m[index] - storage_state_m[index - 1]
            storage_change[index] = float(
                np.nansum(area_m2 * storage_coefficient * delta_storage_state_m) / dt_seconds
            )
        return storage_change

    if period_lengths_seconds.size == n_snapshots:
        storage_change[0] = 0.0
        for index in range(1, n_snapshots):
            dt_seconds = float(period_lengths_seconds[index])
            if dt_seconds <= 0.0 or not math.isfinite(dt_seconds):
                continue
            delta_storage_state_m = storage_state_m[index] - storage_state_m[index - 1]
            storage_change[index] = float(
                np.nansum(area_m2 * storage_coefficient * delta_storage_state_m) / dt_seconds
            )
        return storage_change

    return None


def _load_boussinesq_state_from_store(
    store: SimulationCatalog,
    sim_id: str,
) -> Mapping[str, Any] | None:
    """Try reading Boussinesq state arrays from the SimulationCatalog Zarr group.

    Returns a dict-like mapping of array names to numpy arrays (same
    interface as ``np.load(...)``), or ``None`` if unavailable.
    """
    sz = None
    try:
        sz = store.open_zarr(sim_id)
        grp = sz.root
    except (KeyError, Exception):
        return None

    try:
        state_grp = grp.get("boussinesq_state")
        if state_grp is None:
            return None
        result: dict[str, np.ndarray] = {}
        for key in state_grp:
            result[key] = np.asarray(state_grp[key][:])
        if "time" in grp:
            result["time"] = np.asarray(grp["time"][:])
        budget_grp = grp.get("budget")
        if budget_grp is not None:
            budget_field_names = {
                "recharge": "budget_recharge_m3_s",
                "well": "budget_well_m3_s",
                "drain": "budget_drainage_m3_s",
                "surface_excess": "budget_surface_excess_m3_s",
            }
            for source_name, target_name in budget_field_names.items():
                if source_name in budget_grp:
                    result[target_name] = np.asarray(budget_grp[source_name][:])
    except Exception:
        return None
    finally:
        if sz is not None:
            sz.close()

    return result if result else None


def _load_boussinesq_payload(
    summary: Mapping[str, Any],
    store: SimulationCatalog | None,
    sim_id: str | None,
    run_folder: Path,
) -> tuple[Mapping[str, Any] | None, str]:
    """Resolve the Boussinesq state payload from the catalog or the npz sidecar."""
    if store is not None and sim_id is not None:
        payload = _load_boussinesq_state_from_store(store, sim_id)
        if payload is not None:
            logger.debug(
                "Loaded Boussinesq state from SimulationCatalog for budget (sim_id=%s).",
                sim_id,
            )
            return payload, f"SimulationCatalog(sim_id={sim_id})"

    npz_path = run_folder / "_boussinesq_state_history.npz"
    if not npz_path.exists():
        return None, ""
    return np.load(npz_path, allow_pickle=True), str(npz_path)


def _boussinesq_history_arrays(payload: Mapping[str, Any]) -> dict[str, np.ndarray | None]:
    """Read every named history / budget-total array from the Boussinesq payload."""
    return {
        "recharge_history": _history_matrix(payload, "recharge_rate_history_m_s"),
        "well_history": _history_matrix(payload, "well_flux_history_m3_s"),
        "drainage_history": _history_matrix(payload, "drainage_flux_history_m3_s"),
        "surface_history": _history_matrix(payload, "saturation_excess_history_m_s"),
        "dry_deficit_history": _history_matrix(payload, "dry_deficit_history_m_s"),
        "prescribed_head_history": _history_matrix(payload, "prescribed_head_flux_history_m3_s"),
        "head_history": _history_matrix(payload, "head_history_m"),
        "saturated_thickness_history": _history_matrix(payload, "saturated_thickness_history_m"),
        "residual_history": _history_matrix(payload, "residual_history_m3_s"),
        "budget_recharge_total": _budget_field_total_series(payload, "budget_recharge_m3_s"),
        "budget_well_total": _budget_field_total_series(payload, "budget_well_m3_s"),
        "budget_drainage_total": _budget_field_total_series(payload, "budget_drainage_m3_s"),
        "budget_surface_excess_total": _budget_field_total_series(
            payload, "budget_surface_excess_m3_s"
        ),
    }


def _boussinesq_component_series(
    payload: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray | None],
    *,
    run_folder: Path,
    config_path: Path | None,
) -> tuple[int, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Build every budget component series (m3/s) for one Boussinesq run.

    Returns ``(n_snapshots, elapsed_seconds, period_lengths,
    component_series)``. ``n_snapshots`` is 0 when no history array carries
    any snapshot, in which case the other values are empty.
    """
    recharge_history = arrays["recharge_history"]
    well_history = arrays["well_history"]
    drainage_history = arrays["drainage_history"]
    surface_history = arrays["surface_history"]
    dry_deficit_history = arrays["dry_deficit_history"]
    prescribed_head_history = arrays["prescribed_head_history"]
    head_history = arrays["head_history"]
    saturated_thickness_history = arrays["saturated_thickness_history"]
    residual_history = arrays["residual_history"]
    budget_recharge_total = arrays["budget_recharge_total"]
    budget_well_total = arrays["budget_well_total"]
    budget_drainage_total = arrays["budget_drainage_total"]
    budget_surface_excess_total = arrays["budget_surface_excess_total"]

    n_snapshots = max(
        (
            int(matrix.shape[0])
            for matrix in (
                recharge_history,
                well_history,
                drainage_history,
                surface_history,
                dry_deficit_history,
                prescribed_head_history,
                head_history,
                saturated_thickness_history,
                residual_history,
                budget_recharge_total,
                budget_well_total,
                budget_drainage_total,
                budget_surface_excess_total,
            )
            if matrix is not None
        ),
        default=0,
    )
    if n_snapshots <= 0:
        return 0, np.asarray([], dtype=float), np.asarray([], dtype=float), {}

    area_m2: np.ndarray | None = None
    storage_coefficient: np.ndarray | None = None
    n_cells = next(
        (
            int(matrix.shape[1])
            for matrix in (
                recharge_history,
                well_history,
                drainage_history,
                surface_history,
                dry_deficit_history,
                prescribed_head_history,
                head_history,
                saturated_thickness_history,
                residual_history,
            )
            if matrix is not None and matrix.ndim == 2
        ),
        0,
    )
    if n_cells > 0:
        # Boussinesq has no structured-grid TOML section, so solver_name is
        # dropped: the function falls back to the exchange-bundle path.
        cells = resolve_bundle_cells(
            run_folder,
            config_path=config_path,
            expected_size=n_cells,
        )
        if cells is not None:
            if cells.area_m2 is not None:
                area_m2 = np.asarray(cells.area_m2, dtype=float).reshape(-1)
            if cells.storage_coefficient is not None:
                storage_coefficient = np.asarray(
                    cells.storage_coefficient,
                    dtype=float,
                ).reshape(-1)
            elif (sy_value := _homogeneous_sy_from_config(config_path)) is not None:
                storage_coefficient = np.full(n_cells, sy_value, dtype=float)

    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    if _is_degenerate_time_axis(period_lengths):
        fallback_lengths = _period_lengths_from_root_time(
            payload,
            n_snapshots=n_snapshots,
        )
        if fallback_lengths is not None:
            period_lengths = fallback_lengths
    elapsed_seconds = _elapsed_seconds_axis(
        period_lengths,
        n_snapshots=n_snapshots,
    )

    component_series: dict[str, np.ndarray] = {}
    residual_total = _residual_total_series_m3_s(
        residual_history,
        n_snapshots=n_snapshots,
    )
    if residual_total is not None:
        component_series["closure_residual_m3_s"] = residual_total

    if budget_recharge_total is not None and budget_recharge_total.size == n_snapshots:
        component_series["recharge_total_m3_s"] = budget_recharge_total
    elif (
        recharge_history is not None
        and area_m2 is not None
        and recharge_history.shape[1] == area_m2.size
    ):
        component_series["recharge_total_m3_s"] = np.sum(
            recharge_history * area_m2[None, :],
            axis=1,
            dtype=float,
        )
    if budget_well_total is not None and budget_well_total.size == n_snapshots:
        component_series["well_total_m3_s"] = budget_well_total
    elif well_history is not None:
        component_series["well_total_m3_s"] = np.sum(well_history, axis=1, dtype=float)
    if budget_drainage_total is not None and budget_drainage_total.size == n_snapshots:
        component_series["drainage_total_m3_s"] = budget_drainage_total
    elif drainage_history is not None:
        component_series["drainage_total_m3_s"] = np.sum(
            drainage_history,
            axis=1,
            dtype=float,
        )
    if budget_surface_excess_total is not None and budget_surface_excess_total.size == n_snapshots:
        component_series["surface_excess_total_m3_s"] = np.maximum(
            budget_surface_excess_total,
            0.0,
        )
    elif (
        surface_history is not None
        and area_m2 is not None
        and surface_history.shape[1] == area_m2.size
    ):
        component_series["surface_excess_total_m3_s"] = np.sum(
            np.maximum(surface_history, 0.0) * area_m2[None, :],
            axis=1,
            dtype=float,
        )
    if (
        dry_deficit_history is not None
        and area_m2 is not None
        and dry_deficit_history.shape[1] == area_m2.size
    ):
        component_series["dry_deficit_total_m3_s"] = np.sum(
            np.maximum(dry_deficit_history, 0.0) * area_m2[None, :],
            axis=1,
            dtype=float,
        )
    if prescribed_head_history is not None:
        component_series["prescribed_head_out_total_m3_s"] = np.sum(
            np.maximum(prescribed_head_history, 0.0),
            axis=1,
            dtype=float,
        )

    if _all_finite_zero(saturated_thickness_history):
        saturated_thickness_history = _saturated_thickness_from_head_history(
            head_history_m=head_history,
            z_top_m=payload.get("z_top_m"),
            z_bottom_m=payload.get("z_bottom_m"),
        )
    storage_change = _storage_change_series_m3_s(
        head_history_m=head_history,
        saturated_thickness_history_m=saturated_thickness_history,
        area_m2=area_m2,
        storage_coefficient=storage_coefficient,
        period_lengths_seconds=period_lengths,
    )
    if storage_change is not None:
        component_series["storage_change_total_m3_s"] = storage_change

    if {
        "recharge_total_m3_s",
        "well_total_m3_s",
        "drainage_total_m3_s",
        "surface_excess_total_m3_s",
        "storage_change_total_m3_s",
    }.issubset(component_series) and "closure_residual_m3_s" not in component_series:
        prescribed_out = component_series.get(
            "prescribed_head_out_total_m3_s",
            np.zeros_like(component_series["recharge_total_m3_s"], dtype=float),
        )
        component_series["closure_residual_m3_s"] = (
            component_series["recharge_total_m3_s"]
            + component_series["well_total_m3_s"]
            + component_series.get(
                "dry_deficit_total_m3_s",
                np.zeros_like(component_series["recharge_total_m3_s"], dtype=float),
            )
            - component_series["drainage_total_m3_s"]
            - component_series["surface_excess_total_m3_s"]
            - prescribed_out
            - component_series["storage_change_total_m3_s"]
        )
        if _all_finite_zero(prescribed_out):
            component_series["balance_implied_outflow_total_m3_s"] = np.maximum(
                component_series["closure_residual_m3_s"],
                0.0,
            )

    return n_snapshots, elapsed_seconds, period_lengths, component_series


def _boussinesq_rows_from_component_series(
    component_series: Mapping[str, np.ndarray],
    *,
    summary: Mapping[str, Any],
    n_snapshots: int,
    elapsed_seconds: np.ndarray,
    period_lengths: np.ndarray,
    source_label: str,
) -> list[dict[str, Any]]:
    """Flatten every component series into one row per (component, time_index)."""
    time_labels = [
        (f"{elapsed / 86400.0:.1f} d" if math.isfinite(float(elapsed)) else str(index))
        for index, elapsed in enumerate(elapsed_seconds.tolist())
    ]
    rows: list[dict[str, Any]] = []
    for component, series in sorted(component_series.items()):
        values = np.asarray(series, dtype=float).reshape(-1)
        if values.size != n_snapshots:
            continue
        for time_index, value in enumerate(values.tolist()):
            if not math.isfinite(float(value)):
                continue
            period_metadata = _budget_period_metadata(
                elapsed_seconds=elapsed_seconds,
                period_lengths_seconds=period_lengths,
                n_snapshots=n_snapshots,
                time_index=time_index,
            )
            if period_metadata is None:
                continue
            period_index, period_start, period_end = period_metadata
            rows.append(
                {
                    "simulation_id": summary.get("id", ""),
                    "simulation_label": summary.get("label", summary.get("id", "")),
                    "solver": summary.get("solver", ""),
                    "mesh_mode": summary.get("mesh_mode", ""),
                    "component": component,
                    "unit": "m3/s",
                    "time_role": "period_value",
                    "period_index": period_index,
                    "period_start_seconds": period_start,
                    "period_end_seconds": period_end,
                    "time_index": time_index,
                    "elapsed_seconds": float(elapsed_seconds[time_index]),
                    "time_label": time_labels[time_index],
                    "is_initial_state": False,
                    "value": float(value),
                    "source": source_label,
                }
            )
    return rows


def _load_boussinesq_budget_rows(
    summary: Mapping[str, Any],
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load one row per (budget component, time step) for a Boussinesq run."""
    run_folder = Path(str(summary.get("run_folder", "")))
    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))

    payload, source_label = _load_boussinesq_payload(summary, store, sim_id, run_folder)
    if payload is None:
        return []

    arrays = _boussinesq_history_arrays(payload)
    n_snapshots, elapsed_seconds, period_lengths, component_series = _boussinesq_component_series(
        payload,
        arrays,
        run_folder=run_folder,
        config_path=config_path,
    )
    if n_snapshots <= 0:
        return []

    return _boussinesq_rows_from_component_series(
        component_series,
        summary=summary,
        n_snapshots=n_snapshots,
        elapsed_seconds=elapsed_seconds,
        period_lengths=period_lengths,
        source_label=source_label,
    )


def _mf_budget_component_name(component: str) -> str:
    key = str(component).strip().lower().replace("_", "-")
    aliases = {
        "rcha": "recharge_total_m3_s",
        "rch": "recharge_total_m3_s",
        "recharge": "recharge_total_m3_s",
        "drn": "drainage_total_m3_s",
        "drains": "drainage_total_m3_s",
        "drain": "drainage_total_m3_s",
        "chd": "prescribed_head_out_total_m3_s",
        "constant head": "prescribed_head_out_total_m3_s",
        "constant-head": "prescribed_head_out_total_m3_s",
        "evt": "evapotranspiration_total_m3_s",
        "et": "evapotranspiration_total_m3_s",
    }
    if key.startswith("sto") or key.startswith("storage"):
        return "storage_change_total_m3_s"
    return aliases.get(key, "")


def _mf_budget_component_value_m3_s(component: str, flux_in: float, flux_out: float) -> float:
    target = _mf_budget_component_name(component)
    if target == "storage_change_total_m3_s":
        return float(flux_out) - float(flux_in)
    if target in {
        "drainage_total_m3_s",
        "prescribed_head_out_total_m3_s",
        "evapotranspiration_total_m3_s",
    }:
        return float(flux_out) - float(flux_in)
    return float(flux_in) - float(flux_out)


def _load_catalog_budget_rows(
    summary: Mapping[str, Any],
    store: SimulationCatalog | None,
    sim_id: str | None,
) -> list[dict[str, Any]]:
    """Load generic catalog budget rows and normalize them to comparison terms."""
    if store is None or sim_id in (None, ""):
        return []
    try:
        table = store.query_budget(str(sim_id))
    except Exception:
        return []
    if table is None or table.empty:
        return []

    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
    try:
        max_timestep = int(table["timestep"].max())
    except Exception:
        return []
    elapsed_axis = _step_end_elapsed_seconds_from_config(
        config_path,
        n_steps=max_timestep + 1,
    )

    component_values: dict[tuple[int, str], float] = {}
    for _, raw_row in table.iterrows():
        source_component = str(raw_row.get("component", ""))
        component = _mf_budget_component_name(source_component)
        if not component:
            continue
        try:
            timestep = int(raw_row.get("timestep"))
            factor = _catalog_budget_factor_to_m3_s(
                solver=str(summary.get("solver", "")),
                unit=str(raw_row.get("unit", "m3/s")),
            )
            flux_in = float(raw_row.get("flux_in", 0.0)) * factor
            flux_out = float(raw_row.get("flux_out", 0.0)) * factor
        except Exception:
            continue
        value = _mf_budget_component_value_m3_s(source_component, flux_in, flux_out)
        key = (timestep, component)
        component_values[key] = component_values.get(key, 0.0) + value

    if not component_values:
        return []

    grouped_by_time: dict[int, dict[str, float]] = {}
    for (timestep, component), value in component_values.items():
        grouped_by_time.setdefault(timestep, {})[component] = value
    for values in grouped_by_time.values():
        if {
            "recharge_total_m3_s",
            "storage_change_total_m3_s",
        }.issubset(values):
            values["closure_residual_m3_s"] = (
                values.get("recharge_total_m3_s", 0.0)
                - values.get("drainage_total_m3_s", 0.0)
                - values.get("surface_excess_total_m3_s", 0.0)
                - values.get("prescribed_head_out_total_m3_s", 0.0)
                - values.get("evapotranspiration_total_m3_s", 0.0)
                - values.get("storage_change_total_m3_s", 0.0)
            )

    rows: list[dict[str, Any]] = []
    for timestep, values in sorted(grouped_by_time.items()):
        elapsed = (
            float(elapsed_axis[timestep]) if timestep < int(elapsed_axis.size) else float(timestep)
        )
        period_start = (
            float(elapsed_axis[timestep - 1])
            if timestep > 0 and timestep - 1 < int(elapsed_axis.size)
            else 0.0
        )
        time_label = f"{elapsed / 86400.0:.1f} d" if math.isfinite(elapsed) else str(timestep)
        for component, value in sorted(values.items()):
            if not math.isfinite(float(value)):
                continue
            rows.append(
                {
                    "simulation_id": summary.get("id", ""),
                    "simulation_label": summary.get("label", summary.get("id", "")),
                    "solver": summary.get("solver", ""),
                    "mesh_mode": summary.get("mesh_mode", ""),
                    "component": component,
                    "unit": "m3/s",
                    "time_role": "period_value",
                    "period_index": timestep,
                    "period_start_seconds": period_start,
                    "period_end_seconds": elapsed,
                    "time_index": timestep,
                    "elapsed_seconds": elapsed,
                    "time_label": time_label,
                    "is_initial_state": False,
                    "value": float(value),
                    "source": f"SimulationCatalog budgets(sim_id={sim_id})",
                }
            )
    return rows


BOUSSINESQ_OBSTACLE_DIAGNOSTICS_FIELDS = [
    "simulation_id",
    "simulation_label",
    "solver",
    "mesh_mode",
    "time_index",
    "elapsed_seconds",
    "time_role",
    "time_label",
    "min_head_above_bottom_m",
    "max_head_below_bottom_m",
    "head_below_bottom_cell_count",
    "negative_storage_volume_m3",
    "max_head_above_surface_m",
    "head_above_surface_cell_count",
    "dry_deficit_active_cell_count",
    "dry_deficit_total_m3_s",
    "surface_excess_active_cell_count",
    "surface_excess_total_m3_s",
    "source",
]


def _load_boussinesq_obstacle_diagnostic_rows(
    summary: Mapping[str, Any],
    store: SimulationCatalog | None = None,
    sim_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load lower/upper obstacle diagnostics from Boussinesq state histories."""
    run_folder = Path(str(summary.get("run_folder", "")))
    config_path_raw = summary.get("config_path")
    config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))

    payload: Mapping[str, Any] | None = None
    source_label = ""
    if store is not None and sim_id is not None:
        payload = _load_boussinesq_state_from_store(store, sim_id)
        if payload is not None:
            source_label = f"SimulationCatalog(sim_id={sim_id})"

    if payload is None:
        npz_path = run_folder / "_boussinesq_state_history.npz"
        if not npz_path.exists():
            return []
        payload = np.load(npz_path, allow_pickle=True)
        source_label = str(npz_path)

    head_history = _history_matrix(payload, "head_history_m")
    if head_history is None or head_history.ndim != 2:
        return []

    n_snapshots, n_cells = int(head_history.shape[0]), int(head_history.shape[1])
    cells = resolve_bundle_cells(
        run_folder,
        config_path=config_path,
        expected_size=n_cells,
    )
    if cells is None:
        return []
    if (
        cells.z_top is None
        or cells.z_bottom is None
        or cells.z_top.size != n_cells
        or cells.z_bottom.size != n_cells
    ):
        return []

    area_m2 = (
        np.asarray(cells.area_m2, dtype=float).reshape(-1)
        if cells.area_m2 is not None and cells.area_m2.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )
    storage_coefficient = (
        np.asarray(cells.storage_coefficient, dtype=float).reshape(-1)
        if cells.storage_coefficient is not None and cells.storage_coefficient.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )
    z_top = (
        np.asarray(cells.z_top, dtype=float).reshape(-1)
        if cells.z_top is not None and cells.z_top.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )
    z_bottom = (
        np.asarray(cells.z_bottom, dtype=float).reshape(-1)
        if cells.z_bottom is not None and cells.z_bottom.size == n_cells
        else np.full(n_cells, np.nan, dtype=float)
    )

    dry_deficit_history = _history_matrix(payload, "dry_deficit_history_m_s")
    surface_history = _history_matrix(payload, "saturation_excess_history_m_s")
    if dry_deficit_history is None or dry_deficit_history.shape != head_history.shape:
        dry_deficit_history = np.zeros_like(head_history, dtype=float)
    if surface_history is None or surface_history.shape != head_history.shape:
        surface_history = np.zeros_like(head_history, dtype=float)

    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    elapsed_seconds = _elapsed_seconds_axis(period_lengths, n_snapshots=n_snapshots)
    time_labels = [
        (f"{elapsed / 86400.0:.1f} d" if math.isfinite(float(elapsed)) else str(index))
        for index, elapsed in enumerate(elapsed_seconds.tolist())
    ]

    rows: list[dict[str, Any]] = []
    for time_index in range(n_snapshots):
        head = np.asarray(head_history[time_index], dtype=float)
        bottom_gap = head - z_bottom
        top_gap = head - z_top
        bottom_violation = np.maximum(-bottom_gap, 0.0)
        top_violation = np.maximum(top_gap, 0.0)
        dry = np.maximum(np.asarray(dry_deficit_history[time_index], dtype=float), 0.0)
        surface = np.maximum(np.asarray(surface_history[time_index], dtype=float), 0.0)
        negative_storage_volume = area_m2 * storage_coefficient * bottom_violation
        rows.append(
            {
                "simulation_id": summary.get("id", ""),
                "simulation_label": summary.get("label", summary.get("id", "")),
                "solver": summary.get("solver", ""),
                "mesh_mode": summary.get("mesh_mode", ""),
                "time_index": time_index,
                "elapsed_seconds": float(elapsed_seconds[time_index]),
                "time_role": (
                    "initial_state"
                    if period_lengths.size == n_snapshots - 1 and time_index == 0
                    else "state_snapshot"
                ),
                "time_label": time_labels[time_index],
                "min_head_above_bottom_m": float(np.nanmin(bottom_gap)),
                "max_head_below_bottom_m": float(np.nanmax(bottom_violation)),
                "head_below_bottom_cell_count": int(np.nansum(bottom_violation > 0.0)),
                "negative_storage_volume_m3": float(np.nansum(negative_storage_volume)),
                "max_head_above_surface_m": float(np.nanmax(top_violation)),
                "head_above_surface_cell_count": int(np.nansum(top_violation > 0.0)),
                "dry_deficit_active_cell_count": int(np.nansum(dry > 1.0e-12)),
                "dry_deficit_total_m3_s": float(np.nansum(dry * area_m2)),
                "surface_excess_active_cell_count": int(np.nansum(surface > 1.0e-12)),
                "surface_excess_total_m3_s": float(np.nansum(surface * area_m2)),
                "source": source_label,
            }
        )
    return rows


def write_budget_exports(
    *,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write budget diagnostics derived from Boussinesq state histories."""
    from hydromodpy.analysis.comparison.runtime.metadata import discover_result_store

    rows: list[dict[str, Any]] = []
    for summary in _completed_simulation_summaries(simulation_summaries):
        config_path_raw = summary.get("config_path")
        config_path = None if config_path_raw in (None, "") else Path(str(config_path_raw))
        preferred_sim_id = summary.get("sim_id")
        preferred_run_name = summary.get("run_name")
        store, sim_id = discover_result_store(
            config_path,
            preferred_sim_id=(None if preferred_sim_id in (None, "") else str(preferred_sim_id)),
            preferred_name=(None if preferred_run_name in (None, "") else str(preferred_run_name)),
        )
        try:
            catalog_rows = _load_catalog_budget_rows(summary, store, sim_id)
            if catalog_rows:
                rows.extend(catalog_rows)
            rows.extend(_load_boussinesq_budget_rows(summary, store=store, sim_id=sim_id))
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass

    rows = _with_comparable_outflow_rows(rows)

    artifacts: list[dict[str, Any]] = []
    if not rows:
        return artifacts, rows

    long_path = comparison_root / "budget_timeseries_long.csv"
    _write_csv(
        long_path,
        rows,
        [
            "simulation_id",
            "simulation_label",
            "solver",
            "mesh_mode",
            "component",
            "unit",
            "time_role",
            "period_index",
            "period_start_seconds",
            "period_end_seconds",
            "time_index",
            "elapsed_seconds",
            "time_label",
            "is_initial_state",
            "value",
            "source",
        ],
    )
    artifacts.append({"kind": "budget_timeseries_long_csv", "path": str(long_path)})

    wide_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        elapsed = _as_float(row.get("elapsed_seconds"))
        time_key = (
            f"elapsed_seconds:{elapsed:.9g}"
            if elapsed is not None
            else f"time_index:{int(row['time_index'])}"
        )
        key = (str(row["component"]), time_key)
        item = wide_index.setdefault(
            key,
            {
                "component": row["component"],
                "unit": row["unit"],
                "comparison_time_key": time_key,
                "time_role": row.get("time_role", ""),
                "period_index": row.get("period_index", ""),
                "period_start_seconds": row.get("period_start_seconds", ""),
                "period_end_seconds": row.get("period_end_seconds", ""),
                "time_index": row["time_index"],
                "elapsed_seconds": row["elapsed_seconds"],
                "time_label": row["time_label"],
            },
        )
        item[f"value__{row['simulation_id']}"] = row["value"]
    wide_rows = list(wide_index.values())
    wide_path = comparison_root / "budget_timeseries_wide.csv"
    simulation_columns = sorted(
        {key for row in wide_rows for key in row if key.startswith("value__")}
    )
    _write_csv(
        wide_path,
        wide_rows,
        [
            "component",
            "unit",
            "comparison_time_key",
            "time_role",
            "period_index",
            "period_start_seconds",
            "period_end_seconds",
            "time_index",
            "elapsed_seconds",
            "time_label",
        ]
        + simulation_columns,
    )
    artifacts.append({"kind": "budget_timeseries_wide_csv", "path": str(wide_path)})
    return artifacts, rows


def _with_comparable_outflow_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append solver-comparable outflow totals to budget rows.

    The native components remain exported separately. The derived component is
    only a post-processing comparison aid: drainage plus saturation/surface
    excess when available, with missing terms treated as zero.
    """
    if any(str(row.get("component", "")) == "comparable_outflow_total_m3_s" for row in rows):
        return rows

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        component = str(row.get("component", ""))
        if component not in {"drainage_total_m3_s", "surface_excess_total_m3_s"}:
            continue
        simulation_id = str(row.get("simulation_id", ""))
        elapsed = _as_float(row.get("elapsed_seconds"))
        time_key = (
            f"elapsed_seconds:{elapsed:.9g}"
            if elapsed is not None
            else f"time_index:{row.get('time_index', '')}"
        )
        item = grouped.setdefault(
            (simulation_id, time_key),
            {
                "template": row,
                "drainage_total_m3_s": 0.0,
                "surface_excess_total_m3_s": 0.0,
            },
        )
        value = _as_float(row.get("value"))
        if value is not None:
            item[component] = float(value)

    if not grouped:
        return rows

    derived_rows: list[dict[str, Any]] = []
    for item in grouped.values():
        template = dict(item["template"])
        value = float(item["drainage_total_m3_s"]) + float(item["surface_excess_total_m3_s"])
        template.update(
            {
                "component": "comparable_outflow_total_m3_s",
                "unit": "m3/s",
                "value": value,
                "source": ("derived:drainage_total_m3_s+surface_excess_total_m3_s"),
            }
        )
        derived_rows.append(template)

    derived_rows.sort(
        key=lambda row: (
            str(row.get("simulation_id", "")),
            _as_float(row.get("elapsed_seconds")) or 0.0,
            int(_as_float(row.get("time_index")) or 0),
        )
    )
    return rows + derived_rows
