from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.config.generate_toml import available_modules, generate_toml
from hydromodpy.spatial.mesh.config import (
    parse_mesh_catchment_batch_config_data,
    parse_mesh_catchment_config_data,
)


def test_parse_mesh_catchment_config_defaults_domain_and_rivers() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
        }
    )

    assert cfg.constraints_mode == "rivers_only"
    assert cfg.domain.kind == "geographic_box_buffer"
    assert cfg.geographic_outputs_mode == "keep"
    assert cfg.rivers.source == "domain_geographic"
    assert cfg.watershed_boundary.enabled is False
    assert cfg.figures_enabled is True
    assert cfg.export_exchange_bundle is True
    assert cfg.figure_dpi == 300
    assert cfg.figure_regional_dpi == 220
    assert cfg.zone_meshing.algorithm == "delaunay"


def test_parse_mesh_catchment_config_accepts_figures_disabled() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
            "figures_enabled": False,
        }
    )

    assert cfg.figures_enabled is False


def test_parse_mesh_catchment_config_accepts_exchange_bundle_disabled() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
            "export_exchange_bundle": False,
        }
    )

    assert cfg.export_exchange_bundle is False


def test_parse_mesh_catchment_config_accepts_custom_figure_dpi() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
            "figure_dpi": 360,
            "figure_regional_dpi": 180,
        }
    )

    assert cfg.figure_dpi == 360
    assert cfg.figure_regional_dpi == 180


@pytest.mark.parametrize(
    "removed_key, removed_payload",
    [
        ("interface_scope", {"kind": "geographic_watershed"}),
        ("refinement_scope", {"kind": "geographic_watershed"}),
    ],
)
def test_parse_mesh_catchment_config_rejects_removed_sections(
    removed_key: str,
    removed_payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match=rf"\[mesh_catchment\.{removed_key}\] is no longer supported"):
        parse_mesh_catchment_config_data(
            {
                "constraints_mode": "geology_only",
                "geology": {
                    "source": {
                        "path": "data/geology.tif",
                        "kind": "raster",
                    }
                },
                removed_key: removed_payload,
            }
        )


def test_parse_mesh_catchment_config_accepts_hydraulic_properties() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "geology_only",
            "geology": {
                "source": {
                    "path": "data/geology.tif",
                    "kind": "raster",
                }
            },
            "hydraulic_properties": {
                "conductivity": {
                    "values_source": "inline",
                    "unit": "m/day",
                    "values": {"granite": 12.0},
                }
            },
        }
    )

    assert cfg.hydraulic_properties is not None
    assert cfg.hydraulic_properties.conductivity is not None
    assert cfg.hydraulic_properties.conductivity.unit == "m/day"
    assert cfg.hydraulic_properties.conductivity.values["granite"] == 12.0


def test_parse_mesh_catchment_config_accepts_cleanup_mode() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
            "geographic_outputs_mode": "cleanup",
        }
    )

    assert cfg.geographic_outputs_mode == "cleanup"


def test_parse_mesh_catchment_config_accepts_flat_output_layout() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
            "output_layout": "flat",
        }
    )

    assert cfg.output_layout == "flat"


def test_parse_mesh_catchment_config_accepts_watershed_boundary_settings() -> None:
    cfg = parse_mesh_catchment_config_data(
        {
            "constraints_mode": "geology_only",
            "geology": {
                "source": {
                    "path": "data/geology.tif",
                    "kind": "raster",
                }
            },
            "watershed_boundary": {
                "enabled": True,
                "boundary_refinement_distance": 500.0,
                "smoothing": {
                    "enabled": True,
                    "distance": 50.0,
                    "river_buffer_distance": 100.0,
                    "outer_bias_distance": 10.0,
                },
                "outside_coarsening": {
                    "enabled": True,
                    "size_factor": 2.0,
                    "transition_distance": 500.0,
                    "grid_resolution": 250.0,
                },
                "geology_conformity": {
                    "mode": "buffered_watershed_envelope",
                    "buffer_distance": 400.0,
                },
            },
            "zone_meshing": {
                "refine_interfaces": True,
                "global_size": 250.0,
                "interface_size": 125.0,
                "interface_distance": 500.0,
            },
        }
    )

    assert cfg.watershed_boundary.enabled is True
    assert cfg.watershed_boundary.boundary_refinement_distance == 500.0
    assert cfg.watershed_boundary.smoothing.enabled is True
    assert cfg.watershed_boundary.smoothing.distance == 50.0
    assert cfg.watershed_boundary.smoothing.river_buffer_distance == 100.0
    assert cfg.watershed_boundary.smoothing.outer_bias_distance == 10.0
    assert cfg.watershed_boundary.outside_coarsening.enabled is True
    assert cfg.watershed_boundary.outside_coarsening.size_factor == 2.0
    assert cfg.watershed_boundary.outside_coarsening.transition_distance == 500.0
    assert cfg.watershed_boundary.outside_coarsening.grid_resolution == 250.0
    assert (
        cfg.watershed_boundary.geology_conformity.mode
        == "buffered_watershed_envelope"
    )
    assert cfg.watershed_boundary.geology_conformity.buffer_distance == 400.0


def test_parse_mesh_catchment_config_rejects_buffered_geology_conformity_without_geology() -> None:
    with pytest.raises(
        ValueError,
        match="watershed_boundary.geology_conformity requires the geology section",
    ):
        parse_mesh_catchment_config_data(
            {
                "constraints_mode": "rivers_only",
                "watershed_boundary": {
                    "geology_conformity": {
                        "mode": "buffered_watershed_envelope",
                    }
                },
            }
        )


def test_parse_mesh_catchment_config_rejects_unknown_cleanup_mode() -> None:
    with pytest.raises(ValueError, match="geographic_outputs_mode"):
        parse_mesh_catchment_config_data(
            {
                "constraints_mode": "rivers_only",
                "geographic_outputs_mode": "drop",
            }
        )


def test_parse_mesh_catchment_batch_selected_requires_ids() -> None:
    with pytest.raises(ValueError, match="selected_outlet_ids"):
        parse_mesh_catchment_batch_config_data(
            {
                "enabled": True,
                "outlets_table_path": "outlets.csv",
                "selection_mode": "selected",
            }
        )


def test_generate_toml_exposes_mesh_catchment_sections() -> None:
    modules = available_modules()

    assert "mesh_catchment" in modules
    assert "mesh_catchment_batch" in modules

    content = generate_toml(
        modules=["mesh_catchment", "mesh_catchment_batch"],
        profile="user",
    )

    assert "[mesh_catchment]" in content
    assert "[mesh_catchment_batch]" in content
    assert "Meshing compliance target" in content
    assert "Enable batch mode" in content
    assert "hydraulic_properties" in content


