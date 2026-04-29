"""Geology projection helpers used by the catchment mesh bundle export.

These helpers resolve the geology source configuration, project the encoded
zones onto the planar mesh and produce the per-cell ``GeologyProjectionPayload``
consumed by the bundle orchestrator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.spatial._protocols import get_geology_data_source
from hydromodpy.spatial.field.geology.geology_field import GeologyField
from hydromodpy.spatial.mesh.gmsh_grid.bundle_export_contracts import (
    CatchmentBundleGeologyExportConfig,
    GeologyFractionRow,
    GeologyProjectionPayload,
)


def _build_fractions_by_cell(
    fraction_rows: tuple[GeologyFractionRow, ...],
) -> dict[int, list[tuple[str, float]]]:
    """Group geology-fraction rows by exported cell id."""
    out: dict[int, list[tuple[str, float]]] = {}
    for row in fraction_rows:
        cell_id = int(row.cell_id)
        zone_key = get_geology_data_source().normalize_zone_key(row.geology_key)
        fraction = float(row.fraction)
        if zone_key == "" or fraction <= 0.0:
            continue
        out.setdefault(cell_id, []).append((zone_key, fraction))
    return out


def _resolve_geology_config_paths(
    geology_cfg: CatchmentBundleGeologyExportConfig,
    *,
    config_path: str | Path | None,
) -> dict[str, Any]:
    """Resolve geology paths relative to the calling config when needed.

    The export layer keeps a small typed contract, then converts it to the
    legacy loader mapping only at the edge where the geology loader still
    expects dictionary payloads.
    """

    cfg: dict[str, Any] = {
        "id": geology_cfg.field_id or "field_geology",
        "source": {
            "path": geology_cfg.source.path,
            "kind": geology_cfg.source.kind,
        },
        "cell_samples_per_axis": int(geology_cfg.cell_samples_per_axis),
    }
    source_cfg = dict(cfg["source"])
    if geology_cfg.source.code_field is not None:
        source_cfg["code_field"] = geology_cfg.source.code_field
    if geology_cfg.source.reference_raster_path is not None:
        source_cfg["reference_raster_path"] = geology_cfg.source.reference_raster_path
    source_cfg["path"] = get_geology_data_source().resolve_data_path(
        str(source_cfg["path"]),
        config_path=config_path,
    )
    reference_raster_path = source_cfg.get("reference_raster_path")
    if reference_raster_path is not None:
        source_cfg["reference_raster_path"] = get_geology_data_source().resolve_data_path(
            str(reference_raster_path),
            config_path=config_path,
        )
    cfg["source"] = source_cfg

    clip_polygon_path = cfg.get("clip_polygon_path")
    if clip_polygon_path:
        cfg["clip_polygon_path"] = get_geology_data_source().resolve_data_path(
            str(clip_polygon_path),
            config_path=config_path,
        )

    landsea_cfg = dict(cfg.get("landsea", {}))
    landsea_path = landsea_cfg.get("path")
    if landsea_path:
        landsea_cfg["path"] = get_geology_data_source().resolve_data_path(
            str(landsea_path),
            config_path=config_path,
        )
        cfg["landsea"] = landsea_cfg
    return cfg


def _compute_geology_payload(
    *,
    mesh,
    raster_support,
    geology_cfg: CatchmentBundleGeologyExportConfig | None,
    config_path: str | Path | None,
) -> GeologyProjectionPayload:
    """Project geology information from the source dataset onto the planar mesh."""
    if geology_cfg is None:
        return GeologyProjectionPayload(
            available=False,
            cell_zone_keys=tuple("" for _ in range(mesh.n_cells)),
            cell_zone_codes=tuple(0 for _ in range(mesh.n_cells)),
        )

    support = raster_support
    if support is None:
        raise ValueError("surface_topo.support is required to project geology on mesh")

    resolved_cfg = _resolve_geology_config_paths(geology_cfg, config_path=config_path)
    loaded = get_geology_data_source().load_encoded_grid_on_raster_support(
        resolved_cfg,
        raster_support=support,
    )
    cell_samples_per_axis = int(resolved_cfg.get("cell_samples_per_axis", 8))
    field = GeologyField(
        identifier=str(resolved_cfg["id"]),
        encoded_codes=loaded["encoded_codes"],
        encoded_to_zone=loaded["encoded_to_zone"],
        transform=loaded["transform"],
        crs=loaded["crs"],
        source_kind=str(loaded["source_kind"]),
        default_cell_samples_per_axis=cell_samples_per_axis,
    )
    discretization = field.on_mesh(
        mesh,
        cell_samples_per_axis=cell_samples_per_axis,
    )
    zone_keys, fractions_by_zone = discretization.weighted_components()
    zone_keys = tuple(str(zone_key) for zone_key in zone_keys)
    zone_to_code = {
        str(zone_key): int(encoded_code)
        for encoded_code, zone_key in loaded["encoded_to_zone"].items()
    }

    fractions_flat = {
        zone_key: np.asarray(fractions_by_zone[zone_key], dtype=float).reshape(-1)
        for zone_key in zone_keys
    }

    cell_zone_keys: list[str] = []
    cell_zone_codes: list[int] = []
    fraction_rows: list[GeologyFractionRow] = []
    for cell_idx in range(int(mesh.n_cells)):
        dominant_key = ""
        dominant_fraction = -1.0
        for zone_key in zone_keys:
            fraction = float(fractions_flat[zone_key][cell_idx])
            if fraction > 0.0:
                fraction_rows.append(
                    GeologyFractionRow(
                        cell_id=int(cell_idx),
                        geology_key=str(zone_key),
                        fraction=float(fraction),
                    )
                )
            if fraction > dominant_fraction + 1.0e-12 or (
                abs(fraction - dominant_fraction) <= 1.0e-12
                and dominant_key != ""
                and str(zone_key) < dominant_key
            ):
                dominant_key = str(zone_key) if fraction > 0.0 else dominant_key
                dominant_fraction = float(fraction)
        if dominant_fraction <= 0.0:
            cell_zone_keys.append("")
            cell_zone_codes.append(0)
            continue
        cell_zone_keys.append(dominant_key)
        cell_zone_codes.append(int(zone_to_code.get(dominant_key, 0)))

    return GeologyProjectionPayload(
        available=True,
        field_id=str(field.identifier),
        zone_keys=zone_keys,
        cell_zone_keys=tuple(cell_zone_keys),
        cell_zone_codes=tuple(cell_zone_codes),
        fraction_rows=tuple(fraction_rows),
        source_kind=str(loaded["source_kind"]),
        cell_samples_per_axis=int(cell_samples_per_axis),
    )
