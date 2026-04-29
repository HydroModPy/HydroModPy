"""Top-level orchestrator for method-comparison visual outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.analysis.comparison.config import MethodComparisonConfig
from hydromodpy.analysis.comparison.visuals_payloads import (
    MapPayload,
    _build_difference_payload,
    _build_fine_grid,
    _build_map_payload,
    _regrid_payload,
    _resolve_fine_grid_bounds,
    griddata,
)
from hydromodpy.analysis.comparison.visuals_render_maps import (
    _write_difference_figure,
    _write_geotiff,
    _write_map_comparison_figure,
    _write_regridded_difference_figure,
    _write_regridded_map_figure,
)
from hydromodpy.analysis.comparison.visuals_render_series import (
    _write_budget_diagnostic_figure,
    _write_flux_dashboard,
    _write_native_flux_panel,
    _write_point_dashboard,
    _write_runtime_bar_figure,
    _write_timeseries_figure,
)
from hydromodpy.analysis.comparison.visuals_style import _is_flux_like_name, _slug


def generate_comparison_figures(
    *,
    cfg: MethodComparisonConfig,
    variant_summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    detail_metrics: list[dict[str, Any]],
    reference_variant: str | None,
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
        for summary in variant_summaries
        if summary.get("status") in {"completed", "reused"}
    }
    variants = {variant.id: variant for variant in cfg.method_comparison.variant if variant.enabled}

    artifacts: list[dict[str, Any]] = []
    fine_raster = cfg.method_comparison.fine_raster

    for observable in cfg.method_comparison.observable:
        if observable.support != "map":
            continue
        payloads: list[MapPayload] = []
        for variant_id, variant in variants.items():
            summary = completed_summaries.get(variant_id)
            if summary is None:
                continue
            try:
                payload = _build_map_payload(
                    cfg=cfg,
                    variant=variant,
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

        if reference_variant is None:
            continue
        reference_payload = next(
            (payload for payload in payloads if payload.variant_id == reference_variant),
            None,
        )
        if reference_payload is None:
            continue
        for candidate in payloads:
            if candidate.variant_id == reference_variant:
                continue
            difference = _build_difference_payload(
                reference=reference_payload,
                candidate=candidate,
            )
            if difference is None:
                continue
            diff_path = figure_root / (
                f"{_slug(observable.name)}__difference__"
                f"{_slug(reference_variant)}__vs__{_slug(candidate.variant_id)}.png"
            )
            _write_difference_figure(path=diff_path, payload=difference)
            if diff_path.exists():
                artifacts.append(
                    {
                        "kind": "difference_map",
                        "observable": observable.name,
                        "reference_variant": reference_variant,
                        "candidate_variant": candidate.variant_id,
                        "path": str(diff_path),
                    }
                )

        if fine_raster is not None and fine_raster.enabled and griddata is not None:
            bounds = _resolve_fine_grid_bounds(
                payloads=payloads,
                fine_raster=fine_raster,
                reference_variant=reference_variant,
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
                                f"{_slug(payload.variant_id)}.tif"
                            )
                            if _write_geotiff(path=raster_path, array=array, extent=grid_extent):
                                artifacts.append(
                                    {
                                        "kind": "fine_raster_geotiff",
                                        "observable": observable.name,
                                        "variant_id": payload.variant_id,
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
                    if reference_variant is not None:
                        reference_array = next(
                            (
                                array
                                for payload, array in regridded
                                if payload.variant_id == reference_variant
                            ),
                            None,
                        )
                        reference_payload = next(
                            (
                                payload
                                for payload, _array in regridded
                                if payload.variant_id == reference_variant
                            ),
                            None,
                        )
                        if reference_array is not None and reference_payload is not None:
                            for payload, array in regridded:
                                if payload.variant_id == reference_variant:
                                    continue
                                difference_array = np.asarray(array - reference_array, dtype=float)
                                diff_path = figure_root / (
                                    f"{_slug(observable.name)}__fine_raster_difference__"
                                    f"{_slug(reference_variant)}__vs__{_slug(payload.variant_id)}.png"
                                )
                                if _write_regridded_difference_figure(
                                    path=diff_path,
                                    observable_name=observable.name,
                                    candidate_variant=payload.variant_id,
                                    reference_variant=reference_variant,
                                    array=difference_array,
                                    unit=payload.unit,
                                    extent=grid_extent,
                                ):
                                    artifacts.append(
                                        {
                                            "kind": "fine_raster_difference_map",
                                            "observable": observable.name,
                                            "reference_variant": reference_variant,
                                            "candidate_variant": payload.variant_id,
                                            "path": str(diff_path),
                                        }
                                    )
                                if fine_raster.write_geotiff:
                                    raster_path = figure_root / (
                                        f"{_slug(observable.name)}__fine_raster_difference__"
                                        f"{_slug(reference_variant)}__vs__{_slug(payload.variant_id)}.tif"
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
                                                "reference_variant": reference_variant,
                                                "candidate_variant": payload.variant_id,
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
    budget_variants = sorted(
        {
            (
                str(row.get("variant_id", "")),
                str(row.get("variant_label", row.get("variant_id", ""))),
            )
            for row in budget_long
            if str(row.get("variant_id", "")) != ""
        }
    )
    for variant_id, variant_label in budget_variants:
        budget_path = figure_root / f"{_slug(variant_id)}__budget_diagnostics.png"
        if _write_budget_diagnostic_figure(
            path=budget_path,
            variant_id=variant_id,
            variant_label=variant_label,
            budget_rows=budget_long,
            rows=rows,
        ):
            artifacts.append(
                {
                    "kind": "budget_diagnostics",
                    "observable": "budget",
                    "variant_id": variant_id,
                    "path": str(budget_path),
                }
            )

    if execution_rows:
        runtime_path = figure_root / "execution_time_comparison.png"
        if _write_runtime_bar_figure(
            path=runtime_path,
            execution_rows=execution_rows,
            reference_variant=reference_variant,
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
