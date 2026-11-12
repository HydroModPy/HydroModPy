"""The DEM variable of a project: IGN requests dispatched to the assembler, cached by row.

Boxes are Lambert-93 m and the DEM pixels are 25 m. The assembler is replaced by a
function that writes a one-pixel GeoTIFF.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.variables.dem.apis import ign_dem_fr
from hydromodpy.data.variables.dem.config import DemConfig, IgnGeoplateformeDemSource
from hydromodpy.data.variables.dem.variable import DemVariable

PROJECT_EXTENT = (650000.0, 6400000.0, 1050000.0, 6650000.0)
# Departments of Auvergne-Rhone-Alpes.
AURA_DEPARTMENTS = [
    "001",
    "003",
    "007",
    "015",
    "026",
    "038",
    "042",
    "043",
    "063",
    "069",
    "073",
    "074",
]


def write_tif(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 1.0, 25.0, 25.0),
        "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.zeros((1, 1), dtype="float32"), 1)
    return path


def load_dem(tmp_path, monkeypatch, source):
    """Load the DEM of one source. Return the result, the index and what the assembler was asked."""
    index = CacheIndex(tmp_path)
    asked = {}

    def fake_fetch_ign_dem(*, output_dir, bbox, **kwargs):
        asked.update(output_dir=output_dir, bbox=bbox, **kwargs)
        return write_tif(Path(output_dir) / "processed" / "dem_fake.tif")

    monkeypatch.setattr(ign_dem_fr, "fetch_ign_dem", fake_fetch_ign_dem)
    variable = DemVariable(
        config=DemConfig(sources=[source]),
        index=index,
        project_extent=PROJECT_EXTENT,
        data_dir=tmp_path / "dem",
    )
    return variable.load(), index, asked


def test_explicit_departments_reach_the_assembler(tmp_path, monkeypatch):
    source = IgnGeoplateformeDemSource(
        extent="study_area", departments=["22"], dataset="bd-alti", resolution_m=25.0
    )

    result, _, asked = load_dem(tmp_path, monkeypatch, source)

    assert Path(result.fields[0].data).exists()
    assert asked["departments"] == ["22"]
    assert asked["dataset"] == "bd-alti"
    assert asked["resolution_m"] == 25.0


def test_regions_become_departments_and_a_row(tmp_path, monkeypatch):
    source = IgnGeoplateformeDemSource(
        extent="study_area",
        regions=["Auvergne-Rhone-Alpes"],
        dataset="bd-alti",
        resolution_m=25.0,
        file_format="ASC",
        crs="epsg:2154",
        force_refresh=True,
    )

    result, index, asked = load_dem(tmp_path, monkeypatch, source)

    assert Path(result.fields[0].data).exists()
    assert result.fields[0].source == "ign_geoplateforme_dem"
    assert asked["dataset"] == "bd-alti"
    assert asked["resolution_m"] == 25.0
    assert asked["file_format"] == "ASC"
    assert asked["crs"] == "epsg:2154"
    assert asked["force_refresh"] is True
    assert asked["departments"] == AURA_DEPARTMENTS
    (row,) = index.rows(variable="dem", source="ign_geoplateforme_dem")
    assert row.source_unit == "bd-alti:25m:ASC"
    assert row.bbox is not None
    assert row.crs == "EPSG:2154"
    metadata = row.fetch_metadata
    assert metadata is not None
    assert metadata["provider"] == "ign_geoplateforme"
    assert metadata["dataset"] == "bd-alti"
    assert metadata["resolution_m"] == 25.0
    assert metadata["departments"] == asked["departments"]
    # The row is on disk: a new index reads it back from the sidecar.
    assert CacheIndex(tmp_path).rows(variable="dem") == [row]


def test_a_download_without_a_data_folder_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "user-cache"))
    source = IgnGeoplateformeDemSource(extent="study_area", departments=["22"])
    variable = DemVariable(
        config=DemConfig(sources=[source]),
        index=CacheIndex(None),
        project_extent=PROJECT_EXTENT,
        data_dir=None,
    )

    with pytest.raises(ConfigError, match="no data folder"):
        variable.load()
    assert not (tmp_path / "user-cache").exists()
