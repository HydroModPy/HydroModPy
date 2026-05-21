"""Native postprocess timeseries CSV exports."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .base import (
    _as_float,
    _completed_simulation_summaries,
    _write_csv,
)
from .observables import _load_simulated_timeseries_csv


def write_native_timeseries_exports(
    *,
    comparison_id: str,
    comparison_root: Path,
    simulation_summaries: Iterable[Mapping[str, Any]],
    reference_simulation: str | None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Write CSV exports from `_postprocess/_timeseries/_simulated_timeseries.csv` when present."""
    tables: dict[str, dict[str, Any]] = {}
    for summary in _completed_simulation_summaries(simulation_summaries):
        run_folder = Path(str(summary.get("run_folder", "")))
        source_path = run_folder / "_postprocess" / "_timeseries" / "_simulated_timeseries.csv"
        loaded = _load_simulated_timeseries_csv(source_path)
        if loaded is None:
            continue
        raw_rows, _ = loaded
        numeric_columns = {
            key
            for key in raw_rows[0].keys()
            if key != "date" and any(_as_float(row.get(key)) is not None for row in raw_rows)
        }
        tables[str(summary.get("id", ""))] = {
            "simulation_id": str(summary.get("id", "")),
            "simulation_label": str(summary.get("label", summary.get("id", ""))),
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
                        "simulation_id": table["simulation_id"],
                        "simulation_label": table["simulation_label"],
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
        item[f"value__{row['simulation_id']}"] = row["value"]
    wide_rows = list(wide_index.values())

    delta_rows: list[dict[str, Any]] = []
    if reference_simulation is not None and reference_simulation in tables:
        reference_index = {
            (str(row["variable"]), int(row["time_index"])): row
            for row in long_rows
            if str(row["simulation_id"]) == reference_simulation
        }
        for row in long_rows:
            if str(row["simulation_id"]) == reference_simulation:
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
                    "simulation_id": row["simulation_id"],
                    "reference_simulation": reference_simulation,
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
                "simulation_id",
                "simulation_label",
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
        simulation_columns = sorted(
            {key for row in wide_rows for key in row if key.startswith("value__")}
        )
        _write_csv(
            path,
            wide_rows,
            ["comparison_id", "variable", "time_index", "time_label"] + simulation_columns,
        )
        artifacts.append({"kind": "native_timeseries_wide_csv", "path": str(path)})
    if delta_rows:
        path = comparison_root / "native_timeseries_delta.csv"
        _write_csv(
            path,
            delta_rows,
            [
                "comparison_id",
                "simulation_id",
                "reference_simulation",
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
