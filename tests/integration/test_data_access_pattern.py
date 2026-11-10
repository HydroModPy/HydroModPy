"""Integration coverage for the data access patterns of HydroModPy.

Validates that a sealed run, once indexed, exposes its results through:

- DuckDB SQL queries on ``simulations`` (with scientific metadata columns).
- Parquet files readable directly by ``pandas.read_parquet`` (with KV
  metadata).
- Zarr stores readable directly by ``xarray.open_zarr``.

The runs are written through the store of a claimed run directory and sealed,
as the pipeline does; no solver is invoked.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.record.manifest import MetricRow
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.fixtures_catalog import simulation_catalog
from tests._helpers.run_stores import open_run_store


def _seed_run(
    project: Path,
    *,
    name: str,
    objective: str,
    n_cells: int = 4,
    n_timesteps: int = 3,
) -> str:
    """Write, populate and seal one fake run under ``runs/<name>``; return its id."""
    store = open_run_store(
        project,
        name,
        n_cells=n_cells,
        n_layers=1,
        n_timesteps=n_timesteps,
        scientific_objective=objective,
        mesh_topology="structured_3d",
    )
    sid = store.sim_id
    store.write_run_environment(sid)

    vertices = np.array(
        [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
        dtype=float,
    )
    fnc = np.array([[0, 1, 4, 3], [1, 2, 4, 4], [0, 3, 4, 4], [1, 4, 3, 3]], dtype=int)
    store.write_mesh(
        sid,
        vertices=vertices,
        face_node_connectivity=fnc,
        z_interfaces=np.array([0.0, 10.0], dtype=float),
    )
    for t in range(n_timesteps):
        head = np.full((1, n_cells), float(t + 1), dtype="float64")
        store.write_field(sid, "head", t, head, n_timesteps=n_timesteps)

    ts = pd.Series(
        np.linspace(1.0, 5.0, n_timesteps),
        index=pd.date_range("2024-01-01", periods=n_timesteps, freq="D"),
    )
    store.write_timeseries(sid, station_id="outlet", variable="discharge", ts=ts, unit="m3/s")
    store.write_metric(
        sid, MetricRow(station="outlet", variable="discharge", metric="nse", value=0.7)
    )
    seal_completed(store)
    return sid


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Callable[..., tuple[Catalog, list[str]]]]:
    """Seal one run per ``name=objective`` in a project, index it; return the reader and ids."""
    with ExitStack() as readers:

        def _open(project: str, **objectives: str) -> tuple[Catalog, list[str]]:
            root = tmp_path / project
            sids = [
                _seed_run(root, name=name, objective=objective)
                for name, objective in objectives.items()
            ]
            return readers.enter_context(simulation_catalog(root)), sids

        yield _open


class TestRunsEnvironment:
    """Pattern 0: every sealed run has a populated runs_environment row."""

    def test_environment_is_captured(self, seeded):
        catalog, (sid,) = seeded("ml_p1", r1="exploratory")
        row = catalog.connection.execute(
            "SELECT python_version, hydromodpy_version, platform, hostname, "
            "memory_gb, cpu_info FROM runs_environment WHERE sim_id = ?",
            [sid],
        ).fetchone()
        assert row is not None, "runs_environment row missing"
        py_ver, hmp_ver, platform, hostname, _mem, cpu_info = row
        assert py_ver and py_ver.count(".") >= 2
        assert hmp_ver
        assert platform
        assert hostname
        assert cpu_info  # JSON-encoded dict, never empty


class TestDuckDBPattern:
    """Pattern 1: DuckDB SQL queries return scientific_objective per sim."""

    def test_sql_select_returns_scientific_metadata(self, seeded):
        catalog, _ = seeded("ml_p2a", r1="calibration", r2="validation")

        df = catalog.connection.execute(
            "SELECT sim_id, project, name, scientific_objective "
            "FROM simulations WHERE project = 'ml_p2a' ORDER BY name"
        ).fetchdf()

        assert len(df) == 2
        assert df["scientific_objective"].tolist() == ["calibration", "validation"]


class TestParquetPattern:
    """Pattern 2: per-sim Parquet files readable directly + KV metadata."""

    def test_parquet_with_kv_metadata(self, seeded):
        catalog, (sid,) = seeded("ml_p3", r1="exploratory")
        target = catalog.tables_dir_for(sid) / "timeseries.parquet"
        assert target.is_file()

        # Read via DuckDB, then via pandas: the file needs neither HydroModPy nor the index.
        df = catalog.connection.execute(f"SELECT * FROM read_parquet('{target}')").fetchdf()
        assert {"time", "value", "variable", "station_id"}.issubset(df.columns)
        assert len(df) > 0

        # The same file is also readable by pandas.
        df_pd = pd.read_parquet(target)
        assert {"time", "value", "variable", "station_id"}.issubset(df_pd.columns)

        rows = catalog.connection.execute(
            f"SELECT key, value FROM parquet_kv_metadata('{target}')"
        ).fetchall()
        kv = {row[0].decode(): row[1].decode() for row in rows}
        assert kv["sim_id"] == sid
        assert kv["project"] == "ml_p3"
        assert kv["scientific_objective"] == "exploratory"
        assert kv["hmp.schema_version"]
        assert kv["hydromodpy_version"]


class TestZarrPattern:
    """Pattern 3: per-sim Zarr stores read directly via xarray."""

    def test_run_to_xarray_batch(self, seeded):
        catalog, (sid,) = seeded("ml_p4", r1="exploratory")
        run = catalog[sid]

        ds = run.array.to_xarray_batch(("head",))
        assert "head" in ds
        assert ds["head"].dims == ("time", "layer", "cell")
        assert ds["head"].sizes["time"] == 3
        assert ds["head"].attrs.get("units") == "m"

    def test_run_to_xarray_batch_absent_field_raises(self, seeded):
        """A registered field that is neither stored nor derivable raises."""
        catalog, (sid,) = seeded("ml_p4b", r1="exploratory")
        run = catalog[sid]
        with pytest.raises(KeyError, match="not found"):
            run.array.to_xarray_batch(("concentration",))

    def test_run_to_xarray_batch_derives_virtual_field(self, seeded):
        """``watertable_depth`` is not persisted but is rebuilt from head + top."""
        catalog, (sid,) = seeded("ml_p4c", r1="exploratory")
        run = catalog[sid]
        ds = run.array.to_xarray_batch(("watertable_depth",))
        assert ds["watertable_depth"].sizes["time"] == 3
