"""Context loading for static comparison web reports."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.web.figures import (
    FigureCategory,
    categorize_figures,
    configuration_figures,
)


@dataclass(frozen=True)
class ComparisonWebContext:
    """Materialized data needed by the static comparison report."""

    root: Path
    web_dir: Path
    output_path: Path
    manifest: dict[str, Any]
    audit: dict[str, Any]
    metrics_rows: list[dict[str, str]]
    budget_rows: list[dict[str, str]]
    figure_items: list[dict[str, Any]]
    key_figures: list[dict[str, Any]]
    configuration_figures: list[dict[str, Any]]
    figure_categories: list[FigureCategory]
    simulations: list[dict[str, Any]]
    data_links: list[Path]
    comparable_budget_rows: list[dict[str, str]]


def load_comparison_web_context(
    *,
    comparison_root: Path,
    manifest: Mapping[str, Any] | None = None,
    output_path: Path | None = None,
) -> ComparisonWebContext:
    """Load report inputs from a comparison output folder."""
    root = Path(comparison_root).expanduser().resolve()
    web_dir = root / "web"
    out = output_path or (web_dir / "index.html")
    payload = dict(manifest or _load_json(root / "comparison_manifest.json"))
    metrics_rows = _load_csv(root / "comparison_metrics.csv")
    budget_rows = _load_csv(root / "budget_timeseries_wide.csv")
    audit = _load_json(root / "comparison_audit.json")
    figure_items = _figure_items(root=root, manifest=payload)
    simulations = payload.get("simulations", [])
    if not isinstance(simulations, list):
        simulations = []
    comparable_budget_rows = [
        row
        for row in budget_rows
        if str(row.get("component", "")) == "comparable_outflow_total_m3_s"
    ]
    return ComparisonWebContext(
        root=root,
        web_dir=web_dir,
        output_path=out,
        manifest=payload,
        audit=audit,
        metrics_rows=metrics_rows,
        budget_rows=budget_rows,
        figure_items=figure_items,
        key_figures=_select_key_figures(figure_items),
        configuration_figures=configuration_figures(figure_items),
        figure_categories=categorize_figures(figure_items),
        simulations=[dict(item) for item in simulations if isinstance(item, Mapping)],
        data_links=_data_links(root),
        comparable_budget_rows=comparable_budget_rows,
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _figure_items(*, root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    raw_items = manifest.get("comparison_figures", [])
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, Mapping) and str(item.get("path", "")):
                path = Path(str(item["path"]))
                if not path.is_absolute():
                    path = root / path
                if path.is_file():
                    payload = dict(item)
                    payload["path"] = str(path)
                    items.append(payload)
    known = {str(Path(str(item.get("path", ""))).resolve()) for item in items}
    figure_root = root / "comparison_figures"
    if figure_root.is_dir():
        for path in sorted(figure_root.glob("*.png")):
            key = str(path.resolve())
            if key not in known:
                items.append({"kind": "figure", "observable": path.stem, "path": str(path)})
    return items


def _select_key_figures(figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = (
        "case_configuration.png",
        "comparable_outflow_dashboard.png",
        "flux_overview.png",
        "head_points_dashboard.png",
        "head_map_after_first_month__triptych",
        "head_map_wet_period__triptych",
        "head_map_dry_period__triptych",
        "head_map_last__triptych",
        "mf6_ref__budget_diagnostics.png",
        "bouss_candidate__budget_diagnostics.png",
        "execution_time_comparison.png",
    )

    def score(item: Mapping[str, Any]) -> tuple[int, str]:
        name = Path(str(item.get("path", ""))).name
        for index, token in enumerate(priority):
            if token in name:
                return (index, name)
        return (len(priority), name)

    return sorted(figures, key=score)[:18]


def _data_links(root: Path) -> list[Path]:
    names = (
        "comparison_report.md",
        "comparison_audit.md",
        "comparison_manifest.json",
        "comparison_metrics.csv",
        "comparison_differences.csv",
        "observables.csv",
        "budget_timeseries_wide.csv",
        "budget_timeseries_long.csv",
        "timeseries_wide.csv",
        "timeseries_long.csv",
    )
    return [root / name for name in names]


__all__ = ("ComparisonWebContext", "load_comparison_web_context")
