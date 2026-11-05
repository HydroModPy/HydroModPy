"""An export request names data; the format, the files and their names follow.

The run is a monthly transient run of three stress periods (January to March
2000) on four Lambert-93 cells, written by its store, sealed and indexed. It
holds a head field of one layer, the simulated discharge at the catchment and
the gauged discharge from October 1999, the delineated catchment and the
mapped network as vector layers, the DEM as a raster layer, and the water
budget. Every file lands under ``runs/demo/exports/``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import LineString, box

from hydromodpy.core.time import TimeSelectionError
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.exporters import request as request_module
from hydromodpy.results.exporters import vocabulary
from hydromodpy.results.exporters.export_spec import ExportKind, ExportRequest
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.exporters.vocabulary import list_exportable
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

X0, Y0, STEP = 385000.0, 6814000.0, 500.0
STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])
"""The end of each monthly period: a stamp closes its period."""


@pytest.fixture
def dated_run(tmp_path):
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
    store.write_timeseries(
        sid, "catchment", "discharge", pd.Series([1.0, 2.0, 3.0], index=STAMPS), unit="m3/s"
    )
    gauged = pd.Series(np.arange(200.0), index=pd.date_range("1999-10-01", periods=200, freq="D"))
    store.write_timeseries(sid, "NANCON", "discharge", gauged, unit="m3/s", source="observed")
    extent = box(X0, Y0, X0 + 2 * STEP, Y0 + 2 * STEP)
    store.write_geographic_feature(
        sid, "watershed", gpd.GeoDataFrame(geometry=[extent], crs="EPSG:2154")
    )
    river = LineString([(X0 + STEP, Y0), (X0 + STEP, Y0 + 2 * STEP)])
    store.write_geographic_feature(
        sid,
        "hydrographic_network_reference",
        gpd.GeoDataFrame(geometry=[river], crs="EPSG:2154"),
    )
    dem = np.arange(100.0, dtype="float64").reshape(10, 10)
    store.write_geographic_raster(
        sid,
        "watershed_dem",
        dem,
        transform=(100.0, 0.0, X0, 0.0, -100.0, Y0 + 1000.0),
        crs="EPSG:2154",
        nodata=-99999.0,
    )
    store.write_budgets(
        sid,
        [
            {
                "timestep": t,
                "zone_id": "catchment",
                "component": "recharge",
                "flux_in": 1.0 + t,
                "flux_out": 0.0,
            }
            for t in range(3)
        ],
    )
    run_dir = store.run_dir
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as reader:
        yield reader, sid, run_dir / "exports"


def _names(paths: list[Path]) -> list[str]:
    return sorted(path.name for path in paths)


def test_the_run_lists_what_it_can_export_by_kind(dated_run) -> None:
    catalog, sid, _exports = dated_run
    names = list_exportable(catalog[sid])
    assert names["head"] is ExportKind.field
    assert names["watertable_depth"] is ExportKind.field
    assert names["discharge"] is ExportKind.series
    assert names["discharge_obs"] is ExportKind.series
    assert names["watershed"] is ExportKind.vector
    assert names["hydrographic_network_reference"] is ExportKind.vector
    assert names["watershed_dem"] is ExportKind.raster
    assert names["budget"] is ExportKind.table
    # No release flux, no network criterion: the simulated network is not offered.
    assert "simulated_active_network" not in names


def test_a_field_at_one_date_is_one_geotiff_named_by_the_date(dated_run) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="head", time="2000-02-15"))
    assert written == [exports / "head_2000-02-15.tif"]
    with rasterio.open(written[0]) as src:
        # 2000-02-15 falls in the February period, the second one.
        assert np.nanmax(src.read(1)) == pytest.approx(20.0)
        assert src.tags()["HMP_PERIOD"] == "2000-02"


def test_several_dates_are_one_netcdf_by_default(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="head", time=["2000-01-10", "last"]))
    assert written == [exports / "head.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert ds.sizes["time"] == 2


def test_several_dates_in_a_one_instant_format_write_one_file_per_date(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(
        catalog,
        sid,
        ExportRequest(
            variables=["head", "watertable_depth"], time=["2000-01-10", "last"], format="geotiff"
        ),
    )
    assert _names(written) == [
        "head_2000-01-10.tif",
        "head_last.tif",
        "watertable_depth_2000-01-10.tif",
        "watertable_depth_last.tif",
    ]
    assert all(path.parent == exports for path in written)


def test_a_one_instant_format_over_the_whole_run_writes_one_file_per_period(dated_run) -> None:
    catalog, sid, _exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="head", format="geotiff"))
    assert _names(written) == ["head_2000-01.tif", "head_2000-02.tif", "head_2000-03.tif"]


def test_fields_over_the_run_share_one_netcdf_with_the_run_metadata(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables=["head", "watertable_depth"]))
    assert written == [exports / "demo_fields.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert {"head", "watertable_depth"} <= set(ds.data_vars)
        assert ds.sizes["time"] == 3
        # Exported before the seal, the file still says how large the mesh is
        # and carries the ACDD block the seal composes.
        assert int(ds.attrs["n_cells"]) == 4
        assert ds.attrs["title"] == "demo"


def test_a_period_keeps_the_periods_it_overlaps(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(
        catalog, sid, ExportRequest(variables="head", period=["2000-02-15", "2000-03-10"])
    )
    assert written == [exports / "head_2000-02-15_2000-03-10.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert ds.sizes["time"] == 2


def test_all_in_one_format_writes_every_data_that_format_holds(dated_run) -> None:
    catalog, sid, _exports = dated_run
    written = export_run(
        catalog, sid, ExportRequest(variables="all", time="2000-03-01", format="geotiff")
    )
    assert _names(written) == [
        "head_2000-03-01.tif",
        "seepage_mask_2000-03-01.tif",
        "watershed_dem.tif",
        "watertable_depth_2000-03-01.tif",
        "watertable_elevation_2000-03-01.tif",
    ]


def test_all_writes_each_data_in_its_natural_format(dated_run) -> None:
    catalog, sid, _exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="all"))
    assert _names(written) == [
        "budget.csv",
        "demo_fields.nc",
        "demo_series.csv",
        "hydrographic_network_reference.gpkg",
        "watershed.gpkg",
        "watershed_dem.tif",
    ]


def test_the_catchment_is_a_geopackage_in_the_model_crs(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="watershed"))
    assert written == [exports / "watershed.gpkg"]
    layer = gpd.read_file(written[0])
    assert len(layer) == 1
    assert layer.crs.to_epsg() == 2154


def test_a_vector_layer_is_written_as_a_shapefile_and_reprojected(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(
        catalog,
        sid,
        ExportRequest(
            variables="hydrographic_network_reference", format="shapefile", crs="EPSG:4326"
        ),
    )
    assert written == [exports / "hydrographic_network_reference.shp"]
    layer = gpd.read_file(written[0])
    assert layer.crs.to_epsg() == 4326
    assert layer.total_bounds[0] == pytest.approx(-1.6, abs=2.0)


def test_the_dem_is_a_geotiff_on_its_own_grid(dated_run) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    (dem,) = export_run(catalog, sid, ExportRequest(variables="watershed_dem"))
    assert dem == exports / "watershed_dem.tif"
    with rasterio.open(dem) as src:
        assert src.crs.to_epsg() == 2154
        assert src.res == (100.0, 100.0)
        assert src.read(1)[0, 0] == 0.0
        assert src.nodata == -99999.0


def test_the_dem_is_warped_to_the_crs_and_resolution_asked(dated_run) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    (dem,) = export_run(
        catalog, sid, ExportRequest(variables="watershed_dem", file="dem_50m.tif", resolution=50)
    )
    assert dem == exports / "dem_50m.tif"
    with rasterio.open(dem) as src:
        assert src.res == (50.0, 50.0)
    (wgs84,) = export_run(
        catalog, sid, ExportRequest(variables="watershed_dem", file="dem.tif", crs="EPSG:4326")
    )
    with rasterio.open(wgs84) as src:
        assert src.crs.to_epsg() == 4326


def test_the_budget_is_a_csv_naming_each_period(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(catalog, sid, ExportRequest(variables="budget", time="2000-02-10"))
    assert written == exports / "budget_2000-02-10.csv"
    frame = pd.read_csv(written)
    assert list(frame.columns) == [
        "site",
        "case_id",
        "period_start",
        "period_end",
        "timestep",
        "zone_id",
        "component",
        "flux_in",
        "flux_out",
        "unit",
    ]
    assert frame["timestep"].tolist() == [1]
    assert frame["period_start"].tolist() == ["2000-02-01 00:00:00"]
    assert frame["period_end"].tolist() == ["2000-03-01 00:00:00"]


def test_series_are_written_on_the_run_clock_and_clipped_to_the_simulation(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(catalog, sid, ExportRequest(variables=["discharge", "discharge_obs"]))
    assert written == exports / "demo_series.csv"
    frame = pd.read_csv(written)
    simulated = frame[frame["source"] == "simulated"]
    # Naive times of the run clock: no session-zone offset, midnight stays midnight.
    assert simulated["datetime"].tolist() == [
        "2000-02-01 00:00:00",
        "2000-03-01 00:00:00",
        "2000-04-01 00:00:00",
    ]
    assert set(simulated["station_id"]) == {"catchment"}
    assert set(frame["variable"]) == {"discharge"}
    gauged = frame[frame["source"] == "observed"]
    # The record starts in October 1999; the file keeps the simulated window only.
    assert gauged["datetime"].min() == "2000-01-01 00:00:00"
    assert gauged["datetime"].max() == "2000-03-31 00:00:00"


def test_a_period_clips_each_series_to_the_periods_it_overlaps(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(
        catalog,
        sid,
        ExportRequest(
            variables=["discharge", "discharge_obs"], period=["2000-02-01", "2000-02-20"]
        ),
    )
    assert written == exports / "demo_series_2000-02-01_2000-02-20.csv"
    frame = pd.read_csv(written)
    simulated = frame[frame["source"] == "simulated"]
    assert simulated["datetime"].tolist() == ["2000-03-01 00:00:00"]
    gauged = frame[frame["source"] == "observed"]
    assert gauged["datetime"].min() == "2000-02-01 00:00:00"
    assert gauged["datetime"].max() == "2000-02-29 00:00:00"


def test_a_folder_and_a_file_are_read_from_the_exports_of_the_run(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="watershed", folder="livrables"))
    assert written == [exports / "livrables" / "watershed.gpkg"]
    written = export_run(catalog, sid, ExportRequest(variables="watershed", file="bassin.gpkg"))
    assert written == [exports / "bassin.gpkg"]


def test_every_file_is_recorded_in_the_ledger_of_the_exports(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(catalog, sid, ExportRequest(variables="head", time="last"))
    (entry,) = Ledger.read(exports).entries
    assert entry.file == written.name
    assert entry.options == {"variables": "head", "time": "last", "nodata": -9999.0}


def test_a_metadata_view_is_written_beside_the_seal(dated_run) -> None:
    catalog, sid, exports = dated_run
    (view,) = export_run(catalog, sid, ExportRequest(variables="all", format="stac"))
    assert view == catalog.run_dir_for(sid) / "stac-item.json"
    assert view.is_file()
    (lineage,) = export_run(
        catalog, sid, ExportRequest(variables="all", format="prov", folder="meta")
    )
    assert lineage == exports / "meta" / "prov.jsonld"
    assert lineage.is_file()


def test_the_simulated_network_is_exported_by_date_and_over_the_run(dated_run, monkeypatch) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    flowing = {0: [1.0, 0.0, 0.0, 0.0], 1: [1.0, 1.0, 0.0, 0.0], 2: [1.0, 1.0, 1.0, 0.0]}
    asked: list[list[int]] = []

    def stack(_run, steps):
        asked.append([int(step) for step in steps])
        return np.asarray([flowing[int(step)] for step in steps])

    monkeypatch.setattr(vocabulary, "_simulated_network_available", lambda _run: True)
    monkeypatch.setattr(request_module, "simulated_active_network_stack", stack)

    (tif,) = export_run(
        catalog, sid, ExportRequest(variables="simulated_active_network", time="2000-02-15")
    )
    assert tif == exports / "simulated_active_network_2000-02-15.tif"
    with rasterio.open(tif) as src:
        values = src.read(1)
        assert set(np.unique(values[values != src.nodata])) == {0.0, 1.0}

    (gpkg,) = export_run(
        catalog,
        sid,
        ExportRequest(variables="simulated_active_network", time="last", format="geopackage"),
    )
    # Only the active cells are written: flowing[2] holds one inactive cell,
    # and a network export is not a raster of the whole domain.
    assert gpd.read_file(gpkg)["simulated_active_network"].tolist() == [1.0, 1.0, 1.0]

    (nc,) = export_run(catalog, sid, ExportRequest(variables=["head", "simulated_active_network"]))
    with xr.open_dataset(nc) as ds:
        np.testing.assert_array_equal(ds["simulated_active_network"].values, list(flowing.values()))
        assert ds["simulated_active_network"].attrs["units"] == "1"
    # The graph is built once per request, never once per step.
    assert asked == [[1], [2], [0, 1, 2]]


def test_a_run_without_the_network_says_why_it_cannot_export_it(dated_run) -> None:
    from hydromodpy.core.exceptions import ExportError

    catalog, sid, _exports = dated_run
    with pytest.raises(ExportError, match="no per-cell release_flux"):
        export_run(catalog, sid, ExportRequest(variables="simulated_active_network", time="last"))


def test_run_export_and_hmp_export_speak_the_words_of_the_toml(dated_run) -> None:
    import hydromodpy as hmp

    catalog, sid, exports = dated_run
    run = catalog[sid]
    assert run.export("head", time="2000-01-15") == [exports / "head_2000-01-15.tif"]
    assert hmp.export(run, "discharge", period=("2000-01-01", "2000-01-31")) == [
        exports / "discharge_2000-01-01_2000-01-31.csv"
    ]


@pytest.mark.parametrize("fmt", ["netcdf", "geotiff"])
def test_two_dates_that_read_one_period_are_refused_in_every_format(dated_run, fmt: str) -> None:
    catalog, sid, exports = dated_run
    request = ExportRequest(variables="head", time=["2000-01-10", "2000-01-20"], format=fmt)

    with pytest.raises(TimeSelectionError, match="'2000-01-10' and '2000-01-20' read the same"):
        export_run(catalog, sid, request)

    assert not exports.exists() or not any(exports.iterdir())


def test_an_empty_time_list_is_refused_before_any_file(dated_run) -> None:
    from pydantic import ValidationError

    catalog, sid, exports = dated_run
    with pytest.raises(ValidationError, match="names no instant"):
        catalog[sid].export("discharge", time=[])
    assert not exports.exists() or not any(exports.iterdir())


def test_a_selection_of_no_period_is_an_export_error(dated_run, monkeypatch) -> None:
    """A series asked over no period says so, never as a SQL syntax error."""
    from hydromodpy.core.exceptions import ExportError
    from hydromodpy.results.run.periods import RunPeriods

    catalog, sid, _exports = dated_run
    monkeypatch.setattr(RunPeriods, "steps_for", lambda self, **_: ())
    with pytest.raises(ExportError, match="selects no stress period"):
        export_run(catalog, sid, ExportRequest(variables="discharge", time="last"))
