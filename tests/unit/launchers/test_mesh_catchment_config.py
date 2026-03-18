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
    assert cfg["rivers"]["source"] == "domain_geographic"
    assert cfg["zone_meshing"]["algorithm"] == "delaunay"


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
    single_path = template_dir / "config_mesh_catchment_template.toml"
    batch_path = template_dir / "config_mesh_catchment_batch_template.toml"

    assert single_path.read_text(encoding="utf-8") == render_mesh_catchment_template(
        batch=False,
        profile="user",
    )
    assert batch_path.read_text(encoding="utf-8") == render_mesh_catchment_template(
        batch=True,
        profile="user",
    )
