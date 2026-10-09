"""Low-level HTML template helpers for comparison report sections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.reporting.comparison.context import ComparisonWebContext
from hydromodpy.reporting.comparison.html_utils import (
    link_relative,
    safe,
    short,
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _format_value(value: Any, *, default: str = "") -> str:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if math.isfinite(value):
            return f"{value:.3g}"
        return str(value)
    return str(value)


def _quantity_is_zero(value: Any) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, int | float):
        return math.isfinite(float(value)) and float(value) == 0.0
    token = str(value).strip().split(maxsplit=1)[0]
    try:
        return float(token) == 0.0
    except ValueError:
        return False


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value if value is not None else "")
    if not math.isfinite(number):
        return ""
    if abs(number) > 0 and abs(number) < 0.01:
        return f"{number:.1e}"
    return f"{number:.1f}"


def _format_with_unit(value: Any, unit: str) -> str:
    number = _float_or_none(value)
    if number is None:
        return ""
    formatted = _format_number(number)
    return f"{formatted} {unit}".strip()


def _format_percent_value(value: Any) -> str:
    number = _float_or_none(value)
    if number is None:
        return ""
    return f"{_format_number(number)} %"


def _runtime_seconds(value: Any) -> float | None:
    try:
        seconds = float(value)
    except Exception:
        return None
    if not math.isfinite(seconds):
        return None
    return seconds


def _format_runtime_seconds(value: float | None) -> str:
    if value is None:
        return ""
    if value < 60.0:
        return f"{value:.1f} s"
    minutes = value / 60.0
    if minutes < 60.0:
        return f"{minutes:.1f} min"
    return f"{minutes / 60.0:.2f} h"


def _row_runtime_seconds_with_scope(row: Mapping[str, Any]) -> tuple[float | None, str]:
    metrics = row.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    boussinesq_summary = row.get("boussinesq_summary")
    boussinesq_map = boussinesq_summary if isinstance(boussinesq_summary, Mapping) else {}
    for candidate in (
        row.get("flow_solve_time_seconds"),
        metrics_map.get("flow_solve_time_seconds"),
        boussinesq_map.get("flow_solve_time_seconds"),
    ):
        seconds = _runtime_seconds(candidate)
        if seconds is not None:
            return seconds, "flow_solve"
    return None, ""


def _observable_label(name: str) -> str:
    labels = {
        "head_map_initial": "initial head field",
        "head_map_first_computed": "head field at the first computed step",
        "head_map_wet_year1": "head field after the first wet season",
        "head_map_dry_late": "head field in the late dry state",
        "head_map_drought_year2": "head field at the end of the dry period",
        "head_map_extreme_recharge": "head field during the recharge peak",
        "head_map_last": "final head field",
        "head_west_low_k_series": "head series in the poorly conductive west zone",
        "head_west_interface_series": "head series near the west/centre interface",
        "head_central_high_k_series": "head series in the conductive central corridor",
        "head_east_interface_series": "head series near the centre/east interface",
        "head_east_medium_k_series": "head series in the intermediate east zone",
        "head_domain_low_series": "head series in the lower part of the domain",
        "head_domain_mid_series": "head series in the middle part of the domain",
        "head_domain_high_series": "head series in the upper part of the domain",
    }
    return labels.get(name, name.replace("_", " "))


def _figure_caption(item: Mapping[str, Any]) -> str:
    observable = str(item.get("observable", ""))
    kind = str(item.get("kind", ""))
    if observable == "case_configuration":
        return "Case context: geometry, K zones, recharge and extraction points."
    if kind == "fine_raster_map_comparison":
        return (
            _observable_label(observable)
            + ": reference and candidate on the same interpolated grid."
        )
    if "triptych" in kind or "head_map" in observable:
        return _observable_label(observable) + ": reference, candidate and difference."
    if kind == "timeseries" or observable.endswith("_series"):
        point_label = str(item.get("point_label", "")).strip()
        prefix = f"Point {point_label} - " if point_label else ""
        return prefix + _observable_label(observable) + ": MF6 / Boussinesq time comparison."
    if observable in {"storage_change_total_m3_s", "storage_comparison_dashboard"}:
        return "Global storage: instantaneous change of the volume stored in the aquifer."
    if observable in {"total_inputs_outputs_m3_s", "total_inputs_outputs_dashboard"}:
        return "External budget: sum of inflows and sum of outflows, storage excluded."
    return _observable_label(observable)


def _format_mapping_values(value: Any, *, default: str) -> str:
    if not isinstance(value, Mapping) or not value:
        return default
    labels = {
        "west_low_k": "west",
        "central_high_k": "centre",
        "east_medium_k": "east",
    }
    parts = [
        f"{labels.get(str(key), str(key))}: {_format_value(raw)}" for key, raw in value.items()
    ]
    return "; ".join(parts)


def _format_metric_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    formatted: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        item["observable_label"] = _observable_label(str(row.get("observable", "")))
        for key in (
            "mae",
            "rmse",
            "max_abs_error",
            "normalization_scale",
            "mae_normalized_percent",
            "rmse_normalized_percent",
            "max_abs_error_normalized_percent",
        ):
            item[key] = _format_number(row.get(key))
        formatted.append(item)
    return formatted


def _format_closure_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    formatted: list[dict[str, str]] = []
    for row in rows:
        item = dict(row)
        item["max_abs_closure_m3_s"] = _format_with_unit(row.get("max_abs_closure_m3_s"), "m3/s")
        item["max_abs_closure_mm_d"] = _format_with_unit(row.get("max_abs_closure_mm_d"), "mm/d")
        item["relative_closure_error_p95"] = _format_number(row.get("relative_closure_error_p95"))
        formatted.append(item)
    return formatted


def _metric_snapshot_row(row: Mapping[str, Any]) -> dict[str, Any]:
    unit = str(row.get("unit", "") or "").strip()
    rmse_value = _float_or_none(row.get("rmse"))
    reference_value = _float_or_none(row.get("normalization_scale"))
    rmse_percent = _float_or_none(row.get("rmse_normalized_percent"))
    return {
        "observable_label": str(row.get("observable_label") or row.get("observable") or ""),
        "n_pairs": str(row.get("n_pairs", "")),
        "unit": unit,
        "rmse": _format_with_unit(rmse_value, unit),
        "reference_value": _format_with_unit(reference_value, unit),
        "rmse_percent": _format_percent_value(rmse_percent),
        "rmse_percent_value": rmse_percent,
    }


def _metric_analysis_row(row: Mapping[str, Any]) -> dict[str, Any]:
    observable = str(row.get("observable", ""))
    return {
        "observable": observable,
        "label": _observable_label(observable),
        "rmse": _float_or_none(row.get("rmse")),
        "rmse_percent": _float_or_none(row.get("rmse_normalized_percent")),
        "unit": str(row.get("unit", "") or "").strip(),
    }


def _analysis_row_by_token(
    rows: list[dict[str, Any]],
    token: str,
) -> dict[str, Any] | None:
    token = token.lower()
    for row in rows:
        if token in str(row["observable"]).lower():
            return row
    return None


def _analysis_row_text(row: Mapping[str, Any]) -> str:
    return (
        f"{row['label']} - RMSE {_format_with_unit(row.get('rmse'), str(row.get('unit') or ''))} "
        f"({_format_percent_value(row.get('rmse_percent'))})"
    )


def _render_key_values(rows: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<div><span class="kv-label">{safe(label)}</span><strong>{safe(value)}</strong></div>'
        for label, value in rows
    )


def _render_table(
    rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    columns: list[tuple[str, str]],
    *,
    empty: str,
) -> str:
    materialized = list(rows)
    if not materialized:
        return f'<p class="muted">{safe(empty)}</p>'
    header = "".join(f"<th>{safe(label)}</th>" for _, label in columns)
    body_rows: list[str] = []
    for row in materialized:
        cells = "".join(f"<td>{safe(short(row.get(key, '')))}</td>" for key, _ in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _render_runtime_table(
    rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> str:
    materialized = list(rows)
    if not materialized:
        return '<p class="muted">No simulation in the manifest.</p>'
    runtime_items = [_row_runtime_seconds_with_scope(row) for row in materialized]
    values = [item[0] for item in runtime_items]
    maximum = max([value for value in values if value is not None], default=None)
    body_rows: list[str] = []
    for row, (value, scope) in zip(materialized, runtime_items, strict=False):
        solver = str(row.get("solver", "") or "").strip().lower()
        bar_class = (
            "modflow6" if solver == "modflow6" else "boussinesq" if solver == "boussinesq" else ""
        )
        width = 0.0
        if value is not None and maximum not in (None, 0):
            width = max(2.0, min(100.0, 100.0 * value / maximum))
        runtime = _format_runtime_seconds(value)
        body_rows.append(
            "<tr>"
            f"<td>{safe(short(row.get('id', '')))}</td>"
            f"<td>{safe(short(row.get('solver', '')))}</td>"
            f"<td>{safe(short(row.get('status', '')))}</td>"
            f"<td>{safe(runtime)}</td>"
            f"<td>{safe(scope)}</td>"
            "<td>"
            '<div class="runtime-bar-track">'
            f'<span class="runtime-bar {safe(bar_class)}" style="width: {width:.1f}%"></span>'
            "</div>"
            "</td>"
            "</tr>"
        )
    return (
        '<table class="runtime-table"><thead><tr>'
        "<th>id</th><th>solver</th><th>status</th><th>time</th><th>scope</th><th>comparison</th>"
        f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _render_figures(
    *,
    ctx: ComparisonWebContext,
    figures: list[Mapping[str, Any]],
) -> str:
    blocks: list[str] = []
    for item in figures:
        path = Path(str(item.get("path", "")))
        if not path.is_file():
            continue
        title = Path(path).name
        kind = item.get("kind", "")
        caption = _figure_caption(item)
        blocks.append(
            "<figure>"
            f'<a href="{safe(link_relative(ctx.web_dir, path))}">'
            f'<img src="{safe(link_relative(ctx.web_dir, path))}" alt="{safe(title)}">'
            "</a>"
            f"<figcaption>{safe(caption)}"
            + (
                f'<br><span class="muted">{safe(title)}'
                + (f" - {safe(kind)}" if kind else "")
                + "</span>"
            )
            + "</figcaption></figure>"
        )
    if not blocks:
        return '<p class="muted">No PNG figure available.</p>'
    return "\n".join(blocks)


def _audit_block(audit: Mapping[str, Any]) -> str:
    status = str(audit.get("status", ""))
    issues = audit.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    klass = "warning" if status == "warn" else ""
    lines = [f'<p>Status: <strong class="{klass}">{safe(status or "unknown")}</strong></p>']
    lines.append(f"<p>Issues: <strong>{safe(len(issues))}</strong></p>")
    for issue in issues[:5]:
        if isinstance(issue, Mapping):
            message = issue.get("message", issue.get("description", issue))
        else:
            message = issue
        lines.append(f'<p class="muted">- {safe(short(message, limit=170))}</p>')
    return "\n".join(lines)


def _render_metric_snapshot(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="muted">No metric.</p>'
    numeric_rows = [_metric_snapshot_row(row) for row in rows]
    percentages = [
        item["rmse_percent_value"]
        for item in numeric_rows
        if item["rmse_percent_value"] is not None
    ]
    scale = max(5.0, max(percentages, default=0.0))
    best = min(
        (item for item in numeric_rows if item["rmse_percent_value"] is not None),
        key=lambda item: item["rmse_percent_value"],
        default=None,
    )
    worst = max(
        (item for item in numeric_rows if item["rmse_percent_value"] is not None),
        key=lambda item: item["rmse_percent_value"],
        default=None,
    )
    summary = ""
    if best is not None and worst is not None:
        summary = (
            '<div class="metric-summary">'
            f'<div><span class="kv-label">Closest</span><strong>{safe(best["observable_label"])}</strong><small>{safe(best["rmse_percent"])}</small></div>'
            f'<div><span class="kv-label">Largest difference</span><strong>{safe(worst["observable_label"])}</strong><small>{safe(worst["rmse_percent"])}</small></div>'
            f'<div><span class="kv-label">Reference</span><strong>MF6</strong><small>ref value in {safe(best["unit"] or "unit")}</small></div>'
            "</div>"
        )
    body_rows: list[str] = []
    for item in numeric_rows:
        value = item["rmse_percent_value"]
        width = 0.0 if value is None or scale == 0 else max(2.0, min(100.0, 100.0 * value / scale))
        body_rows.append(
            "<tr>"
            f"<td>{safe(item['observable_label'])}</td>"
            f"<td>{safe(item['n_pairs'])}</td>"
            f"<td>{safe(item['rmse'])}</td>"
            f"<td>{safe(item['reference_value'])}</td>"
            "<td>"
            f"<strong>{safe(item['rmse_percent'])}</strong>"
            '<div class="metric-bar-track">'
            f'<span class="metric-bar" style="width: {width:.1f}%"></span>'
            "</div>"
            "</td>"
            "</tr>"
        )
    table = (
        '<table class="metric-table"><thead><tr>'
        "<th>observable</th><th>n</th><th>RMSE</th><th>ref value</th><th>RMSE / ref</th>"
        f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )
    return summary + table
