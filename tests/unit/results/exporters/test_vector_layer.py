"""A stored vector layer and the pathlines of a run, written to a GeoPackage or a Shapefile."""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.results.exporters.vector_layer import export_geographic_feature, export_pathlines


class _Catalog:
    def __init__(self, frame: gpd.GeoDataFrame) -> None:
        self.frame = frame

    def read_geographic_feature(self, sim_id: str, name: str) -> gpd.GeoDataFrame:
        return self.frame


def _network(fid: list[float] | None) -> gpd.GeoDataFrame:
    lines = [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 0)])]
    columns = {"name": ["a", "b"]} if fid is None else {"fid": fid, "name": ["a", "b"]}
    return gpd.GeoDataFrame(columns, geometry=lines, crs="EPSG:2154")


@pytest.mark.parametrize("fid", [None, [1.0, 2.0], [7.5, 7.5]])
def test_a_layer_with_or_without_a_fid_column_is_written_and_kept(tmp_path, fid):
    path = export_geographic_feature(
        _Catalog(_network(fid)), "sim", "network", tmp_path / "network.gpkg"
    )
    written = gpd.read_file(path, layer="network")
    assert written["name"].tolist() == ["a", "b"]
    if fid is not None:
        assert written["fid"].tolist() == fid


class _Particles:
    """The ``particles`` group of a field store: two particles along x, the second never timed."""

    attrs = {"time_units": "days"}
    arrays = {
        "x": np.array([[0.0, 1.0, 2.0], [0.0, 1.0, 2.0]]),
        "y": np.array([[0.0, 0.0, 0.0], [2.0, 2.0, 2.0]]),
        "time": np.array([[0.0, 365.25, 730.5], [np.nan, np.nan, np.nan]]),
    }

    def get(self, name: str):
        return self if name == "particles" else None

    def __contains__(self, name: str) -> bool:
        return name in self.arrays

    def __getitem__(self, name: str) -> np.ndarray:
        return self.arrays[name]


def _run_with_two_particles() -> SimpleNamespace:
    store = SimpleNamespace(root=_Particles(), close=lambda: None)
    return SimpleNamespace(sim_id="sim", _catalog=SimpleNamespace(open_zarr=lambda _id: store))


@pytest.mark.parametrize(("suffix", "crs"), [("gpkg", None), ("shp", "EPSG:4326")])
def test_the_pathlines_are_one_line_per_particle_that_moved_with_its_travel_time(
    tmp_path, suffix, crs
):
    fmt = {"gpkg": "geopackage", "shp": "shapefile"}[suffix]
    path = export_pathlines(
        _run_with_two_particles(), tmp_path / f"p.{suffix}", fmt=fmt, crs=crs, model_crs="EPSG:2154"
    )
    written = gpd.read_file(path)
    assert written["travel_yr"].tolist() == [2.0] and written.geom_type.tolist() == ["LineString"]
    assert written.crs.to_epsg() == (4326 if crs else 2154)
    with pytest.raises(ValueError, match="not 'csv'"):
        export_pathlines(_run_with_two_particles(), tmp_path / "p.csv", fmt="csv")
