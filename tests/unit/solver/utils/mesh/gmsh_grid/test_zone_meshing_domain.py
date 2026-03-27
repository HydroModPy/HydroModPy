from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    ZoneMeshingDomainConfig,
    ZoneMeshingDomainPayload,
    ZoneMeshingSettings,
    load_zone_meshing_domain_payload,
    parse_zone_meshing_domain_config,
    parse_zone_meshing_settings,
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


def test_parse_domain_bbox_contract() -> None:
    cfg = parse_zone_meshing_domain_config(
        {"kind": "bbox", "bbox": [0.0, 1.0, 10.0, 20.0]}
    )
    assert cfg.to_mapping() == {"kind": "bbox", "bbox": [0.0, 1.0, 10.0, 20.0]}


def test_zone_meshing_domain_config_builds_typed_contract() -> None:
    cfg = ZoneMeshingDomainConfig.from_mapping(
        {"kind": "bbox", "bbox": [0.0, 1.0, 10.0, 20.0]}
    )

    assert cfg.kind == "bbox"
    assert cfg.bbox == (0.0, 1.0, 10.0, 20.0)
    assert cfg.to_mapping() == {"kind": "bbox", "bbox": [0.0, 1.0, 10.0, 20.0]}


def test_parse_zone_meshing_domain_config_returns_typed_contract() -> None:
    cfg = parse_zone_meshing_domain_config(
        {"kind": "vector", "path": "domain.geojson", "id_field": "domain_id"}
    )

    assert isinstance(cfg, ZoneMeshingDomainConfig)
    assert cfg.kind == "vector"
    assert cfg.path == "domain.geojson"
    assert cfg.id_field == "domain_id"


def test_parse_zone_meshing_settings_returns_typed_contract() -> None:
    settings = parse_zone_meshing_settings(
        {
            "global_size": 250.0,
            "refine_interfaces": True,
            "min_size": 25.0,
        }
    )

    assert isinstance(settings, ZoneMeshingSettings)
    assert settings.global_size == pytest.approx(250.0)
    assert settings.refine_interfaces is True
    assert settings.interface_size == pytest.approx(25.0)
    assert settings.interface_distance == pytest.approx(750.0)


def test_validate_domain_rejects_unknown_domain_shape_without_explicit_source() -> None:
    with pytest.raises(ValueError, match="requires one explicit geometry source"):
        parse_zone_meshing_domain_config({"clip_bbox": [1.0, 2.0, 3.0, 4.0]})


def test_load_domain_payload_rejects_unknown_domain_shape_without_explicit_source() -> None:
    with pytest.raises(ValueError, match="requires one explicit geometry source"):
        load_zone_meshing_domain_payload(
            parse_zone_meshing_domain_config({"clip_bbox": [0.0, 0.0, 2.0, 2.0]})
        )


def test_validate_domain_rejects_unknown_extra_fields_on_bbox_contract() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        parse_zone_meshing_domain_config(
            {
                "kind": "bbox",
                "bbox": [0.0, 0.0, 1.0, 1.0],
                "clip_bbox": [0.0, 0.0, 1.0, 1.0],
            }
        )


def test_validate_domain_vector_selected_id_requires_id_field() -> None:
    with pytest.raises(ValueError, match="id_field is required"):
        parse_zone_meshing_domain_config(
            {"kind": "vector", "path": "domain.geojson", "selected_id": "main"}
        )


def test_validate_domain_vector_rejects_selected_ids_plural() -> None:
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        parse_zone_meshing_domain_config(
            {
                "kind": "vector",
                "path": "domain.geojson",
                "id_field": "domain_id",
                "selected_ids": ["main"],
            }
        )


def test_load_domain_geometry_vector_single_selected_id() -> None:
    payload = load_zone_meshing_domain_payload(
        parse_zone_meshing_domain_config(
            {
            "kind": "vector",
            "path": str(_reference_domain_geojson()),
            "id_field": "domain_id",
            "selected_id": "main",
            }
        )
    )
    assert payload.summary["domain_kind"] == "vector"
    assert payload.summary["domain_selected_id"] == "main"
    assert payload.summary["domain_selected_feature_count"] == 1


def test_load_domain_payload_returns_typed_contract() -> None:
    payload = load_zone_meshing_domain_payload(
        ZoneMeshingDomainConfig(
            kind="vector",
            path=str(_reference_domain_geojson()),
            id_field="domain_id",
            selected_id="main",
        ),
    )

    assert isinstance(payload, ZoneMeshingDomainPayload)
    assert payload.summary["domain_kind"] == "vector"
    assert payload.summary["domain_selected_id"] == "main"
    assert payload.to_mapping()["summary"]["domain_selected_feature_count"] == 1
