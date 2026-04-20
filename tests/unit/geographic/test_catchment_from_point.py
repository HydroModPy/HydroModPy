from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.delineation.whitebox_workflows_backend import WhiteboxWorkflowsBackend
from hydromodpy.spatial.geographic.core.catchment_from_point import extract_catchment_from_point


class _DummyVector:
    def __init__(self, records):
        self.records = list(records)


def test_extract_catchment_from_point_rejects_empty_snapped_outlet(
    monkeypatch,
    tmp_path: Path,
) -> None:
    backend = WhiteboxWorkflowsBackend()

    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.core.catchment_from_point.ensure_crs",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(backend, "read_vector", lambda path: _DummyVector([object()]))
    monkeypatch.setattr(backend, "snap_pour_points_vector", lambda *args, **kwargs: _DummyVector([]))
    monkeypatch.setattr(
        backend,
        "write_vector",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("write_vector should not be called")),
    )

    with pytest.raises(ValueError, match="Outlet snapping produced no feature"):
        extract_catchment_from_point(
            x_outlet=10.0,
            y_outlet=20.0,
            snap_dist=50,
            acc_path=tmp_path / "acc.tif",
            direc_path=tmp_path / "direc.tif",
            output_dir=tmp_path / "geo",
            crs_project="EPSG:2154",
            acc_data=object(),
            direc_data=object(),
            backend=backend,
        )


def test_extract_catchment_from_point_rejects_empty_watershed_polygon(
    monkeypatch,
    tmp_path: Path,
) -> None:
    backend = WhiteboxWorkflowsBackend()
    write_targets: list[str] = []

    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.core.catchment_from_point.ensure_crs",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(backend, "read_vector", lambda path: _DummyVector([object()]))
    monkeypatch.setattr(
        backend,
        "snap_pour_points_vector",
        lambda *args, **kwargs: _DummyVector([object()]),
    )
    monkeypatch.setattr(backend, "watershed_raster", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        backend,
        "raster_to_vector_polygons_raster",
        lambda *args, **kwargs: _DummyVector([]),
    )
    monkeypatch.setattr(backend, "write_raster", lambda *args, **kwargs: None)

    def _fake_write_vector(vector, path: str) -> None:
        write_targets.append(str(path))

    monkeypatch.setattr(backend, "write_vector", _fake_write_vector)

    with pytest.raises(ValueError, match="Watershed delineation produced an empty polygon"):
        extract_catchment_from_point(
            x_outlet=10.0,
            y_outlet=20.0,
            snap_dist=50,
            acc_path=tmp_path / "acc.tif",
            direc_path=tmp_path / "direc.tif",
            output_dir=tmp_path / "geo",
            crs_project="EPSG:2154",
            acc_data=object(),
            direc_data=object(),
            backend=backend,
        )

    assert len(write_targets) == 1
    assert write_targets[0].endswith("outlet_snap.shp")
