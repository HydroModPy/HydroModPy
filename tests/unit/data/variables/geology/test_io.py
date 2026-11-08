"""One geology field is read from a config mapping or from a TOML section, in io.py."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.data.variables.geology.io import (
    geology_field_from_config,
    geology_field_from_toml,
)
from tests._helpers import field_cases as cases


def test_a_geology_field_is_built_from_one_config_mapping(tmp_path: Path) -> None:
    source = {"path": str(cases.geology_raster(tmp_path / "geology.tif")), "kind": "raster"}

    field = geology_field_from_config(
        {"id": "field_geology", "source": source, "cell_samples_per_axis": 8}
    )

    assert field.as_dict() == {
        "id": "field_geology",
        "source_kind": "raster",
        "shape": (4, 4),
        "zone_keys": ("1", "2"),
        "default_cell_samples_per_axis": 8,
    }


def test_a_geology_field_reads_its_toml_section(tmp_path: Path) -> None:
    path = cases.geology_raster(tmp_path / "geology.tif")
    toml = cases.write_text(
        tmp_path / "geology.toml",
        "[geology]\n"
        'id = "field_geology"\n'
        "cell_samples_per_axis = 6\n"
        f'source = {{ path = "{path}", kind = "raster" }}',
    )

    field = geology_field_from_toml(toml)

    assert field.as_dict() == {
        "id": "field_geology",
        "source_kind": "raster",
        "shape": (4, 4),
        "zone_keys": ("1", "2"),
        "default_cell_samples_per_axis": 6,
    }
