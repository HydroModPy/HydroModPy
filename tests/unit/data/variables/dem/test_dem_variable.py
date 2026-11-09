from __future__ import annotations

from pathlib import Path

import pytest
import rasterio

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.data.provenance.sidecars import CacheIndex
from hydromodpy.data.variables.dem.config import (
    DemConfig,
    IgnGeoplateformeDemSource,
)
from hydromodpy.data.variables.dem.variable import DemVariable


def _write_tif(path: Path, *, nodata: float | None = -9999.0) -> Path:
    """A one-pixel Lambert-93 GeoTIFF, the shape a FileRecord can seal."""
    import numpy as np
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": 1,
        "width": 1,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 1.0, 25.0, 25.0),
        "nodata": nodata,
    }
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(np.zeros((1, 1), dtype="float32"), 1)
    return path


@pytest.mark.fast
def test_ign_geoplateforme_dem_explicit_departments_dispatch_to_dynamic_client(
    tmp_path, monkeypatch
):
    index = CacheIndex(tmp_path)
    data_dir = tmp_path / "dem"
    captured: dict[str, object] = {}

    def fake_fetch_ign_dem(
        *,
        output_dir,
        bbox,
        departments=None,
        dataset,
        resolution_m,
        file_format,
        crs,
        force_refresh,
        **_kw,
    ):
        captured.update(
            {
                "bbox": bbox,
                "departments": departments,
                "dataset": dataset,
                "resolution_m": resolution_m,
                "file_format": file_format,
                "crs": crs,
                "force_refresh": force_refresh,
            }
        )
        path = Path(output_dir) / "processed" / "dem_explicit.tif"
        return _write_tif(path)

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )
    config = DemConfig(
        sources=[
            IgnGeoplateformeDemSource(
                extent="study_area",
                departments=["22"],
                dataset="bd-alti",
                resolution_m=25.0,
            )
        ]
    )

    result = DemVariable(
        config=config,
        index=index,
        project_extent=(650000.0, 6400000.0, 1050000.0, 6650000.0),
        data_dir=data_dir,
    ).load()

    assert Path(result.fields[0].data).exists()
    assert captured["departments"] == ["22"]
    assert captured["dataset"] == "bd-alti"
    assert captured["resolution_m"] == 25.0


@pytest.mark.fast
def test_ign_geoplateforme_dem_regions_dispatch_to_dynamic_client(tmp_path, monkeypatch):
    index = CacheIndex(tmp_path)
    data_dir = tmp_path / "dem"
    captured: dict[str, object] = {}

    def fake_fetch_ign_dem(
        *,
        output_dir,
        bbox,
        departments=None,
        dataset,
        resolution_m,
        file_format,
        crs,
        force_refresh,
        **_kw,
    ):
        captured.update(
            {
                "output_dir": output_dir,
                "bbox": bbox,
                "departments": departments,
                "dataset": dataset,
                "resolution_m": resolution_m,
                "file_format": file_format,
                "crs": crs,
                "force_refresh": force_refresh,
            }
        )
        path = Path(output_dir) / "processed" / "dem_dynamic.tif"
        return _write_tif(path)

    monkeypatch.setattr(
        "hydromodpy.data.variables.dem.apis.ign_dem_fr.fetch_ign_dem",
        fake_fetch_ign_dem,
    )
    config = DemConfig(
        sources=[
            IgnGeoplateformeDemSource(
                extent="study_area",
                regions=["Auvergne-Rhone-Alpes"],
                dataset="bd-alti",
                resolution_m=25.0,
                file_format="ASC",
                crs="epsg:2154",
                force_refresh=True,
            )
        ]
    )

    result = DemVariable(
        config=config,
        index=index,
        project_extent=(650000.0, 6400000.0, 1050000.0, 6650000.0),
        data_dir=data_dir,
    ).load()

    assert Path(result.fields[0].data).exists()
    assert result.fields[0].source == "ign_geoplateforme_dem"
    assert captured["dataset"] == "bd-alti"
    assert captured["resolution_m"] == 25.0
    assert captured["file_format"] == "ASC"
    assert captured["crs"] == "epsg:2154"
    assert captured["force_refresh"] is True
    assert captured["departments"] == [
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
    (row,) = index.rows(variable="dem", source="ign_geoplateforme_dem")
    assert row.source_unit == "bd-alti:25m:ASC"
    assert row.bbox is not None
    assert row.crs == "EPSG:2154"
    metadata = row.fetch_metadata
    assert metadata is not None
    assert metadata["provider"] == "ign_geoplateforme"
    assert metadata["dataset"] == "bd-alti"
    assert metadata["resolution_m"] == 25.0
    assert metadata["departments"] == captured["departments"]
    # The row is written to disk: a new index reads it back from the sidecar.
    assert CacheIndex(tmp_path).rows(variable="dem") == [row]


@pytest.mark.fast
def test_a_dem_download_without_a_data_folder_is_refused(tmp_path, monkeypatch):
    """No data folder, no download: nothing reaches the cache of the user."""
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "user-cache"))
    config = DemConfig(sources=[IgnGeoplateformeDemSource(extent="study_area", departments=["22"])])

    variable = DemVariable(
        config=config,
        index=CacheIndex(None),
        project_extent=(650000.0, 6400000.0, 1050000.0, 6650000.0),
        data_dir=None,
    )
    with pytest.raises(ConfigError, match="no data folder"):
        variable.load()
    assert not (tmp_path / "user-cache").exists()
