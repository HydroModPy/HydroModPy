"""Observable chronicle CSV exports."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .base import (
    _as_float,
    _observable_support_lookup,
    _observable_variable_lookup,
    _write_csv,
)


def write_observable_chronicle_exports(
    *,
    comparison_root: Path,
    rows: list[dict[str, Any]],
    detail_metrics: list[dict[str, Any]],
    observables: Iterable[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
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
            "simulation_id": row.get("simulation_id", ""),
            "simulation_label": row.get("simulation_label", ""),
            "comparison_time_key": row.get("comparison_time_key", ""),
            "time_role": row.get("time_role", ""),
            "time": row.get("time", ""),
            "time_index": row.get("time_index", ""),
            "elapsed_seconds": row.get("elapsed_seconds", ""),
            "value_index": row.get("value_index", ""),
            "value": row.get("value", ""),
            "surface_top_m": row.get("surface_top_m", ""),
            "surface_bottom_m": row.get("surface_bottom_m", ""),
        }
        for row in rows
        if str(row.get("support", "")) != "map"
        and str(row.get("comparison_time_key", "")) != "reduced"
        and _as_float(row.get("value")) is not None
    ]

    wide_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in long_rows:
        key = (
            str(row.get("observable", "")),
            str(row.get("unit", "")),
            str(row.get("comparison_time_key", "")),
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
                "time_role": row.get("time_role", ""),
                "time": row.get("time", ""),
                "time_index": row.get("time_index", ""),
                "elapsed_seconds": row.get("elapsed_seconds", ""),
                "value_index": row.get("value_index", ""),
            },
        )
        item[f"value__{row['simulation_id']}"] = row.get("value", "")
    wide_rows = list(wide_index.values())

    delta_rows = [
        {
            "comparison_id": row.get("comparison_id", ""),
            "observable": row.get("observable", ""),
            "variable": variable_lookup.get(str(row.get("observable", "")), ""),
            "support": support_lookup.get(str(row.get("observable", "")), ""),
            "simulation_id": row.get("simulation_id", ""),
            "reference_simulation": row.get("reference_simulation", ""),
            "comparison_time_key": row.get("comparison_time_key", ""),
            "time_role": row.get("time_role", ""),
            "reference_time_role": row.get("reference_time_role", ""),
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
                "simulation_id",
                "simulation_label",
                "comparison_time_key",
                "time_role",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
                "value",
                "surface_top_m",
                "surface_bottom_m",
            ],
        )
        artifacts.append({"kind": "timeseries_long_csv", "path": str(path)})
    if wide_rows:
        path = comparison_root / "timeseries_wide.csv"
        simulation_columns = sorted(
            {key for row in wide_rows for key in row if key.startswith("value__")}
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
                "time_role",
                "time",
                "time_index",
                "elapsed_seconds",
                "value_index",
            ]
            + simulation_columns,
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
                "simulation_id",
                "reference_simulation",
                "comparison_time_key",
                "time_role",
                "reference_time_role",
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


def _load_simulated_timeseries_csv(
    path: Path,
) -> tuple[list[dict[str, str]], str] | None:
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
