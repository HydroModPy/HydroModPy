"""GeoParquet writer: a vector layer written by HydroModPy is read back unchanged."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Point, box

from hydromodpy.core.io import geoparquet


def _layer(crs: str | None = "EPSG:2154") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": ["spring", "basin"], "area_m2": [0.0, 10_000.0]},
        geometry=[Point(700_050.0, 6_599_950.0), box(700_000, 6_599_900, 700_100, 6_600_000)],
        crs=crs,
    )


def test_a_layer_written_is_read_back_with_the_same_features_and_frame(tmp_path: Path) -> None:
    layer = _layer()

    out = geoparquet.write_geoparquet_atomic(layer, tmp_path / "vectors" / "layer.parquet")
    back = geoparquet.read_geoparquet(out)

    assert out == tmp_path / "vectors" / "layer.parquet"
    assert back.crs.to_epsg() == 2154
    assert back["name"].tolist() == ["spring", "basin"]
    assert back["area_m2"].tolist() == [0.0, 10_000.0]
    assert back.geometry.geom_equals(layer.geometry).all()


def test_the_file_declares_the_geoparquet_version_the_project_promises(tmp_path: Path) -> None:
    out = geoparquet.write_geoparquet_atomic(_layer(), tmp_path / "layer.parquet")

    geo = pq.read_schema(out).metadata[b"geo"]

    assert f'"version":"{geoparquet.GEOPARQUET_SCHEMA_VERSION}"'.encode() in geo.replace(b" ", b"")


def test_metadata_is_kept_in_the_footer_beside_the_geo_block(tmp_path: Path) -> None:
    out = geoparquet.write_geoparquet_atomic(
        _layer(), tmp_path / "layer.parquet", metadata={"run_id": "r-42", "licence": "CC-BY-4.0"}
    )

    footer = pq.read_schema(out).metadata

    assert footer[b"run_id"] == b"r-42"
    assert footer[b"licence"] == b"CC-BY-4.0"
    assert b"geo" in footer
    assert len(geoparquet.read_geoparquet(out)) == 2


def test_only_the_published_file_is_left_after_a_write(tmp_path: Path) -> None:
    geoparquet.write_geoparquet_atomic(_layer(), tmp_path / "layer.parquet", metadata={"k": "v"})

    assert [p.name for p in tmp_path.iterdir()] == ["layer.parquet"]


def test_a_layer_without_crs_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires gdf.crs"):
        geoparquet.write_geoparquet_atomic(_layer(crs=None), tmp_path / "layer.parquet")

    assert list(tmp_path.iterdir()) == []


def test_a_failed_write_leaves_the_previous_file_and_no_temporary(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "layer.parquet"
    geoparquet.write_geoparquet_atomic(_layer(), target)
    before = target.read_bytes()

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(gpd.GeoDataFrame, "to_parquet", explode)

    with pytest.raises(OSError, match="disk full"):
        geoparquet.write_geoparquet_atomic(_layer(), target)

    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["layer.parquet"]


def test_a_failed_write_that_left_a_partial_temporary_removes_it(
    tmp_path: Path, monkeypatch
) -> None:
    def partial_then_explode(self, path, **_kwargs):
        Path(path).write_bytes(b"partial")
        raise OSError("interrupted")

    monkeypatch.setattr(gpd.GeoDataFrame, "to_parquet", partial_then_explode)

    with pytest.raises(OSError, match="interrupted"):
        geoparquet.write_geoparquet_atomic(_layer(), tmp_path / "layer.parquet")

    assert list(tmp_path.iterdir()) == []
