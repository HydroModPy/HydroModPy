"""An export request resolves its raster resolution (m) from the smallest cell of the mesh."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.exporters.export_spec import ExportRequest
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


def test_a_default_resolution_with_too_many_pixels_asks_for_one(project):
    # A 1 m cell in a 200 km wide domain: 4e10 pixels.
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [200_000.0, 0.0, 0.0],
            [200_000.0, 200_000.0, 0.0],
            [0.0, 200_000.0, 0.0],
        ]
    )
    faces = np.array([[0, 1, 2, 3], [1, 4, 5, 2], [3, 2, 5, 6]], dtype=np.int32)
    store = open_run_store(
        project,
        "run0",
        n_cells=3,
        n_layers=1,
        n_timesteps=1,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 2, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    zarr_store = store.open_zarr(sid)
    try:
        zarr_store.write_mesh(vertices, faces, np.array([10.0, 0.0]))
    finally:
        zarr_store.close()
    store.write_time(sid, np.array(["2000-02-01"], dtype="datetime64[s]").astype("int64"))
    store.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
    store.write_field(sid, "head", 0, np.arange(3.0).reshape(1, -1), n_timesteps=1)
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        with pytest.raises(ValueError, match=r"resolution=") as raised:
            export_run(catalog, sid, ExportRequest(variables="head", time="2000-01-15"))
        assert "smallest cell" in str(raised.value)

        written = export_run(
            catalog, sid, ExportRequest(variables="head", time="2000-01-15", resolution=20_000.0)
        )
        assert written[0].exists()
