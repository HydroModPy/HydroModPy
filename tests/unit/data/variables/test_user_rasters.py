"""User raster variables built on one file: substratum (m) and soil capacity (mm).

Both read a GeoTIFF the user supplies. The raster must declare its CRS, or the
config writes ``default_crs``. A bare file name is refused.
"""

from __future__ import annotations

import typing
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.paths import former_bare_name_location
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.loading.config_schema import DataConfig
from hydromodpy.data.variables.user_rasters import (
    FileSoilCapacitySource,
    SoilCapacityVariable,
    SubstratumConfig,
    SubstratumVariable,
)


def write_geotiff(path: Path, *, crs: str | None = "EPSG:2154", value: float = 42.0) -> Path:
    """A 3 x 4 raster of 25 m cells holding one value."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.full((3, 4), value, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=3,
        width=4,
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    return path


def test_a_raster_without_a_crs_is_refused_unless_default_crs_is_written(tmp_path):
    src = write_geotiff(tmp_path / "no_crs.tif", crs=None)
    refused = SubstratumVariable(
        config=SubstratumConfig.from_raster(src), index=None, data_dir=tmp_path
    )
    with pytest.raises(Exception, match="declares no CRS"):
        refused.load()

    written = SubstratumConfig.model_validate(
        {"sources": [{"source": "file", "path": str(src), "default_crs": "EPSG:4326"}]}
    )
    record = SubstratumVariable(config=written, index=None, data_dir=tmp_path).load().fields[0]
    assert record.crs == "EPSG:4326"


def test_a_bare_filename_is_refused_and_names_where_the_file_used_to_live(tmp_path):
    workspace_data_dir = tmp_path / "data"
    substratum_dir = workspace_data_dir / "substratum"
    substratum_dir.mkdir(parents=True)
    src = write_geotiff(substratum_dir / "substratum_custom_bottom.tif")
    section = {
        "types": ["substratum"],
        "substratum": {"sources": [{"source": "file", "path": src.name}]},
    }

    with pytest.raises(ConfigError, match="is a bare name"):
        DataConfig.from_toml_section(
            section, base_dir=tmp_path, workspace_data_dir=workspace_data_dir
        )
    assert former_bare_name_location(src.name, workspace_data_dir, role="substratum") is not None


def test_the_soil_capacity_path_carries_its_role():
    metadata = FileSoilCapacitySource.model_fields["path"].metadata

    roles = [meta.role for meta in metadata if isinstance(meta, InputFile)]

    assert roles[-1] == "soil_capacity"


def test_the_soil_capacity_unit_is_millimetres():
    assert SoilCapacityVariable.INTERNAL_UNIT == "mm"


def test_the_soil_capacity_never_applies_the_simulation_window():
    assert VARIABLE_SPECS["soil_capacity"].apply_simulation_window is False


def test_the_soil_capacity_source_only_accepts_file():
    annotation = FileSoilCapacitySource.model_fields["source"].annotation

    assert typing.get_args(annotation) == ("file",)
