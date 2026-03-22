"""Outlet-table IO helpers for the mesh-catchment batch launcher."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import rasterio


_VECTOR_TABLE_SUFFIXES = {".geojson", ".gpkg", ".json", ".shp"}


@dataclass(frozen=True)
class MeshCatchmentOutletRecord:
    """One normalized outlet row ready to drive a child catchment run."""

    outlet_id: str
    outlet_id_safe: str
    x_outlet: float
    y_outlet: float


def sanitize_batch_path_token(raw_value: object) -> str:
    """Convert one user-facing token into a filesystem-safe path fragment."""
    text = str(raw_value).strip()
    if text == "":
        return "unknown"
    collapsed = re.sub(r"\s+", "_", text)
    sanitized = re.sub(r'[\\/:*?"<>|]+', "-", collapsed)
    sanitized = sanitized.strip("._-")
    return sanitized or "unknown"


def load_mesh_catchment_outlet_records(
    *,
    table_path: Path,
    selection_mode: str,
    selected_outlet_ids: Sequence[str],
    outlet_id_column: str,
    x_column: str,
    y_column: str,
) -> list[MeshCatchmentOutletRecord]:
    """Load and normalize outlet rows from one CSV or vector table."""

    suffix = table_path.suffix.lower()
    if suffix == ".csv":
        rows = _load_outlet_rows_from_csv(table_path)
    elif suffix in _VECTOR_TABLE_SUFFIXES:
        rows = _load_outlet_rows_from_vector(table_path)
    else:
        raise ValueError(
            "Unsupported mesh_catchment_batch outlets table format "
            f"'{table_path.suffix}'. Supported: .csv, .shp, .gpkg, .geojson, .json."
        )
    if not rows:
        raise ValueError(
            f"mesh_catchment_batch outlets table contains no outlet row: {table_path}"
        )

    selected_ids = set(selected_outlet_ids)
    records: list[MeshCatchmentOutletRecord] = []
    seen_outlet_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        record = _build_outlet_record(
            row=row,
            outlet_id_column=outlet_id_column,
            x_column=x_column,
            y_column=y_column,
            row_label=f"{table_path} row {index}",
        )
        if selection_mode == "selected" and record.outlet_id not in selected_ids:
            continue
        if record.outlet_id in seen_outlet_ids:
            raise ValueError(
                "mesh_catchment_batch outlets table contains duplicated outlet_id "
                f"'{record.outlet_id}'."
            )
        seen_outlet_ids.add(record.outlet_id)
        records.append(record)

    if selection_mode == "selected" and not records:
        raise ValueError(
            "mesh_catchment_batch.selected_outlet_ids did not match any outlet row."
        )
    return records


def validate_outlets_within_raster(
    *,
    records: Sequence[MeshCatchmentOutletRecord],
    raster_path: Path,
    label: str,
) -> None:
    """Check that all selected outlets lie within one raster extent."""

    if not raster_path.exists():
        raise FileNotFoundError(f"{label} not found: {raster_path}")

    with rasterio.open(raster_path) as src:
        bounds = src.bounds
        outside = [
            record
            for record in records
            if not _point_is_within_bounds(
                x=record.x_outlet,
                y=record.y_outlet,
                bounds=bounds,
            )
        ]

    if not outside:
        return

    sample = ", ".join(
        f"{record.outlet_id}({record.x_outlet:.3f},{record.y_outlet:.3f})"
        for record in outside[:3]
    )
    raise ValueError(
        f"{label} does not cover all selected batch outlets. "
        f"Raster bounds are {bounds}. First outside outlet(s): {sample}. "
        "Override the batch config with a DEM/reference raster that covers the full outlets table."
    )


def _load_outlet_rows_from_csv(table_path: Path) -> list[dict[str, Any]]:
    """Read outlet rows from one CSV file with a header row."""

    with table_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"mesh_catchment_batch CSV has no header row: {table_path}")
        return [dict(row) for row in reader]


def _load_outlet_rows_from_vector(table_path: Path) -> list[dict[str, Any]]:
    """Read outlet rows from one vector file and expose point XY columns."""

    import geopandas as gpd

    gdf = gpd.read_file(table_path)
    if gdf.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in gdf.iterrows():
        payload = {
            str(column): row[column] for column in gdf.columns if str(column) != "geometry"
        }
        geometry = getattr(row, "geometry", None)
        if geometry is not None and not geometry.is_empty:
            payload.setdefault("geometry_x", float(geometry.x))
            payload.setdefault("geometry_y", float(geometry.y))
        rows.append(payload)
    return rows


def _build_outlet_record(
    *,
    row: Mapping[str, Any],
    outlet_id_column: str,
    x_column: str,
    y_column: str,
    row_label: str,
) -> MeshCatchmentOutletRecord:
    """Validate one raw table row and convert it into one outlet record."""

    if outlet_id_column not in row:
        raise KeyError(f"Missing outlet id column '{outlet_id_column}' in {row_label}")
    outlet_id = _require_text(
        row.get(outlet_id_column),
        label=f"{row_label}.{outlet_id_column}",
    )
    try:
        raw_x = row.get(x_column, row.get("geometry_x"))
        raw_y = row.get(y_column, row.get("geometry_y"))
        if raw_x is None or raw_y is None:
            raise KeyError
        x_outlet = float(raw_x)
        y_outlet = float(raw_y)
    except KeyError as exc:
        raise KeyError(
            f"Missing outlet coordinates columns '{x_column}'/'{y_column}' in {row_label}"
        ) from exc
    except Exception as exc:
        raise ValueError(
            f"Invalid outlet coordinates in {row_label}: x={row.get(x_column)!r}, y={row.get(y_column)!r}"
        ) from exc
    return MeshCatchmentOutletRecord(
        outlet_id=outlet_id,
        outlet_id_safe=sanitize_batch_path_token(outlet_id),
        x_outlet=x_outlet,
        y_outlet=y_outlet,
    )


def _optional_text(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _require_text(raw_value: object, *, label: str) -> str:
    text = _optional_text(raw_value)
    if text is None:
        raise ValueError(f"{label} cannot be empty.")
    return text


def _point_is_within_bounds(*, x: float, y: float, bounds) -> bool:
    return (
        float(bounds.left) <= float(x) <= float(bounds.right)
        and float(bounds.bottom) <= float(y) <= float(bounds.top)
    )


__all__ = [
    "MeshCatchmentOutletRecord",
    "load_mesh_catchment_outlet_records",
    "sanitize_batch_path_token",
    "validate_outlets_within_raster",
]
