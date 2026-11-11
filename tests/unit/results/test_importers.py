"""Tests for hydromodpy.results.importers, symmetric counterparts of exporters."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import UnknownFieldError
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.exporters.export_spec import ExportRequest
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.importers.csv_timeseries import import_csv_timeseries
from hydromodpy.results.importers.netcdf_fields import import_netcdf_fields
from hydromodpy.results.importers.zarr_field import import_zarr_field
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


@pytest.fixture
def catalog_with_data(tmp_path):
    """A catalog with mesh, head field, and a discharge timeseries."""
    project = tmp_path / "workspace"
    n_cells, n_layers, n_ts = 6, 2, 3
    c = open_run_store(
        project, "demo", n_cells=n_cells, n_layers=n_layers, n_timesteps=n_ts, solver="modflow_nwt"
    )
    sid = c.sim_id

    verts = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [0.5, 0.8],
            [1.5, 0.8],
            [0.8, 1.8],
            [2.0, 0.4],
            [1.8, 1.6],
        ],
        dtype="float64",
    )
    conn = np.array(
        [
            [0, 1, 2, -1],
            [1, 3, 2, -1],
            [2, 3, 4, -1],
            [1, 5, 3, -1],
            [3, 6, 4, -1],
            [3, 5, 6, -1],
        ],
        dtype="int32",
    )
    z_intf = np.array([10.0, 5.0, 0.0])
    c.write_mesh(sid, verts, conn, z_intf)
    c.write_time(
        sid,
        np.array([1577836800, 1577923200, 1578009600], dtype="int64"),
        units="seconds since 1970-01-01T00:00:00Z",
    )

    rng = np.random.default_rng(42)
    for t in range(n_ts):
        head = rng.uniform(3.0, 12.0, (n_layers, n_cells))
        c.write_field(sid, "head", t, head, n_timesteps=n_ts if t == 0 else None)

    idx = pd.date_range("2020-01-01", periods=10, freq="D")
    q = pd.Series(rng.random(10), index=idx, name="recharge")
    c.write_timeseries(sid, "outlet", "recharge", q, unit="m s-1")

    run_dir = c.run_dir
    seal_completed(c)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid, run_dir / "exports"


class TestImportCSVTimeseries:
    def test_roundtrip(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        out = exports / "ts.csv"
        export_run(catalog, sid, ExportRequest(variables="recharge", file=out.name))

        df = import_csv_timeseries(out)
        assert list(df.columns) == [
            "site",
            "case_id",
            "datetime",
            "station_id",
            "variable",
            "source",
            "value",
            "unit",
        ]
        assert len(df) == 10
        assert df["station_id"].iloc[0] == "outlet"
        assert df["variable"].iloc[0] == "recharge"
        assert df["value"].dtype == np.float64
        assert df["datetime"].dt.tz is not None

    def test_filter_variable(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        out = exports / "ts.csv"
        export_run(catalog, sid, ExportRequest(variables="recharge", file=out.name))

        df = import_csv_timeseries(out, variable="recharge")
        assert (df["variable"] == "recharge").all()

    @pytest.mark.parametrize(
        ("asked", "kept"),
        [
            (
                None,
                [("discharge", "simulated"), ("discharge", "observed"), ("nitrate", "observed")],
            ),
            ("discharge", [("discharge", "simulated")]),
            ("discharge_obs", [("discharge", "observed")]),
            ("nitrate_obs", [("nitrate", "observed")]),
        ],
    )
    def test_a_measurement_and_a_series_read_back_by_their_name(self, tmp_path, asked, kept):
        out = tmp_path / "ts.csv"
        out.write_text(
            "site,case_id,datetime,station_id,variable,source,value,unit\n"
            "n,n_run,2020-02-01,catchment,discharge,simulated,1.0,m3 s-1\n"
            "n,n_run,2020-01-01,J001,discharge,observed,2.0,m3 s-1\n"
            "n,n_run,2020-01-01,J001,nitrate,observed,3.0,mg L-1\n"
        )

        df = import_csv_timeseries(out, variable=asked)

        assert list(zip(df["variable"], df["source"], strict=True)) == kept

    def test_a_source_the_exporter_never_writes_is_refused(self, tmp_path):
        out = tmp_path / "ts.csv"
        out.write_text(
            "site,case_id,datetime,station_id,variable,source,value,unit\n"
            "n,n_run,2020-01-01,outlet,discharge,modelled,1.0,m3 s-1\n"
        )
        with pytest.raises(ValueError, match="neither 'simulated' nor 'observed'"):
            import_csv_timeseries(out)

    def test_unknown_variable_raises(self, tmp_path):
        out = tmp_path / "ts.csv"
        out.write_text("site,case_id,datetime,station_id,variable,source,value,unit\n")
        with pytest.raises(UnknownFieldError):
            import_csv_timeseries(out, variable="not_a_field")

    def test_unknown_variable_in_file_raises(self, tmp_path):
        out = tmp_path / "ts.csv"
        out.write_text(
            "site,case_id,datetime,station_id,variable,source,value,unit\n"
            "n,n_run,2020-01-01,outlet,bogus_variable,simulated,1.0,m\n"
        )
        with pytest.raises(UnknownFieldError):
            import_csv_timeseries(out)

    def test_missing_columns_raises(self, tmp_path):
        out = tmp_path / "bad.csv"
        out.write_text("a,b,c\n1,2,3\n")
        with pytest.raises(ValueError, match="missing required columns"):
            import_csv_timeseries(out)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_csv_timeseries(tmp_path / "absent.csv")

    def test_empty_file_returns_empty_frame(self, tmp_path):
        out = tmp_path / "empty.csv"
        out.write_text("site,case_id,datetime,station_id,variable,source,value,unit\n")
        df = import_csv_timeseries(out)
        assert df.empty


class TestImportNetCDFFields:
    def test_roundtrip_head(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        out = exports / "fields.nc"
        export_run(catalog, sid, ExportRequest(variables="head", file=out.name))

        fields = import_netcdf_fields(out, ["head"])
        assert "head" in fields
        assert fields["head"].shape == (3, 2, 6)

    def test_default_loads_registered_only(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        out = exports / "fields.nc"
        export_run(catalog, sid, ExportRequest(variables="head", file=out.name))

        fields = import_netcdf_fields(out)
        assert "head" in fields
        assert "node_x" not in fields

    def test_timestep_subset(self, catalog_with_data):
        catalog, sid, exports = catalog_with_data
        out = exports / "fields.nc"
        export_run(catalog, sid, ExportRequest(variables="head", file=out.name))

        fields = import_netcdf_fields(out, ["head"], timesteps=[0, 2])
        assert fields["head"].shape == (2, 2, 6)

    def test_unknown_variable_raises(self, tmp_path):
        with pytest.raises(UnknownFieldError):
            import_netcdf_fields(tmp_path / "any.nc", ["not_a_field"])

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_netcdf_fields(tmp_path / "absent.nc", ["head"])


class TestImportZarrField:
    def test_read_head(self, catalog_with_data):
        catalog, sid, _ = catalog_with_data
        zarr_path = catalog.fields_path_for(sid)

        data = import_zarr_field(zarr_path, "head")
        assert data.shape == (3, 2, 6)

    def test_timestep_subset(self, catalog_with_data):
        catalog, sid, _ = catalog_with_data
        zarr_path = catalog.fields_path_for(sid)

        data = import_zarr_field(zarr_path, "head", timesteps=[1])
        assert data.shape == (1, 2, 6)

    def test_unknown_variable_raises(self, catalog_with_data):
        catalog, sid, _ = catalog_with_data
        zarr_path = catalog.fields_path_for(sid)
        with pytest.raises(UnknownFieldError):
            import_zarr_field(zarr_path, "not_a_field")

    def test_missing_field_raises(self, catalog_with_data):
        catalog, sid, _ = catalog_with_data
        zarr_path = catalog.fields_path_for(sid)
        with pytest.raises(KeyError, match="watertable_depth"):
            import_zarr_field(zarr_path, "watertable_depth")

    def test_missing_store_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_zarr_field(tmp_path / "absent.zarr", "head")
