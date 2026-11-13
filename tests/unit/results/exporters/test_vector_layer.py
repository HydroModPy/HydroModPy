"""A stored vector layer written to a GeoPackage or a Shapefile."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from hydromodpy.results.exporters.vector_layer import export_geographic_feature


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
