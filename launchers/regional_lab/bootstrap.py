"""Bootstrap helpers to build one regional-lab site catalog from outlet tables."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping


def _normalize_text(value: object) -> str | None:
    """Return one stripped optional text value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_float(value: object) -> float | None:
    """Return one optional float value."""
    text = _normalize_text(value)
    if text is None:
        return None
    return float(text)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Load one CSV file into a list of stripped string mappings."""
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows: list[dict[str, str]] = []
        for row in reader:
            normalized: dict[str, str] = {}
            for key, value in row.items():
                key_text = str(key).strip()
                if key_text == "":
                    continue
                normalized[key_text] = "" if value is None else str(value).strip()
            rows.append(normalized)
    return rows


def _write_csv_rows(
    path: Path,
    *,
    fieldnames: list[str],
    rows: list[Mapping[str, Any]],
) -> None:
    """Write one canonical CSV payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = {name: row.get(name, "") for name in fieldnames}
            writer.writerow(payload)


def build_site_catalog_from_outlet_table(
    *,
    outlets_table_path: str | Path,
    output_path: str | Path,
    cluster_id: str,
    region_id: str,
    source_selection_id: str,
    cluster_label: str | None = None,
    cluster_family: str | None = None,
    cluster_scale: str | None = None,
    manifest_csv: str | Path | None = None,
    outlet_id_column: str = "outlet_id",
    x_column: str = "x_outlet",
    y_column: str = "y_outlet",
    area_column: str = "area_km2",
    site_id_template: str = "{cluster_id}_outlet_{outlet_id}",
    default_site_status: str = "inventory",
    default_maturity: str = "screening",
    default_tags: tuple[str, ...] = (),
    enabled: bool = True,
) -> dict[str, Any]:
    """Build one canonical regional-lab site catalog from outlet and manifest CSVs."""
    outlets_path = Path(outlets_table_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    manifest_path = None if manifest_csv is None else Path(manifest_csv).expanduser().resolve()

    if not outlets_path.is_file():
        raise FileNotFoundError(f"Outlets table not found: {outlets_path}")
    if manifest_path is not None and not manifest_path.is_file():
        raise FileNotFoundError(f"Mesh manifest CSV not found: {manifest_path}")

    outlet_rows = _read_csv_rows(outlets_path)
    if not outlet_rows:
        raise ValueError(f"Outlets table contains no row: {outlets_path}")

    manifest_by_outlet_id: dict[str, dict[str, str]] = {}
    if manifest_path is not None:
        for row in _read_csv_rows(manifest_path):
            manifest_outlet_id = _normalize_text(row.get("outlet_id"))
            if manifest_outlet_id is None:
                continue
            manifest_by_outlet_id[manifest_outlet_id] = row

    catalog_rows: list[dict[str, Any]] = []
    for outlet_row in outlet_rows:
        outlet_id = _normalize_text(outlet_row.get(outlet_id_column))
        if outlet_id is None:
            raise ValueError(
                "Outlets table row is missing the configured outlet identifier column "
                f"'{outlet_id_column}'"
            )
        manifest_row = manifest_by_outlet_id.get(outlet_id, {})
        manifest_status = _normalize_text(manifest_row.get("status"))
        tags = list(default_tags)
        if manifest_status is not None and manifest_status.lower() == "ok":
            tags.append("mesh_ready")
        site_id = site_id_template.format(cluster_id=cluster_id, outlet_id=outlet_id)
        mesh_output = _normalize_text(manifest_row.get("output_mesh"))
        mesh_bundle_dir = None
        if mesh_output is not None:
            mesh_bundle_dir = str(Path(mesh_output).expanduser().resolve().parent)

        catalog_rows.append(
            {
                "site_id": site_id,
                "site_label": f"{cluster_label or cluster_id} outlet {outlet_id}",
                "cluster_id": cluster_id,
                "cluster_label": cluster_label or cluster_id,
                "cluster_family": cluster_family or "",
                "cluster_scale": cluster_scale or "",
                "region_id": region_id,
                "source_selection_id": source_selection_id,
                "site_status": manifest_status or default_site_status,
                "maturity": default_maturity,
                "enabled": "true" if enabled else "false",
                "tags": ";".join(tags),
                "outlet_id": outlet_id,
                "x": "" if _normalize_float(outlet_row.get(x_column)) is None else _normalize_float(outlet_row.get(x_column)),
                "y": "" if _normalize_float(outlet_row.get(y_column)) is None else _normalize_float(outlet_row.get(y_column)),
                "area_km2": "" if _normalize_float(outlet_row.get(area_column)) is None else _normalize_float(outlet_row.get(area_column)),
                "mesh_manifest_status": manifest_status or "",
                "mesh_output_mesh": mesh_output or "",
                "mesh_summary_json": _normalize_text(manifest_row.get("output_summary_json")) or "",
                "mesh_bundle_dir": mesh_bundle_dir or "",
                "mesh_figure": _normalize_text(manifest_row.get("output_figure")) or "",
                "mesh_figure_regional": _normalize_text(manifest_row.get("output_figure_regional")) or "",
                "notes": "",
            }
        )

    fieldnames = [
        "site_id",
        "site_label",
        "cluster_id",
        "cluster_label",
        "cluster_family",
        "cluster_scale",
        "region_id",
        "source_selection_id",
        "site_status",
        "maturity",
        "enabled",
        "tags",
        "outlet_id",
        "x",
        "y",
        "area_km2",
        "mesh_manifest_status",
        "mesh_output_mesh",
        "mesh_summary_json",
        "mesh_bundle_dir",
        "mesh_figure",
        "mesh_figure_regional",
        "notes",
    ]
    _write_csv_rows(destination, fieldnames=fieldnames, rows=catalog_rows)
    return {
        "output_path": str(destination),
        "site_count": len(catalog_rows),
        "cluster_id": cluster_id,
        "region_id": region_id,
        "source_selection_id": source_selection_id,
        "manifest_merged": manifest_path is not None,
    }


__all__ = ("build_site_catalog_from_outlet_table",)
