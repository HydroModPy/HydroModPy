"""Supplemental CSV exports for method-comparison runs."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


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
    "write_execution_summary_csv",
    "write_native_timeseries_exports",
    "write_observable_chronicle_exports",
)
