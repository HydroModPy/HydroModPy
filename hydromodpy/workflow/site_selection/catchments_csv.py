"""Run the selection stage on a CSV of catchments that were delineated beforehand."""

from __future__ import annotations

import csv
from pathlib import Path

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.spatial.site_selection.domain.candidate_outlet import CandidateOutlet
from hydromodpy.spatial.site_selection.domain.delineated_catchment import DelineatedCatchment
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionResult
from hydromodpy.spatial.site_selection.hydrology.flow_products import FlowProductsBuilder
from hydromodpy.spatial.site_selection.pipelines.build import select_catchments_and_write_outputs
from hydromodpy.workflow.site_selection.config_paths import (
    resolve_csv_path,
    with_default_data_root,
)
from hydromodpy.workflow.site_selection.data_loading import DemLoader, load_site_selection_config
from hydromodpy.workflow.site_selection.dem_request import (
    maybe_delineate_from_outlets,
    maybe_resolve_map_dem_for_review,
)
from hydromodpy.workflow.site_selection.selection_plan import ReportRenderer

__all__ = [
    "load_delineated_catchments_csv",
    "select_delineated_catchments_from_csv",
]


def _required_text(row: dict[str, str], field: str, *, row_number: int) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise DataContractViolation(
            f"catchments CSV row {row_number} is missing required field {field!r}."
        )
    return value


def _float_from_row(
    row: dict[str, str],
    field: str,
    *,
    fallback_field: str,
    row_number: int,
) -> float:
    value = row.get(field)
    if value in {None, ""}:
        value = row.get(fallback_field)
    number = _optional_float(value)
    if number is None:
        raise DataContractViolation(
            f"catchments CSV row {row_number} is missing numeric {field!r} "
            f"or fallback {fallback_field!r}."
        )
    return number


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return float(text)


def load_delineated_catchments_csv(path: str | Path) -> list[DelineatedCatchment]:
    """Load a small delineated-catchment CSV for selection-only workflows."""

    source = Path(path).expanduser().resolve()
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    catchments: list[DelineatedCatchment] = []
    for index, row in enumerate(rows, start=1):
        site_id = _required_text(row, "site_id", row_number=index)
        x = _float_from_row(row, "x_outlet", fallback_field="x", row_number=index)
        y = _float_from_row(row, "y_outlet", fallback_field="y", row_number=index)
        area_km2 = _optional_float(row.get("area_km2"))
        outlet = CandidateOutlet(
            candidate_id=row.get("candidate_id") or site_id,
            x=x,
            y=y,
            crs=row.get("outlet_crs") or row.get("crs") or "EPSG:2154",
            source=row.get("source") or "delineated_csv",
            source_feature_id=row.get("source_feature_id") or site_id,
            source_label=row.get("site_label") or site_id,
            priority=_optional_float(row.get("priority")) or 0.0,
            attributes={str(key): value for key, value in row.items()},
        )
        catchments.append(
            DelineatedCatchment(
                site_id=site_id,
                outlet=outlet,
                outlet_shp=resolve_csv_path(row.get("outlet_shp"), base_dir=source.parent),
                outlet_snap_shp=resolve_csv_path(
                    row.get("outlet_snap_shp"),
                    base_dir=source.parent,
                ),
                watershed_tif=resolve_csv_path(row.get("watershed_tif"), base_dir=source.parent),
                watershed_shp=resolve_csv_path(row.get("watershed_shp"), base_dir=source.parent),
                area_km2=area_km2,
                status=row.get("status") or "delineated",
                failure_reason=row.get("failure_reason") or "",
            )
        )
    return catchments


def select_delineated_catchments_from_csv(
    *,
    config_path: str | Path,
    catchments_csv: str | Path,
    output_root: str | Path | None = None,
    region_id: str = "",
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    dem_loader: DemLoader | None = None,
    report_renderer: ReportRenderer | None = None,
) -> tuple[SelectionResult, dict[str, Path]]:
    """Run the selection stage from a pre-delineated catchments CSV."""

    cfg = load_site_selection_config(config_path)
    catchments = load_delineated_catchments_csv(catchments_csv)
    target_root = Path(output_root).expanduser().resolve() if output_root else cfg.output_root
    cfg_for_outputs = with_default_data_root(cfg.model_copy(update={"output_root": target_root}))
    catchments, flow_manifest = maybe_delineate_from_outlets(
        catchments=catchments,
        config=cfg_for_outputs,
        config_path=Path(config_path).expanduser().resolve(),
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        dem_loader=dem_loader,
    )
    if not flow_manifest:
        flow_manifest = maybe_resolve_map_dem_for_review(
            config=cfg_for_outputs,
            catchments=catchments,
            config_path=Path(config_path).expanduser().resolve(),
            dem_loader=dem_loader,
        )
    _, result, _, paths = select_catchments_and_write_outputs(
        catchments,
        config=cfg,
        root=target_root,
        action="delineated_catchments",
        region_id=region_id,
        flow_manifest=flow_manifest,
        manifest_config=cfg_for_outputs,
        input_paths={"catchments_csv": catchments_csv},
        report_renderer=report_renderer,
    )
    return result, paths
