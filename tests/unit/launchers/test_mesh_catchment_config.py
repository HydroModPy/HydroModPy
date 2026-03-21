from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config.generate_toml import available_modules, generate_toml
from launchers.mesh_catchment.config import (
    validate_mesh_catchment_batch_config_data,
    validate_mesh_catchment_config_data,
)
from launchers.mesh_catchment.templates import render_mesh_catchment_template


def test_validate_mesh_catchment_config_defaults_domain_and_rivers() -> None:
    cfg = validate_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
        }
    )

    assert cfg["constraints_mode"] == "rivers_only"
    assert cfg["domain"]["kind"] == "geographic_box_buffer"
    assert cfg["geographic_outputs_mode"] == "keep"
    assert cfg["rivers"]["source"] == "domain_geographic"
    assert cfg["zone_meshing"]["algorithm"] == "delaunay"


def test_validate_mesh_catchment_config_accepts_watershed_boundary() -> None:
    cfg = validate_mesh_catchment_config_data(
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
                "participates_in_refinement": False,
                "smoothing": {
                    "enabled": True,
                    "simplify_tolerance": 25.0,
                    "heal_tolerance": 10.0,
                },
            },
        }
    )

    assert cfg["watershed_boundary"]["enabled"] is True
    assert cfg["watershed_boundary"]["source"] == "domain_geographic"
    assert cfg["watershed_boundary"]["smoothing"]["simplify_tolerance"] == 25.0


def test_validate_mesh_catchment_config_rejects_redundant_watershed_boundary() -> None:
    with pytest.raises(ValueError, match="watershed_boundary is redundant"):
        validate_mesh_catchment_config_data(
            {
                "constraints_mode": "geology_only",
                "geology": {
                    "source": {
                        "path": "data/geology.tif",
                        "kind": "raster",
                    }
                },
                "domain": {"kind": "geographic_watershed"},
                "watershed_boundary": {"enabled": True},
            }
        )


def test_validate_mesh_catchment_config_accepts_hydraulic_properties() -> None:
    cfg = validate_mesh_catchment_config_data(
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

    assert cfg["hydraulic_properties"]["conductivity"]["unit"] == "m/day"
    assert cfg["hydraulic_properties"]["conductivity"]["values"]["granite"] == 12.0


def test_validate_mesh_catchment_config_accepts_cleanup_mode() -> None:
    cfg = validate_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
            "geographic_outputs_mode": "cleanup",
        }
    )

    assert cfg["geographic_outputs_mode"] == "cleanup"


def test_validate_mesh_catchment_config_accepts_flat_output_layout() -> None:
    cfg = validate_mesh_catchment_config_data(
        {
            "constraints_mode": "rivers_only",
            "output_layout": "flat",
        }
    )

    assert cfg["output_layout"] == "flat"


def test_validate_mesh_catchment_config_rejects_unknown_cleanup_mode() -> None:
    with pytest.raises(ValueError, match="geographic_outputs_mode"):
        validate_mesh_catchment_config_data(
            {
                "constraints_mode": "rivers_only",
                "geographic_outputs_mode": "drop",
            }
        )


def test_validate_mesh_catchment_batch_selected_requires_ids() -> None:
    with pytest.raises(ValueError, match="selected_outlet_ids"):
        validate_mesh_catchment_batch_config_data(
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


def test_versioned_templates_match_renderer() -> None:
    template_dir = Path("launchers/mesh_catchment")
    single_path = template_dir / "config_template.toml"
    batch_path = template_dir / "config_batch_template.toml"

    assert single_path.read_text(encoding="utf-8") == render_mesh_catchment_template(
        batch=False,
        profile="user",
    )
    assert batch_path.read_text(encoding="utf-8") == render_mesh_catchment_template(
        batch=True,
        profile="user",
    )


def test_template_renderer_mentions_output_layout() -> None:
    content = render_mesh_catchment_template(batch=False, profile="user")

    assert 'output_layout = "standard"' in content
    assert "write final mesh artifacts directly under `workspace.project_root`" in content
    assert "[mesh_catchment.watershed_boundary]" in content
