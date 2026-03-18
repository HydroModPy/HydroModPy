"""Unit non-regression test for geology property demo (Brittany subset)."""

from __future__ import annotations

import json
from pathlib import Path
import textwrap

import numpy as np

from hydromodpy.data_managers.variables.geology.cases import run_geology_property_case as demo
from hydromodpy.field.geology.geology_mesh import GeologyStructuredMesh


GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_FILE = GOLDEN_DIR / "geology_property_demo_brittany_signature.json"


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hydromodpy").is_dir():
            return parent
    raise RuntimeError("Cannot locate repository root from test path")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _write_demo_tomls(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = _repo_root()
    subset_dir = repo_root / "examples" / "data" / "geology"
    dem_path = repo_root / "examples" / "data" / "dem" / "regional_dem_canut.tif"

    if not (subset_dir / "GEO1M_brittany.shp").exists():
        raise FileNotFoundError("Missing Brittany geology subset shapefile for test")
    if not (subset_dir / "geology_K_dummy_demo.csv").exists():
        raise FileNotFoundError("Missing Brittany geology property CSV for test")
    if not dem_path.exists():
        raise FileNotFoundError("Missing DEM raster required by vector geology schema")

    geology_config_path = tmp_path / "geology_config_test.toml"
    field_param_path = tmp_path / "field_param_test.toml"

    geology_config_path.write_text(
        textwrap.dedent(
            f"""
            [geology]
            id = "field_geology"
            cell_samples_per_axis = 6

            [geology.source]
            path = "{(subset_dir / "GEO1M_brittany.shp").as_posix()}"
            kind = "vector"
            code_field = "CODE_LEG"
            reference_raster_path = "{dem_path.as_posix()}"
            all_touched = false

            [geology.landsea]
            enabled = false
            sea_value = 0
            override_code = "1"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    field_param_path.write_text(
        textwrap.dedent(
            f"""
            [field]
            id = "K"
            kind = "heterogeneous"

            [field_heterogeneous]
            values_source = "csv"
            values_csv_file = "{(subset_dir / "geology_K_dummy_demo.csv").as_posix()}"
            csv_key_column = "zone_key"
            csv_value_column = "K_value"
            field_spatial_id = "field_geology"

            [field_vertical_profile]
            mode = "none"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    return geology_config_path, field_param_path


def _compute_brittany_signature(tmp_path: Path) -> dict:
    geology_config_path, field_param_path = _write_demo_tomls(tmp_path)
    output_figure = tmp_path / "geology_property_demo.png"

    args = demo._parse_args(
        [
            "--geology-config-file",
            str(geology_config_path),
            "--field-param-config-file",
            str(field_param_path),
            "--global-map",
            "--target-n-cells",
            "400",
            "--cell-samples-per-axis",
            "6",
            "--output-file",
            str(output_figure),
            "--no-show-plot",
        ]
    )

    loaded, gdf, _window_polygon, sea_info = demo._load_display_geology(args, geology_config_path)
    field_param = demo._load_and_validate_field_param(
        args,
        field_param_path,
        expected_field_id=str(loaded["field_id"]),
    )
    geology_field = demo._build_local_geology_field(
        gdf,
        identifier=str(loaded["field_id"]),
        target_n_cells=int(args.target_n_cells),
    )
    mesh = GeologyStructuredMesh.from_bounds(gdf.total_bounds, target_n_cells=int(args.target_n_cells))
    discretized = geology_field.on_mesh(
        mesh,
        cell_samples_per_axis=max(2, int(args.cell_samples_per_axis)),
    )
    values_mesh = field_param.to_mesh_field(discretized)
    values = np.asarray(values_mesh.cell_values, dtype=float).reshape(-1)

    zone_counts = gdf["zone_key"].astype(str).value_counts()
    mesh_shape = [int(v) for v in mesh.shape]

    return {
        "field_id": str(loaded["field_id"]),
        "field_param_id": str(field_param.identifier),
        "n_polygons": int(len(gdf)),
        "n_unique_zones": int(zone_counts.index.size),
        "zone_keys_sorted": sorted([str(v) for v in zone_counts.index.tolist()]),
        "n_mesh_cells": int(mesh.n_cells),
        "mesh_shape": mesh_shape,
        "property_min": round(float(np.nanmin(values)), 12),
        "property_max": round(float(np.nanmax(values)), 12),
        "property_mean": round(float(np.nanmean(values)), 12),
        "property_sum": round(float(np.nansum(values)), 12),
        "sea_info": {
            "enabled": bool(sea_info.get("enabled")),
            "sea_zone_key": str(sea_info.get("sea_zone_key")),
            "sea_value": str(sea_info.get("sea_value")),
            "sea_field": str(sea_info.get("sea_field")),
            "n_sea_polygons": int(sea_info.get("n_sea_polygons", 0)),
            "n_reassigned_polygons": int(sea_info.get("n_reassigned_polygons", 0)),
        },
    }


def test_geology_property_demo_brittany_non_regression(tmp_path: Path, update_goldens: bool):
    """Check geology->property mapping stays stable on a small Brittany subset."""
    signature = _compute_brittany_signature(tmp_path)
    assert signature["n_polygons"] > 0
    assert signature["n_unique_zones"] > 0
    assert signature["n_mesh_cells"] > 0

    if update_goldens:
        _write_json(GOLDEN_FILE, signature)
        return

    if not GOLDEN_FILE.exists():
        raise AssertionError(
            f"Missing golden reference file: {GOLDEN_FILE}. "
            "Run tests with --update-goldens to generate it."
        )

    expected = _load_json(GOLDEN_FILE)
    assert signature == expected

