from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    load_zone_meshing_domain_geometry,
    validate_zone_meshing_domain_config_data,
)


def _reference_domain_geojson() -> Path:
    return (
        Path(__file__).resolve().parents[6]
        / "hydromodpy"
        / "solver"
        / "utils"
        / "mesh"
        / "gmsh_grid"
        / "cases"
        / "reference_2d_geology_conformal"
        / "domain_window.geojson"
    )


def test_validate_domain_bbox_contract() -> None:
    cfg = validate_zone_meshing_domain_config_data(
        {"kind": "bbox", "bbox": [0.0, 1.0, 10.0, 20.0]}
    )
    assert cfg == {"kind": "bbox", "bbox": [0.0, 1.0, 10.0, 20.0]}


def test_validate_domain_legacy_clip_bbox_rejected() -> None:
    with pytest.raises(ValueError, match="clip_bbox is no longer supported"):
        validate_zone_meshing_domain_config_data({"clip_bbox": [1.0, 2.0, 3.0, 4.0]})


def test_load_domain_geometry_legacy_clip_bbox_rejected() -> None:
    with pytest.raises(ValueError, match="clip_bbox is no longer supported"):
        load_zone_meshing_domain_geometry({"clip_bbox": [0.0, 0.0, 2.0, 2.0]})


def test_validate_domain_rejects_bbox_and_clip_bbox_together() -> None:
    with pytest.raises(ValueError, match="clip_bbox is no longer supported"):
        validate_zone_meshing_domain_config_data(
            {
                "kind": "bbox",
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "clip_bbox": [0.0, 0.0, 1.0, 1.0],
            }
        )


def test_validate_domain_vector_selected_id_requires_id_field() -> None:
    with pytest.raises(ValueError, match="id_field is required"):
        validate_zone_meshing_domain_config_data(
            {"kind": "vector", "path": "domain.geojson", "selected_id": "main"}
        )


def test_validate_domain_vector_rejects_selected_ids_plural() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_zone_meshing_domain_config_data(
            {
                "kind": "vector",
                "path": "domain.geojson",
                "id_field": "domain_id",
                "selected_ids": ["main"],
            }
        )


def test_load_domain_geometry_vector_single_selected_id() -> None:
    payload = load_zone_meshing_domain_geometry(
        {
            "kind": "vector",
            "path": str(_reference_domain_geojson()),
            "id_field": "domain_id",
            "selected_id": "main",
        }
    )
    assert payload["summary"]["domain_kind"] == "vector"
    assert payload["summary"]["domain_selected_id"] == "main"
    assert payload["summary"]["domain_selected_feature_count"] == 1
