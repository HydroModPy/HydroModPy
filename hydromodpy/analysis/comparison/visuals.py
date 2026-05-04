"""Top-level orchestrator for simulation-comparison visual outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.config import ComparisonConfig
from hydromodpy.analysis.comparison.visuals_payloads import (
    MapPayload,
    _build_case_configuration_payload,
    _build_difference_payload,
    _build_fine_grid,
    _build_map_payload,
    _regrid_payload,
    _resolve_fine_grid_bounds,
    griddata,
)
from hydromodpy.analysis.comparison.visuals_render_maps import (
    _write_case_configuration_figure,
    _write_difference_figure,
    _write_geotiff,
    _write_map_comparison_figure,
    _write_map_triptych_figure,
    _write_regridded_difference_figure,
    _write_regridded_map_figure,
    _write_regridded_triptych_figure,
)
from hydromodpy.analysis.comparison.visuals_render_series import (
    _write_budget_diagnostic_figure,
    _write_comparable_outflow_dashboard,
    _write_flux_dashboard,
    _write_native_flux_panel,
    _write_point_dashboard,
    _write_runtime_bar_figure,
    _write_timeseries_figure,
)
from hydromodpy.analysis.comparison.visuals_style import _is_flux_like_name, _slug


def generate_comparison_figures(
    *,
    cfg: ComparisonConfig,
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

    for observable in cfg.comparison.observable:
        if observable.support != "map":
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

        if len(payloads) >= 1:
            map_path = figure_root / f"{_slug(observable.name)}__map_comparison.png"
            _write_map_comparison_figure(
                path=map_path,
                observable_name=observable.name,
                payloads=payloads,
            )
            if map_path.exists():
                artifacts.append(
                    {
                        "kind": "map_comparison",
                        "observable": observable.name,
                        "path": str(map_path),
                    }
                )

        if reference_simulation is None:
            continue
        reference_payload = next(
            (payload for payload in payloads if payload.simulation_id == reference_simulation),
            None,
        )
        if reference_payload is None:
            continue
        for candidate in payloads:
            if candidate.simulation_id == reference_simulation:
                continue
            difference = _build_difference_payload(
                reference=reference_payload,
                candidate=candidate,
            )
            if difference is None:
                continue
            diff_path = figure_root / (
                f"{_slug(observable.name)}__difference__"
                f"{_slug(reference_simulation)}__vs__{_slug(candidate.simulation_id)}.png"
            )
            _write_difference_figure(path=diff_path, payload=difference)
            if diff_path.exists():
                artifacts.append(
                    {
                        "kind": "difference_map",
                        "observable": observable.name,
                        "reference_simulation": reference_simulation,
                        "candidate_simulation": candidate.simulation_id,
                        "path": str(diff_path),
                    }
                )
            triptych_path = figure_root / (
                f"{_slug(observable.name)}__triptych__"
                f"{_slug(reference_simulation)}__vs__{_slug(candidate.simulation_id)}.png"
            )
            if _write_map_triptych_figure(
                path=triptych_path,
                reference=reference_payload,
                candidate=candidate,
                difference=difference,
            ):
                artifacts.append(
                    {
                        "kind": "map_triptych",
                        "observable": observable.name,
                        "reference_simulation": reference_simulation,
                        "candidate_simulation": candidate.simulation_id,
                        "path": str(triptych_path),
                    }
                )

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
                    if reference_simulation is not None:
                        reference_array = next(
                            (
                                array
                                for payload, array in regridded
                                if payload.simulation_id == reference_simulation
                            ),
                            None,
                        )
                        reference_payload = next(
                            (
                                payload
                                for payload, _array in regridded
                                if payload.simulation_id == reference_simulation
                            ),
                            None,
                        )
                        if reference_array is not None and reference_payload is not None:
                            for payload, array in regridded:
                                if payload.simulation_id == reference_simulation:
                                    continue
                                difference_array = np.asarray(array - reference_array, dtype=float)
                                triptych_path = figure_root / (
                                    f"{_slug(observable.name)}__fine_raster_triptych__"
                                    f"{_slug(reference_simulation)}__vs__{_slug(payload.simulation_id)}.png"
                                )
                                if _write_regridded_triptych_figure(
                                    path=triptych_path,
                                    observable_name=observable.name,
                                    reference_payload=reference_payload,
                                    candidate_payload=payload,
                                    reference_array=reference_array,
                                    candidate_array=array,
                                    extent=grid_extent,
                                ):
                                    artifacts.append(
                                        {
                                            "kind": "fine_raster_triptych",
                                            "observable": observable.name,
                                            "reference_simulation": reference_simulation,
                                            "candidate_simulation": payload.simulation_id,
                                            "path": str(triptych_path),
                                        }
                                    )
                                diff_path = figure_root / (
                                    f"{_slug(observable.name)}__fine_raster_difference__"
                                    f"{_slug(reference_simulation)}__vs__{_slug(payload.simulation_id)}.png"
                                )
                                if _write_regridded_difference_figure(
                                    path=diff_path,
                                    observable_name=observable.name,
                                    candidate_simulation=payload.simulation_id,
                                    reference_simulation=reference_simulation,
                                    array=difference_array,
                                    unit=payload.unit,
                                    extent=grid_extent,
                                ):
                                    artifacts.append(
                                        {
                                            "kind": "fine_raster_difference_map",
                                            "observable": observable.name,
                                            "reference_simulation": reference_simulation,
                                            "candidate_simulation": payload.simulation_id,
                                            "path": str(diff_path),
                                        }
                                    )
                                if fine_raster.write_geotiff:
                                    raster_path = figure_root / (
                                        f"{_slug(observable.name)}__fine_raster_difference__"
                                        f"{_slug(reference_simulation)}__vs__{_slug(payload.simulation_id)}.tif"
                                    )
                                    if _write_geotiff(
                                        path=raster_path,
                                        array=difference_array,
                                        extent=grid_extent,
                                    ):
                                        artifacts.append(
                                            {
                                                "kind": "fine_raster_difference_geotiff",
                                                "observable": observable.name,
                                                "reference_simulation": reference_simulation,
                                                "candidate_simulation": payload.simulation_id,
                                                "path": str(raster_path),
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
        if _write_timeseries_figure(
            path=series_path,
            observable_name=observable_name,
            unit=unit,
            grouped_rows=grouped,
        ):
            artifacts.append(
                {
                    "kind": "timeseries",
                    "observable": observable_name,
                    "unit": unit,
                    "path": str(series_path),
                }
            )

    native_long = list(native_timeseries_rows or [])
    native_delta = list(native_timeseries_delta_rows or [])

    point_dashboard_path = figure_root / "head_points_dashboard.png"
    if _write_point_dashboard(path=point_dashboard_path, rows=rows):
        artifacts.append(
            {
                "kind": "point_dashboard",
                "observable": "head_points",
                "path": str(point_dashboard_path),
            }
        )

    native_variables = sorted(
        {
            str(row.get("variable", ""))
            for row in native_long
            if _is_flux_like_name(str(row.get("variable", "")))
        }
    )
    for variable in native_variables:
        flux_path = figure_root / f"native_{_slug(variable)}__hydrograph.png"
        if _write_native_flux_panel(
            path=flux_path,
            variable=variable,
            long_rows=native_long,
            delta_rows=native_delta,
        ):
            artifacts.append(
                {
                    "kind": "native_flux_panel",
                    "observable": variable,
                    "path": str(flux_path),
                }
            )

    flux_dashboard_path = figure_root / "flux_overview.png"
    if _write_flux_dashboard(
        path=flux_dashboard_path,
        rows=rows,
        native_long_rows=native_long,
    ):
        artifacts.append(
            {
                "kind": "flux_dashboard",
                "observable": "flux_overview",
                "path": str(flux_dashboard_path),
            }
        )

    budget_long = list(budget_rows or [])
    comparable_outflow_path = figure_root / "comparable_outflow_dashboard.png"
    if _write_comparable_outflow_dashboard(
        path=comparable_outflow_path,
        budget_rows=budget_long,
        rows=rows,
    ):
        artifacts.append(
            {
                "kind": "comparable_outflow_dashboard",
                "observable": "comparable_outflow_total_m3_s",
                "path": str(comparable_outflow_path),
            }
        )

    budget_simulations = sorted(
        {
            (
                str(row.get("simulation_id", "")),
                str(row.get("simulation_label", row.get("simulation_id", ""))),
            )
            for row in budget_long
            if str(row.get("simulation_id", "")) != ""
        }
    )
    for simulation_id, simulation_label in budget_simulations:
        budget_path = figure_root / f"{_slug(simulation_id)}__budget_diagnostics.png"
        if _write_budget_diagnostic_figure(
            path=budget_path,
            simulation_id=simulation_id,
            simulation_label=simulation_label,
            budget_rows=budget_long,
            rows=rows,
        ):
            artifacts.append(
                {
                    "kind": "budget_diagnostics",
                    "observable": "budget",
                    "simulation_id": simulation_id,
                    "path": str(budget_path),
                }
            )

    if execution_rows:
        runtime_path = figure_root / "execution_time_comparison.png"
        if _write_runtime_bar_figure(
            path=runtime_path,
            execution_rows=execution_rows,
            reference_simulation=reference_simulation,
        ):
            artifacts.append(
                {
                    "kind": "execution_time_bars",
                    "observable": "execution_time",
                    "path": str(runtime_path),
                }
            )

    return artifacts


__all__ = ("generate_comparison_figures",)
