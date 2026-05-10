"""Top-level orchestrator for simulation-comparison visual outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.config import RuntimeComparisonConfig
from hydromodpy.analysis.comparison.visuals_payloads import (
    MapPayload,
    _build_case_configuration_payload,
    _build_fine_grid,
    _build_map_payload,
    _regrid_payload,
    _resolve_fine_grid_bounds,
    griddata,
    observable_point_label_map,
)
from hydromodpy.analysis.comparison.visuals_render_maps import (
    _write_case_configuration_figure,
    _write_geotiff,
    _write_regridded_map_figure,
)
from hydromodpy.analysis.comparison.visuals_render_series import (
    _write_storage_comparison_dashboard,
    _write_timeseries_figure,
    _write_total_input_output_dashboard,
)
from hydromodpy.analysis.comparison.visuals_style import _slug


def _representative_map_observable_names(observables: list[Any]) -> set[str]:
    """Keep the comparison report focused by selecting one map observable."""
    map_observables = [item for item in observables if getattr(item, "support", "") == "map"]
    if not map_observables:
        return set()
    priority = (
        "head_map_wet_year1",
        "head_map_extreme_recharge",
        "head_map_last",
        "head_map_first_computed",
        "head_map_initial",
    )
    by_name = {str(item.name): item for item in map_observables}
    for name in priority:
        if name in by_name:
            return {name}
    return {str(map_observables[0].name)}


def generate_comparison_figures(
    *,
    cfg: RuntimeComparisonConfig,
    simulation_summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    detail_metrics: list[dict[str, Any]],
    reference_simulation: str | None,
    comparison_root: Path,
    native_timeseries_rows: list[dict[str, Any]] | None = None,
    native_timeseries_delta_rows: list[dict[str, Any]] | None = None,
    budget_rows: list[dict[str, Any]] | None = None,
    execution_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Generate best-effort PNG comparisons from extracted observables."""
    figure_root = comparison_root / "comparison_figures"
    figure_root.mkdir(parents=True, exist_ok=True)
    for existing_path in figure_root.glob("*"):
        if existing_path.is_file():
            try:
                existing_path.unlink()
            except OSError:
                pass

    completed_summaries = {
        str(summary.get("id", "")): summary
        for summary in simulation_summaries
        if summary.get("status") in {"completed", "reused"}
    }
    simulations = {
        simulation.id: simulation for simulation in cfg.comparison.simulation if simulation.enabled
    }

    artifacts: list[dict[str, Any]] = []
    fine_raster = cfg.comparison.fine_raster
    try:
        case_payload = _build_case_configuration_payload(
            cfg=cfg,
            simulation_summaries=simulation_summaries,
            reference_simulation=reference_simulation,
        )
    except Exception:
        case_payload = None
    if case_payload is not None:
        case_path = figure_root / "case_configuration.png"
        if _write_case_configuration_figure(path=case_path, payload=case_payload):
            artifacts.append(
                {
                    "kind": "case_configuration",
                    "observable": "case_configuration",
                    "path": str(case_path),
                }
            )

    representative_map_names = _representative_map_observable_names(list(cfg.comparison.observable))
    point_labels = observable_point_label_map(tuple(cfg.comparison.observable))
    for observable in cfg.comparison.observable:
        if observable.support != "map":
            continue
        if observable.name not in representative_map_names:
            continue
        payloads: list[MapPayload] = []
        for simulation_id, simulation in simulations.items():
            summary = completed_summaries.get(simulation_id)
            if summary is None:
                continue
            try:
                payload = _build_map_payload(
                    cfg=cfg,
                    simulation=simulation,
                    summary=summary,
                    observable=observable,
                    rows=rows,
                )
            except Exception:
                payload = None
            if payload is not None:
                payloads.append(payload)

        if reference_simulation is None:
            continue
        reference_payload = next(
            (payload for payload in payloads if payload.simulation_id == reference_simulation),
            None,
        )
        if reference_payload is None:
            continue

        if fine_raster is not None and fine_raster.enabled and griddata is not None:
            bounds = _resolve_fine_grid_bounds(
                payloads=payloads,
                fine_raster=fine_raster,
                reference_simulation=reference_simulation,
            )
            if bounds is not None:
                fine_grid = _build_fine_grid(
                    bounds=bounds,
                    resolution=float(fine_raster.resolution or 0.0),
                )
                if fine_grid is not None:
                    grid_x, grid_y, grid_extent = fine_grid
                    regridded: list[tuple[MapPayload, np.ndarray]] = []
                    for payload in payloads:
                        array = _regrid_payload(
                            payload=payload,
                            grid_x=grid_x,
                            grid_y=grid_y,
                            interpolation=fine_raster.interpolation,
                        )
                        if array is None:
                            continue
                        regridded.append((payload, array))
                        if fine_raster.write_geotiff:
                            raster_path = figure_root / (
                                f"{_slug(observable.name)}__fine_raster__"
                                f"{_slug(payload.simulation_id)}.tif"
                            )
                            if _write_geotiff(path=raster_path, array=array, extent=grid_extent):
                                artifacts.append(
                                    {
                                        "kind": "fine_raster_geotiff",
                                        "observable": observable.name,
                                        "simulation_id": payload.simulation_id,
                                        "path": str(raster_path),
                                    }
                                )
                    if len(regridded) >= 1:
                        fine_map_path = figure_root / (
                            f"{_slug(observable.name)}__fine_raster_map_comparison.png"
                        )
                        if _write_regridded_map_figure(
                            path=fine_map_path,
                            observable_name=observable.name,
                            arrays=regridded,
                            extent=grid_extent,
                        ):
                            artifacts.append(
                                {
                                    "kind": "fine_raster_map_comparison",
                                    "observable": observable.name,
                                    "path": str(fine_map_path),
                                }
                            )

    grouped_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("support", "")) == "map":
            continue
        if str(row.get("comparison_time_key", "")) == "reduced":
            continue
        key = (str(row.get("observable", "")), str(row.get("unit", "")))
        grouped_rows.setdefault(key, []).append(row)

    for (observable_name, unit), grouped in sorted(grouped_rows.items()):
        series_path = figure_root / f"{_slug(observable_name)}__timeseries.png"
        point_label = point_labels.get(observable_name, "")
        if _write_timeseries_figure(
            path=series_path,
            observable_name=observable_name,
            unit=unit,
            grouped_rows=grouped,
            point_label=point_label,
        ):
            artifacts.append(
                {
                    "kind": "timeseries",
                    "observable": observable_name,
                    "unit": unit,
                    "point_label": point_label,
                    "path": str(series_path),
                }
            )

    native_long = list(native_timeseries_rows or [])
    del native_long, native_timeseries_delta_rows

    budget_long = list(budget_rows or [])
    storage_path = figure_root / "storage_comparison_dashboard.png"
    if _write_storage_comparison_dashboard(
        path=storage_path,
        budget_rows=budget_long,
    ):
        artifacts.append(
            {
                "kind": "storage_comparison_dashboard",
                "observable": "storage_change_total_m3_s",
                "path": str(storage_path),
            }
        )

    totals_path = figure_root / "total_inputs_outputs_dashboard.png"
    if _write_total_input_output_dashboard(
        path=totals_path,
        budget_rows=budget_long,
    ):
        artifacts.append(
            {
                "kind": "total_inputs_outputs_dashboard",
                "observable": "total_inputs_outputs_m3_s",
                "path": str(totals_path),
            }
        )
    del execution_rows

    return artifacts


__all__ = ("generate_comparison_figures",)
