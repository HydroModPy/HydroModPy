"""Small runner-only helpers for the reference 2D zone-conformal case."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import geopandas as gpd


def _parse_args(
    argv=None,
    *,
    default_config_file: str,
    default_section: str,
):
    parser = argparse.ArgumentParser(
        description="Generate one conformal 2D Gmsh mesh from configurable zone and river constraints."
    )
    parser.add_argument("--config-file", default=default_config_file)
    parser.add_argument("--section", default=default_section)
    parser.add_argument("--output-mesh", default=None)
    parser.add_argument("--output-summary-json", default=None)
    parser.add_argument("--output-figure", default=None)
    parser.add_argument("--output-figure-regional", default=None)
    parser.add_argument("--show-plot", action="store_true")
    return parser.parse_args(argv)


def _resolve_config_path(raw_config: str | Path, *, script_dir: Path) -> Path:
    candidate = Path(raw_config).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    script_candidate = (script_dir / candidate).resolve()
    if script_candidate.exists():
        return script_candidate
    raise FileNotFoundError(f"Config TOML not found: '{raw_config}'")


def _resolve_optional_output_path(
    config_toml: Path,
    config_value: Any,
    override_value: str | None,
) -> Path | None:
    raw = override_value if override_value is not None else config_value
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (config_toml.parent / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _build_partition_gdf(partition, *, crs) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "face_id": [int(face.face_id) for face in partition.faces],
            "zone_key": [str(face.zone_key) for face in partition.faces],
            "face_area": [float(face.area) for face in partition.faces],
        },
        geometry=[face.polygon for face in partition.faces],
        crs=crs,
    )


__all__ = [
    "_build_partition_gdf",
    "_parse_args",
    "_resolve_config_path",
    "_resolve_optional_output_path",
]
