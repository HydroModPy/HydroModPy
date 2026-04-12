"""Human-readable reporting helpers for method-comparison runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


def _format_number(value: Any) -> str:
    if value in ("", None):
        return ""
    try:
        return f"{float(value):.6g}"
    except Exception:
        return str(value)


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("observable", "")),
        str(row.get("comparison_time_key", row.get("time", ""))),
        str(row.get("value_index", "")),
        str(row.get("unit", "")),
    )


def _build_unmatched_groups(
    rows: list[dict[str, Any]],
    *,
    reference_variant: str | None,
) -> list[dict[str, Any]]:
    if not rows or reference_variant is None:
        return []

    reference_keys = {
        _row_key(row)
        for row in rows
        if str(row.get("variant_id", "")) == reference_variant
    }
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        variant_id = str(row.get("variant_id", ""))
        if variant_id == reference_variant:
            continue
        if _row_key(row) in reference_keys:
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
                "reason": "missing reference row or unit mismatch",
            }
        )
    return items


def build_comparison_report(
    *,
    comparison_id: str,
    reference_variant: str | None,
    variant_summaries: list[dict[str, Any]],
    observables: Iterable[Mapping[str, Any]],
    rows: list[dict[str, Any]],
    summary_metrics: list[dict[str, Any]],
) -> str:
    """Build a short Markdown report for one comparison run."""
    unmatched = _build_unmatched_groups(rows, reference_variant=reference_variant)
    completed_variants = [
        summary for summary in variant_summaries if summary.get("status") in {"completed", "reused"}
    ]

    lines = [
        f"# Method Comparison Report: {comparison_id}",
        "",
        f"- Reference variant: `{reference_variant or 'none'}`",
        f"- Completed variants: {len(completed_variants)} / {len(variant_summaries)}",
        f"- Observable rows: {len(rows)}",
        f"- Comparable metric groups: {len(summary_metrics)}",
        f"- Unmatched row groups: {len(unmatched)}",
        "",
        "## Variants",
    ]
    for summary in variant_summaries:
        wall_time = summary.get("wall_time_seconds")
        run_folder = summary.get("run_folder", "")
        lines.append(
            f"- `{summary.get('id', '')}`: {summary.get('status', '')}"
            f", solver=`{summary.get('solver', '') or 'n/a'}`"
            f", mesh=`{summary.get('mesh_mode', '')}`"
            f", rows={summary.get('n_observable_rows', 0)}"
            f", wall_time={_format_number(wall_time)}"
            f", run_folder=`{run_folder}`"
        )

    lines.extend(
        [
            "",
            "## Observables",
        ]
    )
    for observable in observables:
        lines.append(
            f"- `{observable.get('name', '')}`:"
            f" variable=`{observable.get('variable', '')}`"
            f", support=`{observable.get('support', '')}`"
            f", unit=`{observable.get('unit', '') or 'native'}`"
        )

    lines.extend(
        [
            "",
            "## Metrics",
        ]
    )
    if not summary_metrics:
        lines.append("- No comparable metric groups were produced.")
    else:
        lines.append(
            "| Variant | Observable | Unit | Pairs | Bias | MAE | RMSE | Max abs | Mean rel |"
        )
        lines.append(
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
        )
        for row in summary_metrics:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(row.get("variant_id", "")),
                        str(row.get("observable", "")),
                        str(row.get("unit", "")),
                        str(row.get("n_pairs", "")),
                        _format_number(row.get("bias")),
                        _format_number(row.get("mae")),
                        _format_number(row.get("rmse")),
                        _format_number(row.get("max_abs_error")),
                        _format_number(row.get("mean_relative_error")),
                    ]
                )
                + " |"
            )

    lines.extend(
        [
            "",
            "## Gaps",
        ]
    )
    if not unmatched:
        lines.append("- No unmatched rows.")
    else:
        for item in unmatched:
            lines.append(
                f"- `{item['variant_id']}` / `{item['observable']}` / `{item['unit'] or 'no-unit'}`:"
                f" {item['n_rows']} rows skipped ({item['reason']})."
            )

    return "\n".join(lines).rstrip() + "\n"


__all__ = ("build_comparison_report",)
