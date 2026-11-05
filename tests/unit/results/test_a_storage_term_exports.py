"""A storage budget term is listed, read and exported like any other field.

The run holds a head field of one layer and ``budget/storage_sy`` (the
MODFLOW 6 specific-yield term) on four Lambert-93 cells, over three monthly
periods, written by its store, sealed and indexed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.exporters.export_spec import ExportKind, ExportRequest
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.exporters.vocabulary import list_exportable
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

X0, Y0, STEP = 385000.0, 6814000.0, 500.0
STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])
# Multiples of 1/4 are exact in float32, the width the store keeps.
STORAGE_SY = np.arange(12, dtype="float64").reshape(3, 1, 4) * 0.25


@pytest.fixture
def storage_run(tmp_path):
    project = tmp_path / "workspace"
    store = open_run_store(
        project,
        "demo",
        n_cells=4,
        n_layers=1,
        n_timesteps=3,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 4, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    verts = np.array(
        [[X0 + i * STEP, Y0 + j * STEP] for j in range(3) for i in range(3)], dtype="float64"
    )
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
    store.write_mesh(sid, verts, conn, np.array([50.0, 0.0]))
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
    for t in range(3):
        store.write_field(
            sid,
            "head",
            t,
            np.array([[12.5, 14.25, 16.75, 19.0]]) + t,
            n_timesteps=3 if t == 0 else None,
        )
    store.write_field_stack(sid, "storage_sy", STORAGE_SY, subgroup="budget")
    run_dir = store.run_dir
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid, run_dir / "exports"


def test_the_run_lists_and_reads_the_storage_term(storage_run) -> None:
    catalog, sid, _exports = storage_run
    run = catalog[sid]
    assert "storage_sy" in run.array.list_fields()
    assert list_exportable(run)["storage_sy"] is ExportKind.field
    np.testing.assert_allclose(run.field("storage_sy", time=1, layer=0), STORAGE_SY[1, 0])


def test_the_storage_term_exports_to_netcdf(storage_run) -> None:
    catalog, sid, exports = storage_run
    written = export_run(catalog, sid, ExportRequest(variables="storage_sy"))
    assert written == [exports / "storage_sy.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert ds["storage_sy"].attrs["units"] == "m3 s-1"
        np.testing.assert_allclose(ds["storage_sy"].values.reshape(3, 1, 4), STORAGE_SY)


def test_the_storage_term_exports_to_geotiff(storage_run) -> None:
    import rasterio

    catalog, sid, exports = storage_run
    written = export_run(
        catalog, sid, ExportRequest(variables="storage_sy", time="2000-02-15", format="geotiff")
    )
    assert written == [exports / "storage_sy_2000-02-15.tif"]
    with rasterio.open(written[0]) as src:
        assert np.nanmax(src.read(1)) == pytest.approx(STORAGE_SY[1, 0].max())


def test_all_includes_the_storage_term(storage_run) -> None:
    catalog, sid, _exports = storage_run
    (written,) = export_run(catalog, sid, ExportRequest(variables="all"))
    with xr.open_dataset(written) as ds:
        assert {"head", "storage_sy"} <= set(ds.data_vars)
