"""Where hydrography gets its extent, now that no object carries it.

The manager used to read a ``geographic`` object for three things at once --
the project CRS, the polygon it clips to and the grid it rasterises onto. Two
of them are a mask file and one is a constructor argument, and these are the
tests that say so. The loader-side half matters as much as the manager-side
one: ``_apply_default_masks`` only ever looked at ``cfg.sources``, and
hydrography declares its mask on the **section**, so without the section-level
fill a project run would reach the manager with no extent at all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon

from hydromodpy.data.loading.loader import DataManagersRuntimeLoader
from hydromodpy.data.variables.hydrography.config import HydrographyConfig
from hydromodpy.data.variables.hydrography.manager import HydrographyManager

from ._test_hydrography_full_builders import WhiteboxStubBackend, _fake_inputs


def _watershed_wgs84(path: Path) -> Path:
    """A mask over Rennes, in degrees, written where the caller asks."""
    gpd.GeoDataFrame(
        geometry=[Polygon([(-1.8, 48.0), (-1.5, 48.0), (-1.5, 48.3), (-1.8, 48.3)])],
        crs="EPSG:4326",
    ).to_file(path)
    return path


@pytest.mark.fast
def test_the_manager_refuses_a_geographic_object():
    """The parameter is gone, not ignored."""
    with pytest.raises(TypeError, match="geographic"):
        HydrographyManager(config=None, out_path=".", geographic=object())


def _record_the_extent(monkeypatch) -> list:
    """Intercept the port call and keep the extent the manager built."""
    seen: list = []

    def _fetch(source, extent, *, out_dir):
        seen.append((source, extent, out_dir))
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    monkeypatch.setattr(
        "hydromodpy.data.variables.hydrography.manager.fetch_network",
        _fetch,
    )
    return seen


@pytest.mark.fast
def test_a_section_without_a_mask_is_refused_by_name(tmp_path, monkeypatch):
    """No extent is a refusal that names the field, not an AttributeError."""
    _record_the_extent(monkeypatch)
    cfg = HydrographyConfig(sources=[{"source": "osm"}])
    with patch("hydromodpy.spatial.delineation.get_whitebox_backend"):
        manager = HydrographyManager(config=cfg, out_path=tmp_path)
    with pytest.raises(ValueError, match="mask_path"):
        manager._fetch_from_source(cfg.sources[0])


@pytest.mark.fast
def test_the_request_box_leaves_in_the_crs_the_source_declares(tmp_path, monkeypatch):
    """The three hydrography sources declare degrees; the mask is in metres.

    Anti-vacuity: the Lambert-93 bounds of the fixture are around
    ``(300000, 6700000)``. Handing them over unconverted is the defect F5d-1
    removed from the raster managers, and it would fail every assertion here.
    The CRS is no longer a literal in the manager: it is read off the source,
    so a source answering in another frame is asked in that one.
    """
    seen = _record_the_extent(monkeypatch)
    inputs = _fake_inputs(tmp_path, crs="EPSG:2154")
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
    with patch("hydromodpy.spatial.delineation.get_whitebox_backend"):
        manager = HydrographyManager(config=cfg, out_path=tmp_path)

    manager._fetch_from_source(cfg.sources[0])

    source, extent, _ = seen[0]
    assert extent.crs == source.extent_crs == "EPSG:4326"
    lon_min, lat_min, lon_max, lat_max = extent.bbox
    assert -3.0 < lon_min < lon_max < 0.0, (lon_min, lon_max)
    assert 47.0 < lat_min < lat_max < 50.0, (lat_min, lat_max)


@pytest.mark.fast
@patch("hydromodpy.data.variables.hydrography.manager.HydrographyManager._fetch_from_source")
@patch("hydromodpy.spatial.delineation.get_whitebox_backend")
def test_the_clip_happens_in_the_frame_the_mask_declares(
    mock_backend_factory, mock_fetch, tmp_path
):
    """A degrees mask and a metres network still meet, and the output is in degrees.

    This is the read that replaced ``geographic.crs_proj``. The old code
    reprojected the network into a CRS read off the object and clipped against
    a file that was assumed to be in the same one; here the file is the only
    thing that says where anything is, so a mismatch cannot happen.
    """
    mock_backend_factory.return_value = WhiteboxStubBackend()
    mock_fetch.return_value = gpd.GeoDataFrame(
        {"id": [1]},
        geometry=[LineString([(350000.0, 6780000.0), (355000.0, 6785000.0)])],
        crs="EPSG:2154",
    )

    mask_path = _watershed_wgs84(tmp_path / "mask_wgs84.shp")
    inputs = _fake_inputs(tmp_path, crs="EPSG:2154")
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=mask_path)
    manager = HydrographyManager(config=cfg, out_path=tmp_path, base_raster=inputs.base_raster)

    manager.load()

    clipped = gpd.read_file(manager._data_folder / "streams.shp")
    assert not clipped.empty, "the network was dropped, so the two frames never met"
    assert "4326" in str(clipped.crs)


@pytest.mark.fast
def test_rasterising_without_a_reference_grid_is_refused_by_name(tmp_path):
    """``base_raster`` replaced ``geographic.watershed_dem``, and it is required."""
    inputs = _fake_inputs(tmp_path)
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=inputs.mask_path)
    with patch("hydromodpy.spatial.delineation.get_whitebox_backend"):
        manager = HydrographyManager(config=cfg, out_path=tmp_path)
    with pytest.raises(ValueError, match="base_raster"):
        manager._rasterize(inputs.mask_path, "FID")


@pytest.mark.fast
def test_the_loader_fills_a_mask_declared_on_the_section(tmp_path):
    """The generalisation hydrography needs, and the per-source fill it kept."""
    watershed = tmp_path / "watershed.shp"
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=watershed))
    )
    cfg = HydrographyConfig(sources=[{"source": "osm"}])

    DataManagersRuntimeLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == watershed


@pytest.mark.fast
def test_the_loader_leaves_an_authored_section_mask_alone(tmp_path):
    """Anti-vacuity for the fill: it is a default, not an override."""
    authored = tmp_path / "authored.gpkg"
    result = SimpleNamespace(
        setup=SimpleNamespace(geographic=SimpleNamespace(watershed_shp=tmp_path / "ws.shp"))
    )
    cfg = HydrographyConfig(sources=[{"source": "osm"}], mask_path=authored)

    DataManagersRuntimeLoader._apply_default_masks(cfg, result)

    assert cfg.mask_path == authored
