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
    "reference_match_strategy",
    "reference_match_key",
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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _row_is_nodata(row: dict[str, Any]) -> bool:
    return _as_bool(row.get("is_nodata", False))


def _exact_row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return the observable/time/value key used for exact reference matching."""
    return (
        str(row.get("observable", "")),
        str(row.get("comparison_time_key", row.get("time", ""))),
        str(row.get("value_index", "")),
        str(row.get("unit", "")),
    )


def _fallback_row_keys(row: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Return semantic fallback keys used when time encodings differ."""
    fallback_key = str(row.get("match_fallback_key", "")).strip()
    if fallback_key == "":
        return []
    return [
        (
            str(row.get("observable", "")),
            fallback_key,
            str(row.get("value_index", "")),
            str(row.get("unit", "")),
        )
    ]


def _is_comparable_metric_row(row: dict[str, Any]) -> bool:
    if _row_is_nodata(row):
        return False
    return _as_float(row.get("value")) is not None


def _build_reference_indexes(
    rows: list[dict[str, Any]],
    *,
    reference_variant: str,
) -> tuple[
    dict[tuple[str, str, str, str], dict[str, Any]],
    dict[tuple[str, str, str, str], dict[str, Any]],
]:
    exact_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    fallback_index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if str(row.get("variant_id", "")) != reference_variant:
            continue
        if not _is_comparable_metric_row(row):
            continue
        exact_index[_exact_row_key(row)] = row
        for fallback_key in _fallback_row_keys(row):
            fallback_index.setdefault(fallback_key, row)
    return exact_index, fallback_index


def _match_reference_row(
    row: dict[str, Any],
    *,
    exact_index: dict[tuple[str, str, str, str], dict[str, Any]],
    fallback_index: dict[tuple[str, str, str, str], dict[str, Any]],
) -> tuple[dict[str, Any] | None, str, str]:
    exact_key = _exact_row_key(row)
    reference = exact_index.get(exact_key)
    if reference is not None:
        return reference, "exact_time_key", exact_key[1]

    for fallback_key in _fallback_row_keys(row):
        reference = fallback_index.get(fallback_key)
        if reference is not None:
            return reference, "fallback_time_key", fallback_key[1]

    return None, "", ""


def build_unmatched_groups(
    rows: list[dict[str, Any]],
    *,
    reference_variant: str | None,
) -> list[dict[str, Any]]:
    """Group candidate rows that still have no aligned reference row."""
    if not rows or reference_variant is None:
        return []

    exact_index, fallback_index = _build_reference_indexes(
        rows,
        reference_variant=reference_variant,
    )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        variant_id = str(row.get("variant_id", ""))
        if variant_id == reference_variant:
            continue
        if not _is_comparable_metric_row(row):
            continue
        reference, _, _ = _match_reference_row(
            row,
            exact_index=exact_index,
            fallback_index=fallback_index,
        )
        if reference is not None:
            continue
        grouped[
            (
                variant_id,
                str(row.get("observable", "")),
                str(row.get("unit", "")),
            )
        ].append(row)

    items: list[dict[str, Any]] = []
    for (variant_id, observable, unit), group in sorted(grouped.items()):
        items.append(
            {
                "variant_id": variant_id,
                "observable": observable,
                "unit": unit,
                "n_rows": len(group),
                "reason": "missing aligned reference row or unit mismatch",
            }
        )
    return items


def build_comparison_metrics(
    rows: list[dict[str, Any]],
    *,
    reference_variant: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build detail and summary metrics against one reference variant."""
    if not rows or reference_variant is None:
        return [], []

    exact_index, fallback_index = _build_reference_indexes(
        rows,
        reference_variant=reference_variant,
    )

    detail_rows: list[dict[str, Any]] = []
    for row in rows:
        variant_id = str(row.get("variant_id", ""))
        if variant_id == reference_variant:
            continue
        if not _is_comparable_metric_row(row):
            continue
        reference, match_strategy, match_key = _match_reference_row(
            row,
            exact_index=exact_index,
            fallback_index=fallback_index,
        )
        if reference is None:
            continue
        value = _as_float(row.get("value"))
        reference_value = _as_float(reference.get("value"))
        if value is None or reference_value is None:
            continue
        signed_error = value - reference_value
        absolute_error = abs(signed_error)
        relative_error = (
            absolute_error / abs(reference_value) if reference_value != 0.0 else math.nan
        )
        detail_rows.append(
            {
                "comparison_id": row.get("comparison_id", ""),
                "variant_id": variant_id,
                "reference_variant": reference_variant,
                "observable": row.get("observable", ""),
                "comparison_time_key": row.get("comparison_time_key", ""),
                "reference_match_strategy": match_strategy,
                "reference_match_key": match_key,
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
    "build_unmatched_groups",
    "write_metrics_csv",
    "write_metrics_json",
)
