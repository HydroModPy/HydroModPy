"""Supplemental CSV exports for method-comparison runs."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from launchers.method_comparison.runtime import resolve_bundle_cells


def _as_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _completed_variant_summaries(
    variant_summaries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(summary)
        for summary in variant_summaries
        if str(summary.get("status", "")) in {"completed", "reused"}
    ]


def _runtime_seconds(summary: Mapping[str, Any]) -> float | None:
    for candidate in (
        summary.get("wall_time_seconds"),
        summary.get("metrics", {}).get("wall_time_seconds"),
        summary.get("run_metadata", {}).get("wall_time_seconds"),
    ):
        value = _as_float(candidate)
        if value is not None:
            return value
    return None


def _observable_support_lookup(
    observables: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for observable in observables:
        lookup[str(observable.get("name", ""))] = str(observable.get("support", ""))
    return lookup


def _observable_variable_lookup(
    observables: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for observable in observables:
        lookup[str(observable.get("name", ""))] = str(observable.get("variable", ""))
    return lookup


def write_observable_chronicle_exports(
    *,
    comparison_root: Path,
    rows: list[dict[str, Any]],
    detail_metrics: list[dict[str, Any]],
    observables: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Write CSV exports for non-map observables."""
    support_lookup = _observable_support_lookup(observables)
    variable_lookup = _observable_variable_lookup(observables)

    long_rows = [
        {
            "comparison_id": row.get("comparison_id", ""),
            "observable": row.get("observable", ""),
            "variable": variable_lookup.get(str(row.get("observable", "")), ""),
            "support": row.get("support", ""),
            "unit": row.get("unit", ""),
            "variant_id": row.get("variant_id", ""),
            "variant_label": row.get("variant_label", ""),
            "comparison_time_key": row.get("comparison_time_key", ""),
            "time": row.get("time", ""),
            "time_index": row.get("time_index", ""),
            "elapsed_seconds": row.get("elapsed_seconds", ""),
            "value_index": row.get("value_index", ""),
            "value": row.get("value", ""),
        }
        for row in rows
        if str(row.get("support", "")) != "map"
        and str(row.get("comparison_time_key", "")) != "reduced"
        and _as_float(row.get("value")) is not None
    ]

    wide_index: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in long_rows:
        key = (
            str(row.get("observable", "")),
            str(row.get("unit", "")),
            str(row.get("comparison_time_key", "")),
            str(row.get("time_index", "")),
            str(row.get("value_index", "")),
        )
        item = wide_index.setdefault(
            key,
            {
                "comparison_id": row.get("comparison_id", ""),
                "observable": row.get("observable", ""),
                "variable": row.get("variable", ""),
                "support": row.get("support", ""),
                "unit": row.get("unit", ""),
                "comparison_time_key": row.get("comparison_time_key", ""),
                "time": row.get("time", ""),
                "time_index": row.get("time_index", ""),
                "elapsed_seconds": row.get("elapsed_seconds", ""),
                "value_index": row.get("value_index", ""),
            },
        )
        item[f"value__{row['variant_id']}"] = row.get("value", "")
    wide_rows = list(wide_index.values())

    delta_rows = [
        {
            "comparison_id": row.get("comparison_id", ""),
            "observable": row.get("observable", ""),
            "variable": variable_lookup.get(str(row.get("observable", "")), ""),
            "support": support_lookup.get(str(row.get("observable", "")), ""),
            "variant_id": row.get("variant_id", ""),
            "reference_variant": row.get("reference_variant", ""),
            "comparison_time_key": row.get("comparison_time_key", ""),
            "time": row.get("time", ""),
            "time_index": row.get("time_index", ""),
            "elapsed_seconds": row.get("elapsed_seconds", ""),
            "value_index": row.get("value_index", ""),
            "value": row.get("value", ""),
            "reference_value": row.get("reference_value", ""),
            "signed_error": row.get("signed_error", ""),
            "absolute_error": row.get("absolute_error", ""),
            "relative_error": row.get("relative_error", ""),
            "unit": row.get("unit", ""),
        }
        for row in detail_metrics
        if support_lookup.get(str(row.get("observable", "")), "") != "map"
    ]

    artifacts: list[dict[str, Any]] = []
    if long_rows:
        path = comparison_root / "timeseries_long.csv"
        _write_csv(
            path,
            long_rows,
            [
                "comparison_id",
                "observable",
                "variable",
                "support",
                "unit",
                "variant_id",
                "variant_label",
                "comparison_time_key",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
                "value",
            ],
        )
        artifacts.append({"kind": "timeseries_long_csv", "path": str(path)})
    if wide_rows:
        path = comparison_root / "timeseries_wide.csv"
        variant_columns = sorted(
            {
                key
                for row in wide_rows
                for key in row
                if key.startswith("value__")
            }
        )
        _write_csv(
            path,
            wide_rows,
            [
                "comparison_id",
                "observable",
                "variable",
                "support",
                "unit",
                "comparison_time_key",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
            ]
            + variant_columns,
        )
        artifacts.append({"kind": "timeseries_wide_csv", "path": str(path)})
    if delta_rows:
        path = comparison_root / "timeseries_delta.csv"
        _write_csv(
            path,
            delta_rows,
            [
                "comparison_id",
                "observable",
                "variable",
                "support",
                "variant_id",
                "reference_variant",
                "comparison_time_key",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
                "value",
                "reference_value",
                "signed_error",
                "absolute_error",
                "relative_error",
                "unit",
            ],
        )
        artifacts.append({"kind": "timeseries_delta_csv", "path": str(path)})
    return artifacts, long_rows, wide_rows, delta_rows


def _load_simulated_timeseries_csv(path: Path) -> tuple[list[dict[str, str]], str] | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    delimiter = ";" if ";" in raw.partition("\n")[0] else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = [{str(key): str(value) for key, value in row.items()} for row in reader]
    if not rows:
        return None
    return rows, delimiter


def write_native_timeseries_exports(
    *,
    comparison_id: str,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    reference_variant: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Write CSV exports from `_postprocess/_timeseries/_simulated_timeseries.csv` when present."""
    tables: dict[str, dict[str, Any]] = {}
    for summary in _completed_variant_summaries(variant_summaries):
        run_folder = Path(str(summary.get("run_folder", "")))
        source_path = run_folder / "_postprocess" / "_timeseries" / "_simulated_timeseries.csv"
        loaded = _load_simulated_timeseries_csv(source_path)
        if loaded is None:
            continue
        raw_rows, _delimiter = loaded
        numeric_columns = {
            key
            for key in raw_rows[0].keys()
            if key != "date"
            and any(_as_float(row.get(key)) is not None for row in raw_rows)
        }
        tables[str(summary.get("id", ""))] = {
            "variant_id": str(summary.get("id", "")),
            "variant_label": str(summary.get("label", summary.get("id", ""))),
            "rows": raw_rows,
            "numeric_columns": numeric_columns,
            "source_path": str(source_path),
        }

    if len(tables) < 2:
        return [], [], [], []

    common_variables = sorted(
        set.intersection(*(table["numeric_columns"] for table in tables.values()))
    )
    if not common_variables:
        return [], [], [], []

    long_rows: list[dict[str, Any]] = []
    for table in tables.values():
        for time_index, raw_row in enumerate(table["rows"]):
            time_label = raw_row.get("date", str(time_index))
            for variable in common_variables:
                value = _as_float(raw_row.get(variable))
                if value is None:
                    continue
                long_rows.append(
                    {
                        "comparison_id": comparison_id,
                        "variant_id": table["variant_id"],
                        "variant_label": table["variant_label"],
                        "variable": variable,
                        "time_index": time_index,
                        "time_label": time_label,
                        "value": value,
                        "source_path": table["source_path"],
                    }
                )

    wide_index: dict[tuple[str, int], dict[str, Any]] = {}
    for row in long_rows:
        key = (str(row["variable"]), int(row["time_index"]))
        item = wide_index.setdefault(
            key,
            {
                "comparison_id": comparison_id,
                "variable": row["variable"],
                "time_index": row["time_index"],
                "time_label": row["time_label"],
            },
        )
        item[f"value__{row['variant_id']}"] = row["value"]
    wide_rows = list(wide_index.values())

    delta_rows: list[dict[str, Any]] = []
    if reference_variant is not None and reference_variant in tables:
        reference_index = {
            (str(row["variable"]), int(row["time_index"])): row
            for row in long_rows
            if str(row["variant_id"]) == reference_variant
        }
        for row in long_rows:
            if str(row["variant_id"]) == reference_variant:
                continue
            reference_row = reference_index.get((str(row["variable"]), int(row["time_index"])))
            if reference_row is None:
                continue
            signed_error = float(row["value"]) - float(reference_row["value"])
            absolute_error = abs(signed_error)
            ref_value = float(reference_row["value"])
            relative_error = absolute_error / abs(ref_value) if ref_value != 0.0 else math.nan
            delta_rows.append(
                {
                    "comparison_id": comparison_id,
                    "variant_id": row["variant_id"],
                    "reference_variant": reference_variant,
                    "variable": row["variable"],
                    "time_index": row["time_index"],
                    "time_label": row["time_label"],
                    "value": row["value"],
                    "reference_value": reference_row["value"],
                    "signed_error": signed_error,
                    "absolute_error": absolute_error,
                    "relative_error": relative_error,
                }
            )

    artifacts: list[dict[str, Any]] = []
    if long_rows:
        path = comparison_root / "native_timeseries_long.csv"
        _write_csv(
            path,
            long_rows,
            [
                "comparison_id",
                "variant_id",
                "variant_label",
                "variable",
                "time_index",
                "time_label",
                "value",
                "source_path",
            ],
        )
        artifacts.append({"kind": "native_timeseries_long_csv", "path": str(path)})
    if wide_rows:
        path = comparison_root / "native_timeseries_wide.csv"
        variant_columns = sorted(
            {
                key
                for row in wide_rows
                for key in row
                if key.startswith("value__")
            }
        )
        _write_csv(
            path,
            wide_rows,
            ["comparison_id", "variable", "time_index", "time_label"] + variant_columns,
        )
        artifacts.append({"kind": "native_timeseries_wide_csv", "path": str(path)})
    if delta_rows:
        path = comparison_root / "native_timeseries_delta.csv"
        _write_csv(
            path,
            delta_rows,
            [
                "comparison_id",
                "variant_id",
                "reference_variant",
                "variable",
                "time_index",
                "time_label",
                "value",
                "reference_value",
                "signed_error",
                "absolute_error",
                "relative_error",
            ],
        )
        artifacts.append({"kind": "native_timeseries_delta_csv", "path": str(path)})
    return artifacts, long_rows, wide_rows, delta_rows


def _load_json_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _history_matrix(payload: Mapping[str, Any], key: str) -> np.ndarray | None:
    if key not in payload:
        return None
    values = np.asarray(payload[key], dtype=float)
    if values.ndim == 1:
        return values.reshape(1, -1)
    if values.ndim == 2:
        return values
    return None


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


def _storage_change_series_m3_s(
    *,
    head_history_m: np.ndarray | None,
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
    if not (
        head_history_m.shape[1] == area_m2.size == storage_coefficient.size
    ):
        return None

    n_snapshots = int(head_history_m.shape[0])
    storage_change = np.full(n_snapshots, np.nan, dtype=float)
    if n_snapshots == 0:
        return storage_change

    if period_lengths_seconds.size == n_snapshots - 1:
        storage_change[0] = 0.0
        for index in range(1, n_snapshots):
            dt_seconds = float(period_lengths_seconds[index - 1])
            if dt_seconds <= 0.0 or not math.isfinite(dt_seconds):
                continue
            delta_head_m = head_history_m[index] - head_history_m[index - 1]
            storage_change[index] = float(
                np.nansum(area_m2 * storage_coefficient * delta_head_m) / dt_seconds
            )
        return storage_change

    if period_lengths_seconds.size == n_snapshots:
        storage_change[0] = 0.0
        for index in range(1, n_snapshots):
            dt_seconds = float(period_lengths_seconds[index])
            if dt_seconds <= 0.0 or not math.isfinite(dt_seconds):
                continue
            delta_head_m = head_history_m[index] - head_history_m[index - 1]
            storage_change[index] = float(
                np.nansum(area_m2 * storage_coefficient * delta_head_m) / dt_seconds
            )
        return storage_change

    return None


def _load_boussinesq_budget_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    run_folder = Path(str(summary.get("run_folder", "")))
    npz_path = run_folder / "_boussinesq_state_history.npz"
    if not npz_path.exists():
        return []

    payload = np.load(npz_path, allow_pickle=True)
    recharge_history = _history_matrix(payload, "recharge_rate_history_m_s")
    well_history = _history_matrix(payload, "well_flux_history_m3_s")
    drainage_history = _history_matrix(payload, "drainage_flux_history_m3_s")
    surface_history = _history_matrix(payload, "saturation_excess_history_m_s")
    head_history = _history_matrix(payload, "head_history_m")

    n_snapshots = max(
        (
            int(matrix.shape[0])
            for matrix in (
                recharge_history,
                well_history,
                drainage_history,
                surface_history,
                head_history,
            )
            if matrix is not None
        ),
        default=0,
    )
    if n_snapshots <= 0:
        return []

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
                head_history,
            )
            if matrix is not None and matrix.ndim == 2
        ),
        0,
    )
    if n_cells > 0:
        cells = resolve_bundle_cells(
            run_folder,
            expected_size=n_cells,
            solver_name="boussinesq",
        )
        if cells is not None:
            if cells.area_m2 is not None:
                area_m2 = np.asarray(cells.area_m2, dtype=float).reshape(-1)
            if cells.storage_coefficient is not None:
                storage_coefficient = np.asarray(
                    cells.storage_coefficient,
                    dtype=float,
                ).reshape(-1)

    period_lengths = (
        np.asarray(payload["period_lengths_seconds"], dtype=float).ravel()
        if "period_lengths_seconds" in payload
        else np.asarray([], dtype=float)
    )
    elapsed_seconds = _elapsed_seconds_axis(
        period_lengths,
        n_snapshots=n_snapshots,
    )

    component_series: dict[str, np.ndarray] = {}
    if recharge_history is not None and area_m2 is not None and recharge_history.shape[1] == area_m2.size:
        component_series["recharge_total_m3_s"] = np.sum(
            recharge_history * area_m2[None, :],
            axis=1,
            dtype=float,
        )
    if well_history is not None:
        component_series["well_total_m3_s"] = np.sum(well_history, axis=1, dtype=float)
    if drainage_history is not None:
        component_series["drainage_total_m3_s"] = np.sum(
            drainage_history,
            axis=1,
            dtype=float,
        )
    if surface_history is not None and area_m2 is not None and surface_history.shape[1] == area_m2.size:
        component_series["surface_excess_total_m3_s"] = np.sum(
            np.maximum(surface_history, 0.0) * area_m2[None, :],
            axis=1,
            dtype=float,
        )

    storage_change = _storage_change_series_m3_s(
        head_history_m=head_history,
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
    }.issubset(component_series):
        component_series["closure_residual_m3_s"] = (
            component_series["recharge_total_m3_s"]
            + component_series["well_total_m3_s"]
            - component_series["drainage_total_m3_s"]
            - component_series["surface_excess_total_m3_s"]
            - component_series["storage_change_total_m3_s"]
        )

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
            rows.append(
                {
                    "variant_id": summary.get("id", ""),
                    "variant_label": summary.get("label", summary.get("id", "")),
                    "solver": summary.get("solver", ""),
                    "mesh_mode": summary.get("mesh_mode", ""),
                    "component": component,
                    "unit": "m3/s",
                    "time_index": time_index,
                    "elapsed_seconds": float(elapsed_seconds[time_index]),
                    "time_label": time_labels[time_index],
                    "value": float(value),
                    "source": str(npz_path),
                }
            )
    return rows


def write_budget_exports(
    *,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write budget diagnostics derived from Boussinesq state histories."""
    rows: list[dict[str, Any]] = []
    for summary in _completed_variant_summaries(variant_summaries):
        rows.extend(_load_boussinesq_budget_rows(summary))

    artifacts: list[dict[str, Any]] = []
    if not rows:
        return artifacts, rows

    long_path = comparison_root / "budget_timeseries_long.csv"
    _write_csv(
        long_path,
        rows,
        [
            "variant_id",
            "variant_label",
            "solver",
            "mesh_mode",
            "component",
            "unit",
            "time_index",
            "elapsed_seconds",
            "time_label",
            "value",
            "source",
        ],
    )
    artifacts.append({"kind": "budget_timeseries_long_csv", "path": str(long_path)})

    wide_index: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["component"]), int(row["time_index"]))
        item = wide_index.setdefault(
            key,
            {
                "component": row["component"],
                "unit": row["unit"],
                "time_index": row["time_index"],
                "elapsed_seconds": row["elapsed_seconds"],
                "time_label": row["time_label"],
            },
        )
        item[f"value__{row['variant_id']}"] = row["value"]
    wide_rows = list(wide_index.values())
    wide_path = comparison_root / "budget_timeseries_wide.csv"
    variant_columns = sorted(
        {
            key
            for row in wide_rows
            for key in row
            if key.startswith("value__")
        }
    )
    _write_csv(
        wide_path,
        wide_rows,
        ["component", "unit", "time_index", "elapsed_seconds", "time_label"]
        + variant_columns,
    )
    artifacts.append({"kind": "budget_timeseries_wide_csv", "path": str(wide_path)})
    return artifacts, rows


def write_execution_summary_csv(
    *,
    comparison_root: Path,
    variant_summaries: Iterable[Mapping[str, Any]],
    reference_variant: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write one flat runtime summary CSV."""
    rows: list[dict[str, Any]] = []
    reference_runtime: float | None = None
    for summary in _completed_variant_summaries(variant_summaries):
        if str(summary.get("id", "")) == reference_variant:
            reference_runtime = _runtime_seconds(summary)
            break

    for summary in _completed_variant_summaries(variant_summaries):
        runtime_seconds = _runtime_seconds(summary)
        if runtime_seconds is None:
            continue
        speedup = (
            reference_runtime / runtime_seconds
            if reference_runtime is not None and runtime_seconds > 0.0
            else math.nan
        )
        rows.append(
            {
                "variant_id": summary.get("id", ""),
                "variant_label": summary.get("label", summary.get("id", "")),
                "solver": summary.get("solver", ""),
                "mesh_mode": summary.get("mesh_mode", ""),
                "runtime_seconds": runtime_seconds,
                "runtime_minutes": runtime_seconds / 60.0,
                "reference_variant": reference_variant or "",
                "speedup_vs_reference": speedup,
            }
        )

    artifacts: list[dict[str, Any]] = []
    if rows:
        path = comparison_root / "execution_times.csv"
        _write_csv(
            path,
            rows,
            [
                "variant_id",
                "variant_label",
                "solver",
                "mesh_mode",
                "runtime_seconds",
                "runtime_minutes",
                "reference_variant",
                "speedup_vs_reference",
            ],
        )
        artifacts.append({"kind": "execution_times_csv", "path": str(path)})
    return artifacts, rows


__all__ = (
    "write_budget_exports",
    "write_execution_summary_csv",
    "write_native_timeseries_exports",
    "write_observable_chronicle_exports",
)
