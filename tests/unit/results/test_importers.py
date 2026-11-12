"""Importers read back what the exporters wrote: discharge series from CSV, fields from NetCDF and Zarr.

The run has 6 cells, 2 layers and 3 time steps (head in m), and a recharge series
of 10 daily values at the outlet (m s-1).
"""

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


CSV_HEADER = "site,case_id,datetime,station_id,variable,source,value,unit\n"
CSV_COLUMNS = ["site", "case_id", "datetime", "station_id", "variable", "source", "value", "unit"]


def export_head_to_netcdf(catalog, sid, exports):
    out = exports / "fields.nc"
    export_run(catalog, sid, ExportRequest(variables="head", file=out.name))
    return out


def test_csv_roundtrip(catalog_with_data):
    catalog, sid, exports = catalog_with_data
    out = exports / "ts.csv"
    export_run(catalog, sid, ExportRequest(variables="recharge", file=out.name))

    df = import_csv_timeseries(out)

    assert list(df.columns) == CSV_COLUMNS
    assert len(df) == 10
    assert df["station_id"].iloc[0] == "outlet"
    assert df["variable"].iloc[0] == "recharge"
    assert df["value"].dtype == np.float64
    assert df["datetime"].dt.tz is not None


def test_csv_filter_variable(catalog_with_data):
    catalog, sid, exports = catalog_with_data
    out = exports / "ts.csv"
    export_run(catalog, sid, ExportRequest(variables="recharge", file=out.name))

    df = import_csv_timeseries(out, variable="recharge")

    assert (df["variable"] == "recharge").all()


KEPT = [
    pytest.param(
        None,
        [("discharge", "simulated"), ("discharge", "observed"), ("nitrate", "observed")],
        id="all",
    ),
    pytest.param("discharge", [("discharge", "simulated")], id="simulated by its name"),
    pytest.param("discharge_obs", [("discharge", "observed")], id="measurement by its name"),
    pytest.param("nitrate_obs", [("nitrate", "observed")], id="other measurement"),
]


@pytest.mark.parametrize(("asked", "kept"), KEPT)
def test_csv_measurement_and_series_by_name(tmp_path, asked, kept):
    out = tmp_path / "ts.csv"
    out.write_text(
        CSV_HEADER + "n,n_run,2020-02-01,catchment,discharge,simulated,1.0,m3 s-1\n"
        "n,n_run,2020-01-01,J001,discharge,observed,2.0,m3 s-1\n"
        "n,n_run,2020-01-01,J001,nitrate,observed,3.0,mg L-1\n"
    )

    df = import_csv_timeseries(out, variable=asked)

    assert list(zip(df["variable"], df["source"], strict=True)) == kept


def test_csv_empty_file(tmp_path):
    out = tmp_path / "empty.csv"
    out.write_text(CSV_HEADER)

    assert import_csv_timeseries(out).empty


def test_netcdf_roundtrip_head(catalog_with_data):
    catalog, sid, exports = catalog_with_data

    fields = import_netcdf_fields(export_head_to_netcdf(catalog, sid, exports), ["head"])

    assert fields["head"].shape == (3, 2, 6)


def test_netcdf_default_loads_registered_only(catalog_with_data):
    catalog, sid, exports = catalog_with_data

    fields = import_netcdf_fields(export_head_to_netcdf(catalog, sid, exports))

    assert "head" in fields
    assert "node_x" not in fields


def test_netcdf_timestep_subset(catalog_with_data):
    catalog, sid, exports = catalog_with_data

    out = export_head_to_netcdf(catalog, sid, exports)
    fields = import_netcdf_fields(out, ["head"], timesteps=[0, 2])

    assert fields["head"].shape == (2, 2, 6)


ZARR_SHAPES = [
    pytest.param(None, (3, 2, 6), id="all steps"),
    pytest.param([1], (1, 2, 6), id="one step"),
]


@pytest.mark.parametrize(("timesteps", "shape"), ZARR_SHAPES)
def test_zarr_read_head(catalog_with_data, timesteps, shape):
    catalog, sid, _ = catalog_with_data

    data = import_zarr_field(catalog.fields_path_for(sid), "head", timesteps=timesteps)

    assert data.shape == shape


ZARR_REFUSALS = [
    pytest.param("not_a_field", UnknownFieldError, None, id="unknown variable"),
    pytest.param("watertable_depth", KeyError, "watertable_depth", id="field not stored"),
]


@pytest.mark.parametrize(("variable", "error", "match"), ZARR_REFUSALS)
def test_zarr_refusals(catalog_with_data, variable, error, match):
    catalog, sid, _ = catalog_with_data

    with pytest.raises(error, match=match):
        import_zarr_field(catalog.fields_path_for(sid), variable)


CSV_REFUSALS = [
    pytest.param(
        CSV_HEADER + "n,n_run,2020-01-01,outlet,discharge,modelled,1.0,m3 s-1\n",
        None,
        ValueError,
        "neither 'simulated' nor 'observed'",
        id="source the exporter never writes",
    ),
    pytest.param(CSV_HEADER, "not_a_field", UnknownFieldError, None, id="unknown variable asked"),
    pytest.param(
        CSV_HEADER + "n,n_run,2020-01-01,outlet,bogus_variable,simulated,1.0,m\n",
        None,
        UnknownFieldError,
        None,
        id="unknown variable in file",
    ),
    pytest.param("a,b,c\n1,2,3\n", None, ValueError, "missing required columns", id="columns"),
]


@pytest.mark.parametrize(("text", "variable", "error", "match"), CSV_REFUSALS)
def test_csv_refusals(tmp_path, text, variable, error, match):
    out = tmp_path / "ts.csv"
    out.write_text(text)

    with pytest.raises(error, match=match):
        import_csv_timeseries(out, variable=variable)


FILE_REFUSALS = [
    pytest.param(import_csv_timeseries, "absent.csv", (), FileNotFoundError, id="csv missing"),
    pytest.param(
        import_netcdf_fields, "absent.nc", (["head"],), FileNotFoundError, id="netcdf missing"
    ),
    pytest.param(
        import_netcdf_fields, "any.nc", (["not_a_field"],), UnknownFieldError, id="netcdf unknown"
    ),
    pytest.param(import_zarr_field, "absent.zarr", ("head",), FileNotFoundError, id="zarr missing"),
]


@pytest.mark.parametrize(("reader", "name", "args", "error"), FILE_REFUSALS)
def test_file_refusals(tmp_path, reader, name, args, error):
    with pytest.raises(error):
        reader(tmp_path / name, *args)
