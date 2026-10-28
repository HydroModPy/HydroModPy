"""The backend plumbing and the vector helper of the geographic step."""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from hydromodpy.spatial.delineation import get_backend
from hydromodpy.spatial.geographic import geographic_io
from hydromodpy.spatial.geographic.geographic_io import (
    backend_has_callables,
    resolve_delineation_backend,
    write_shapefile_without_duplicate_columns,
)
from tests._helpers.geographic_cases import LAMBERT


def test_an_injected_backend_wins_over_the_registry() -> None:
    injected = object()

    assert resolve_delineation_backend(injected) is injected
    assert resolve_delineation_backend() is get_backend()


_READ = SimpleNamespace(read=lambda: None, write=None)


@pytest.mark.parametrize(
    ("backend", "methods", "expected"),
    [
        (SimpleNamespace(), ("read",), False),
        (SimpleNamespace(raster=_READ), ("read",), True),
        (SimpleNamespace(raster=_READ), ("read", "write"), False),
    ],
    ids=["no-component", "every-method", "a-method-is-not-callable"],
)
def test_a_backend_has_a_capability_only_when_every_method_is_callable(
    backend, methods, expected
) -> None:
    assert backend_has_callables(backend, "raster", *methods) is expected


def test_a_shapefile_is_written_back_with_each_column_once(tmp_path, monkeypatch) -> None:
    frame = gpd.GeoDataFrame({"code": ["a", "b"]}, geometry=[Point(0, 0), Point(1, 1)], crs=LAMBERT)
    doubled = pd.concat([frame[["code"]], frame], axis=1)
    monkeypatch.setattr(geographic_io.gpd, "read_file", lambda path: gpd.GeoDataFrame(doubled))

    write_shapefile_without_duplicate_columns("ignored.shp", tmp_path / "out.shp")

    monkeypatch.undo()
    written = gpd.read_file(tmp_path / "out.shp")
    assert list(written.columns) == ["code", "geometry"]
    assert written["code"].tolist() == ["a", "b"]
