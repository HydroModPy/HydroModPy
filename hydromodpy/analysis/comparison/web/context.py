"""Context loading for static comparison web reports."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.analysis.comparison.web.figures import (
    FigureCategory,
    categorize_figures,
    configuration_figures,
    include_in_comparison_report,
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
    numerical_closure_rows: list[dict[str, str]]
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
    numerical_closure_rows = _load_csv(root / "numerical_closure_summary.csv")
    budget_rows = _load_csv(root / "budget_timeseries_wide.csv")
    audit = _load_json(root / "comparison_audit.json")
    _ensure_domain_head_profile_figures(root=root, manifest=payload)
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
        numerical_closure_rows=numerical_closure_rows,
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
                if path.is_file() and path.suffix.lower() in {
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".svg",
                }:
                    payload = dict(item)
                    payload["path"] = str(path)
                    if include_in_comparison_report(payload):
                        items.append(payload)
    known = {str(Path(str(item.get("path", ""))).resolve()) for item in items}
    figure_root = root / "comparison_figures"
    if figure_root.is_dir():
        for path in sorted(figure_root.glob("*.png")):
            key = str(path.resolve())
            if key not in known:
                name = path.name.lower()
                observable = path.stem
                kind = "figure"
                if name.startswith("head_") and name.endswith("__timeseries.png"):
                    kind = "timeseries"
                    observable = path.stem.removesuffix("__timeseries")
                payload = {"kind": kind, "observable": observable, "path": str(path)}
                if include_in_comparison_report(payload):
                    items.append(payload)
    return items


def _ensure_domain_head_profile_figures(*, root: Path, manifest: Mapping[str, Any]) -> None:
    figure_root = root / "comparison_figures"
    rows = _load_csv(root / "observables.csv")
    if not rows:
        _remove_domain_head_profile_figures(figure_root)
        return
    profile_indices = _domain_head_profile_indices(rows, manifest=manifest)
    if not profile_indices:
        _remove_domain_head_profile_figures(figure_root)
        return
    profiles = _domain_head_profile_series(
        root=root,
        manifest=manifest,
        profile_indices=profile_indices,
    )
    if not profiles:
        _remove_domain_head_profile_figures(figure_root)
        return
    try:
        from hydromodpy.analysis.comparison.visuals_render_series import _write_timeseries_figure
    except Exception:
        _remove_domain_head_profile_figures(figure_root)
        return
    _remove_domain_head_profile_figures(figure_root)
    figure_root.mkdir(parents=True, exist_ok=True)
    for profile_id, label, grouped_rows in profiles:
        if not grouped_rows:
            continue
        path = figure_root / f"head_domain_{profile_id}_series__timeseries.png"
        try:
            _write_timeseries_figure(
                path=path,
                observable_name=f"head_domain_{profile_id}_series",
                unit="m",
                grouped_rows=grouped_rows,
                point_label=label,
            )
        except Exception:
            continue


def _remove_domain_head_profile_figures(figure_root: Path) -> None:
    if not figure_root.is_dir():
        return
    for path in figure_root.glob("head_domain_*_series__timeseries.png"):
        try:
            path.unlink()
        except OSError:
            pass


def _domain_head_profile_indices(
    rows: list[dict[str, str]],
    *,
    manifest: Mapping[str, Any],
) -> list[tuple[str, str, int, float | None, float | None]]:
    head_map_rows = [
        row
        for row in rows
        if str(row.get("support", "")) == "map"
        and str(row.get("observable", "")).startswith("head_map")
        and _float_or_none(row.get("value")) is not None
        and str(row.get("is_nodata", "")).strip().lower() not in {"true", "1", "yes"}
    ]
    if not head_map_rows:
        return []
    reference = str(manifest.get("reference_simulation", "")).strip()
    reference_rows = [
        row
        for row in head_map_rows
        if not reference or str(row.get("simulation_id", "")) == reference
    ]
    if not reference_rows:
        reference_rows = head_map_rows
    first_key = _first_profile_time_key(reference_rows)
    candidates = [
        row
        for row in reference_rows
        if _profile_time_key(row) == first_key
        and str(row.get("value_index", "")).strip()
        and _float_or_none(row.get("surface_top_m")) is not None
    ]
    if len(candidates) < 3:
        candidates = [
            row
            for row in reference_rows
            if _profile_time_key(row) == first_key and str(row.get("value_index", "")).strip()
        ]
    if len(candidates) < 3:
        return []
    ordered = sorted(
        candidates,
        key=lambda row: (
            _float_or_none(row.get("surface_top_m")) is None,
            _float_or_none(row.get("surface_top_m")) or 0.0,
            int(float(row.get("value_index", 0))),
        ),
    )
    picks = [
        ("low", "domaine bas", ordered[max(0, round((len(ordered) - 1) * 0.2))]),
        ("mid", "domaine median", ordered[max(0, round((len(ordered) - 1) * 0.5))]),
        ("high", "domaine haut", ordered[max(0, round((len(ordered) - 1) * 0.8))]),
    ]
    profiles: list[tuple[str, str, int, float | None, float | None]] = []
    used_indices: set[str] = set()
    for profile_id, label, picked in picks:
        value_index = str(picked.get("value_index", "")).strip()
        if not value_index or value_index in used_indices:
            continue
        used_indices.add(value_index)
        try:
            index = int(float(value_index))
        except Exception:
            continue
        profiles.append(
            (
                profile_id,
                label,
                index,
                _float_or_none(picked.get("surface_top_m")),
                _float_or_none(picked.get("surface_bottom_m")),
            )
        )
    return profiles[:3]


def _domain_head_profile_series(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    profile_indices: list[tuple[str, str, int, float | None, float | None]],
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    simulations = manifest.get("simulations", [])
    if not isinstance(simulations, list):
        return []
    profiles: dict[str, tuple[str, list[dict[str, Any]]]] = {
        profile_id: (label, []) for profile_id, label, _, _, _ in profile_indices
    }
    for simulation in simulations:
        if not isinstance(simulation, Mapping):
            continue
        if str(simulation.get("status", "")).strip().lower() not in {"completed", "reused"}:
            continue
        run_folder = _local_path(simulation.get("run_folder"), root=root)
        if run_folder is None or not run_folder.exists():
            continue
        try:
            from hydromodpy.analysis.comparison.runtime import load_variable_series
            from hydromodpy.results.catalog import SimulationCatalog
        except Exception:
            continue
        simulation_id = str(simulation.get("id", "") or "")
        simulation_label = str(simulation.get("label", simulation_id) or simulation_id)
        solver = str(simulation.get("solver", "") or "")
        store = None
        try:
            store = SimulationCatalog(run_folder)
            series = load_variable_series(
                run_folder=run_folder,
                variable="watertable_elevation",
                store=store,
                sim_id=str(simulation.get("sim_id", "") or ""),
            )
            for profile_id, _, value_index, top, bottom in profile_indices:
                label, grouped_rows = profiles[profile_id]
                for time_order, time_slice in enumerate(series.slices):
                    values = time_slice.values.ravel()
                    if value_index >= int(values.size):
                        continue
                    value = _float_or_none(values[value_index])
                    if value is None:
                        continue
                    grouped_rows.append(
                        {
                            "simulation_id": simulation_id,
                            "simulation_label": simulation_label,
                            "solver": solver,
                            "observable": f"head_domain_{profile_id}_series",
                            "support": "point",
                            "time_index": time_slice.time_index,
                            "elapsed_seconds": (
                                ""
                                if time_slice.elapsed_seconds is None
                                else float(time_slice.elapsed_seconds)
                            ),
                            "selection_time_order": time_order,
                            "value_index": 0,
                            "value": value,
                            "unit": "m",
                            "surface_top_m": "" if top is None else top,
                            "surface_bottom_m": "" if bottom is None else bottom,
                        }
                    )
        except Exception:
            continue
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception:
                    pass
    return [
        (profile_id, label, grouped_rows)
        for profile_id, (label, grouped_rows) in profiles.items()
        if _profile_has_two_methods(grouped_rows)
    ]


def _local_path(value: Any, *, root: Path) -> Path | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    candidates: list[Path] = []
    normalized = text.replace("\\", "/")
    if normalized.startswith("/mnt/") and len(normalized) > 6 and normalized[6] == "/":
        drive = normalized[5].upper()
        candidates.append(Path(f"{drive}:/" + normalized[7:]))
    candidates.append(Path(text))
    if not Path(text).is_absolute():
        candidates.append((root / text).resolve())
        candidates.append((root.parent / text).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1] if candidates else None


def _first_profile_time_key(rows: list[dict[str, str]]) -> tuple[float, str]:
    return min((_profile_time_key(row) for row in rows), default=(math.inf, ""))


def _profile_time_key(row: Mapping[str, Any]) -> tuple[float, str]:
    elapsed = _float_or_none(row.get("elapsed_seconds"))
    if elapsed is not None:
        return elapsed, str(row.get("observable", ""))
    time_index = _float_or_none(row.get("time_index"))
    if time_index is not None:
        return time_index, str(row.get("observable", ""))
    return math.inf, str(row.get("observable", ""))


def _profile_has_two_methods(rows: list[Mapping[str, Any]]) -> bool:
    by_simulation: dict[str, int] = {}
    for row in rows:
        if _float_or_none(row.get("value")) is None:
            continue
        simulation_id = str(row.get("simulation_id", "")).strip()
        if not simulation_id:
            continue
        by_simulation[simulation_id] = by_simulation.get(simulation_id, 0) + 1
    return sum(1 for count in by_simulation.values() if count >= 2) >= 2


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _select_key_figures(figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = (
        "case_configuration.png",
        "head_map_wet_year1__fine_raster_map_comparison",
        "head_central_high_k_series__timeseries",
        "head_west_low_k_series__timeseries",
        "head_west_interface_series__timeseries",
        "head_east_interface_series__timeseries",
        "head_east_medium_k_series__timeseries",
        "storage_comparison_dashboard.png",
        "total_inputs_outputs_dashboard.png",
    )

    def score(item: Mapping[str, Any]) -> tuple[int, str]:
        name = Path(str(item.get("path", ""))).name
        for index, token in enumerate(priority):
            if token in name:
                return (index, name)
        return (len(priority), name)

    return sorted(figures, key=score)[:12]


def _data_links(root: Path) -> list[Path]:
    names = (
        "comparison_report.md",
        "comparison_audit.md",
        "comparison_manifest.json",
        "comparison_metrics.csv",
        "comparison_differences.csv",
        "numerical_closure_summary.csv",
        "numerical_closure_by_period.csv",
        "observables.csv",
        "budget_timeseries_wide.csv",
        "budget_timeseries_long.csv",
        "timeseries_wide.csv",
        "timeseries_long.csv",
    )
    return [root / name for name in names]


__all__ = ("ComparisonWebContext", "load_comparison_web_context")
