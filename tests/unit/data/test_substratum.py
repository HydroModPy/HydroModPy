"""Substratum (aquifer-bottom raster) config and manager.

Mirrors the lake-bathymetry tests: ``substratum`` is another custom-only
raster variable built on ``RasterFileManager``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from hydromodpy.data.contracts import FieldRecord
from hydromodpy.data.loading.config_schema import DataManagersConfig
from hydromodpy.data.variables.substratum.config import CustomSubstratumSource, SubstratumConfig
from hydromodpy.data.variables.substratum.manager import SubstratumManager


def _write_geotiff(path: Path, *, crs: str | None = "EPSG:2154", value: float = 42.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.full((3, 4), value, dtype="float32")
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(0.0, 100.0, 25.0, 25.0),
    ) as dst:
        dst.write(data, 1)
    return path


def test_custom_source_without_path_is_refused() -> None:
    with pytest.raises(ValidationError):
        CustomSubstratumSource.model_validate({"source": "custom"})


def test_config_refuses_two_sources(tmp_path: Path) -> None:
    a = _write_geotiff(tmp_path / "a.tif")
    b = _write_geotiff(tmp_path / "b.tif")
    with pytest.raises(ValidationError):
        SubstratumConfig.model_validate(
            {
                "sources": [
                    {"source": "custom", "path": str(a)},
                    {"source": "custom", "path": str(b)},
                ]
            }
        )


def test_manager_reads_a_tiny_geotiff(tmp_path: Path) -> None:
    src = _write_geotiff(tmp_path / "substratum.tif")
    config = SubstratumConfig.from_raster(src)
    manager = SubstratumManager(config=config, catalog=None, data_dir=tmp_path)

    result = manager.load()

    assert len(result.fields) == 1
    record = result.fields[0]
    assert isinstance(record, FieldRecord)
    assert record.variable == "substratum"
    assert record.unit == "m"
    assert record.crs.upper().endswith("2154")


def test_manager_falls_back_on_default_crs_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    src = _write_geotiff(tmp_path / "no_crs.tif", crs=None)
    config = SubstratumConfig.from_raster(src)
    manager = SubstratumManager(config=config, catalog=None, data_dir=tmp_path)

    with caplog.at_level(logging.WARNING):
        result = manager.load()

    record = result.fields[0]
    assert record.crs == "EPSG:2154"
    assert any("substratum" in message and "default_crs" in message for message in caplog.messages)


def test_from_toml_section_builds_substratum_even_when_not_in_types(tmp_path: Path) -> None:
    src = _write_geotiff(tmp_path / "bottom.tif")
    section = {
        "types": [],
        "substratum": {"sources": [{"source": "custom", "path": str(src)}]},
    }

    cfg = DataManagersConfig.from_toml_section(section, base_dir=tmp_path)

    assert isinstance(cfg.substratum, SubstratumConfig)
    assert cfg.substratum.sources[0].path == src


def test_a_bare_filename_resolves_under_the_workspace_substratum_folder(tmp_path: Path) -> None:
    workspace_data_dir = tmp_path / "data"
    substratum_dir = workspace_data_dir / "substratum"
    substratum_dir.mkdir(parents=True)
    src = _write_geotiff(substratum_dir / "substratum_custom_bottom.tif")

    section = {
        "types": ["substratum"],
        "substratum": {"sources": [{"source": "custom", "path": src.name}]},
    }

    cfg = DataManagersConfig.from_toml_section(
        section, base_dir=tmp_path, workspace_data_dir=workspace_data_dir
    )

    assert Path(cfg.substratum.sources[0].path) == src
