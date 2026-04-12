"""Comparison metrics for method-comparison observables."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


SUMMARY_METRIC_FIELDS = [
    "variant_id",
    "reference_variant",
    "observable",
    "unit",
    "n_pairs",
    "bias",
    "mae",
    "rmse",
    "max_abs_error",
    "mean_relative_error",
]

DETAIL_METRIC_FIELDS = [
    "comparison_id",
    "variant_id",
    "reference_variant",
    "observable",
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
    "selection",
    "reference_selection",
]


def _as_float(value: Any) -> float | None:
    """Coerce one CSV/JSON value to float, returning None for blanks."""
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return the observable/time/value key used for reference matching."""
    return (
        str(row.get("observable", "")),
        str(row.get("comparison_time_key", row.get("time", ""))),
        str(row.get("value_index", "")),
        str(row.get("unit", "")),
    )


def build_comparison_metrics(
    rows: list[dict[str, Any]],
    *,
    reference_variant: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build detail and summary metrics against one reference variant."""
    if not rows or reference_variant is None:
        return [], []

    reference_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if str(row.get("variant_id", "")) == reference_variant:
            reference_by_key[_row_key(row)] = row

    detail_rows: list[dict[str, Any]] = []
    for row in rows:
        variant_id = str(row.get("variant_id", ""))
        if variant_id == reference_variant:
            continue
        reference = reference_by_key.get(_row_key(row))
        if reference is None:
            continue
        value = _as_float(row.get("value"))
        reference_value = _as_float(reference.get("value"))
        if value is None or reference_value is None:
            continue
        signed_error = value - reference_value
        absolute_error = abs(signed_error)
        relative_error = (
            absolute_error / abs(reference_value)
            if reference_value != 0.0
            else math.nan
        )
        detail_rows.append(
            {
                "comparison_id": row.get("comparison_id", ""),
                "variant_id": variant_id,
                "reference_variant": reference_variant,
                "observable": row.get("observable", ""),
                "comparison_time_key": row.get("comparison_time_key", ""),
                "time": row.get("time", ""),
                "time_index": row.get("time_index", ""),
                "elapsed_seconds": row.get("elapsed_seconds", ""),
                "value_index": row.get("value_index", ""),
                "value": value,
                "reference_value": reference_value,
                "signed_error": signed_error,
                "absolute_error": absolute_error,
                "relative_error": relative_error,
                "unit": row.get("unit", ""),
                "selection": row.get("selection", ""),
                "reference_selection": reference.get("selection", ""),
            }
        )

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in detail_rows:
        grouped[
            (
                str(row["variant_id"]),
                str(row["observable"]),
                str(row.get("unit", "")),
            )
        ].append(row)

    summary_rows: list[dict[str, Any]] = []
    for (variant_id, observable, unit), group in sorted(grouped.items()):
        signed = np.asarray([row["signed_error"] for row in group], dtype=float)
        abs_err = np.abs(signed)
        rel_err = np.asarray([row["relative_error"] for row in group], dtype=float)
        finite_rel = rel_err[np.isfinite(rel_err)]
        summary_rows.append(
            {
                "variant_id": variant_id,
                "reference_variant": reference_variant,
                "observable": observable,
                "unit": unit,
                "n_pairs": int(signed.size),
                "bias": float(np.nanmean(signed)),
                "mae": float(np.nanmean(abs_err)),
                "rmse": float(np.sqrt(np.nanmean(signed**2))),
                "max_abs_error": float(np.nanmax(abs_err)),
                "mean_relative_error": (
                    float(np.nanmean(finite_rel)) if finite_rel.size else math.nan
                ),
            }
        )
    return detail_rows, summary_rows


def write_metrics_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    fieldnames: list[str] | None = None,
) -> None:
    """Write metrics rows to CSV."""
    resolved_fieldnames = fieldnames or (list(rows[0].keys()) if rows else SUMMARY_METRIC_FIELDS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=resolved_fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in resolved_fieldnames})


def write_metrics_json(path: Path, payload: dict[str, Any]) -> None:
    """Write metrics payload to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )


__all__ = (
    "DETAIL_METRIC_FIELDS",
    "SUMMARY_METRIC_FIELDS",
    "build_comparison_metrics",
    "write_metrics_csv",
    "write_metrics_json",
)
