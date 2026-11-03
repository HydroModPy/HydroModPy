"""The store of a run writes its directory alone and remembers its facts.

Every table carries the identity of the run in its footer; the facts a step
records (parameters, metrics, environment, inputs, grid) survive the close of
the store and the next open, so a later step or a later attempt finds them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from hydromodpy.core.tracking.input_file import TrackedFileEntry
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.manifest import RUNTIME_VARIABLE, MetricRow
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME
from hydromodpy.results.storage.parquet_io import read_kv_metadata
from hydromodpy.results.storage.run_facts import RunFacts, facts_path, read_facts
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.metric_rows import headline_row

SIM_ID = "9a4f0000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 15, 8, 2, 11, tzinfo=UTC)


def _facts(name: str = "nancon_monthly") -> RunFacts:
    return RunFacts(
        sim_id=SIM_ID,
        name=name,
        case_id=name,
        project="demo",
        attempt=1,
        attempt_id="7c1e" * 8,
        created_at=NOW,
        started_at=NOW,
        solver="modflow6",
        crs_wkt="EPSG:2154",
        crs_epsg=2154,
        bbox=(340000.0, 6790000.0, 360000.0, 6810000.0),
    )


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "runs" / "nancon_monthly"
    directory.mkdir(parents=True)
    return directory


def test_the_first_open_writes_the_facts_and_a_later_open_reads_them(run_dir: Path) -> None:
    with RunStore.open(run_dir, facts=_facts()) as store:
        store.write_parameters(SIM_ID, [{"param_name": "K", "value": 1e-5, "unit": "m/s"}])
    assert facts_path(run_dir).is_file()

    with RunStore.open(run_dir) as store:
        assert store.sim_id == SIM_ID
        assert [(p.name, p.value, p.origin) for p in store.facts.parameters] == [
            ("K", 1e-5, "declared")
        ]


def test_the_store_refuses_another_run(run_dir: Path) -> None:
    with RunStore.open(run_dir, facts=_facts()) as store, pytest.raises(KeyError):
        store.write_parameters("other-sim", [{"param_name": "K", "value": 1.0}])


def test_every_table_carries_the_identity_and_the_run_footer(run_dir: Path) -> None:
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    with RunStore.open(run_dir, facts=_facts()) as store:
        store.write_timeseries(SIM_ID, "P01", "head", pd.Series(np.ones(3), index=index))
        store.write_budgets(
            SIM_ID, [{"timestep": 0, "component": "recharge", "flux_in": 1.0, "flux_out": 0.0}]
        )
        store.write_mass_balance(SIM_ID, 0, 10.0, 9.5, 5.0)
        store.write_metric(
            SIM_ID, MetricRow(station="P01", variable="head", metric="nse", value=0.8)
        )
        store.write_provenance(SIM_ID, "dem", "ign_geoplateforme_dem", np.ones(4))

    tables = run_dir / TABLES_DIRNAME
    names = sorted(path.name for path in tables.iterdir())
    assert names == [
        f"budgets{PARQUET_FILE_SUFFIX}",
        f"mass_balance{PARQUET_FILE_SUFFIX}",
        f"metrics{PARQUET_FILE_SUFFIX}",
        f"provenance{PARQUET_FILE_SUFFIX}",
        f"timeseries{PARQUET_FILE_SUFFIX}",
    ]
    for name in names:
        identity = read_identity_from(tables / name)
        assert identity is not None and identity.sim_id == SIM_ID and identity.label is None
        footer = read_kv_metadata(tables / name)
        assert footer["project"] == "demo"
        assert footer["hmp.bbox_crs"] == "EPSG:2154"
        assert "geospatial_lat_min" in footer


def test_a_second_write_merges_on_the_key(run_dir: Path) -> None:
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    with RunStore.open(run_dir, facts=_facts()) as store:
        store.write_timeseries(SIM_ID, "P01", "head", pd.Series(np.ones(3), index=index))
        store.write_timeseries(SIM_ID, "P01", "head", pd.Series(np.full(3, 2.0), index=index))
        series = store.query_timeseries(SIM_ID, "P01", "head")
    assert series.tolist() == [2.0, 2.0, 2.0]


def test_the_mass_balance_records_the_worst_discrepancy_as_a_check(run_dir: Path) -> None:
    with RunStore.open(run_dir, facts=_facts()) as store:
        store.write_mass_balance(SIM_ID, 0, 10.0, 9.5, 0.5)
        store.write_mass_balance(SIM_ID, 1, 10.0, 9.0, -2.0)
    assert read_facts(run_dir).budget_pct == 2.0


def test_the_grid_and_the_tracked_inputs_land_in_the_facts(run_dir: Path, tmp_path: Path) -> None:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"dem")
    with RunStore.open(run_dir, facts=_facts(), workspace=tmp_path) as store:
        store.update_simulation_grid_metadata(
            SIM_ID, n_cells=4148, n_layers=2, mesh_hash="abc", mesh_topology="polygon"
        )
        written = store.register_tracked_files(
            SIM_ID,
            [
                TrackedFileEntry(
                    role="dem",
                    category="raster",
                    original_path="dem.tif",
                    canonical_path=dem,
                    portable=True,
                )
            ],
        )
        store.write_geographic_metadata(SIM_ID, {"catch_area": 65.2, "x_outlet": 350000.0})
    assert written == 1
    facts = read_facts(run_dir)
    assert (facts.n_cells, facts.n_layers, facts.mesh_hash, facts.mesh_topology) == (
        4148,
        2,
        "abc",
        "polygon",
    )
    assert facts.tracked_inputs[0].path == "dem.tif"
    assert facts.tracked_inputs[0].sha256
    assert facts.geographic_metadata == {"catch_area": 65.2, "x_outlet": 350000.0}


def test_a_metric_written_twice_keeps_the_last_value_of_each_period(run_dir: Path) -> None:
    with RunStore.open(run_dir, facts=_facts()) as store:
        for window, value in (("metrics", 0.5), ("metrics", 0.8), ("validation", 0.2)):
            store.write_metric(
                SIM_ID, headline_row("nse", value, window_name=window, window_role="validation")
            )
        store.write_runtime_metric(SIM_ID, "flow_main", "solve_time_s", 12.5)
    rows = read_facts(run_dir).metrics
    assert [(row.window_name, row.value) for row in rows if not row.is_runtime] == [
        ("metrics", 0.8),
        ("validation", 0.2),
    ]
    table = pq.read_table(run_dir / TABLES_DIRNAME / f"metrics{PARQUET_FILE_SUFFIX}").to_pandas()
    kept = table.set_index(["window_name", "metric"])["value"]
    assert (kept[("metrics", "nse")], kept[("validation", "nse")]) == (0.8, 0.2)
    runtime = table[table["variable"] == RUNTIME_VARIABLE].iloc[0]
    assert (runtime["metric"], runtime["value"], runtime["window_name"]) == (
        "solve_time_s",
        12.5,
        None,
    )


def test_a_store_that_keeps_no_parquet_writes_no_table(run_dir: Path) -> None:
    from hydromodpy.core.config_kit.persistence import PersistenceConfig

    policy = PersistenceConfig(save_parquet=False)
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    with RunStore.open(run_dir, facts=_facts(), persistence=policy) as store:
        store.write_timeseries(SIM_ID, "P01", "head", pd.Series(np.ones(3), index=index))
    assert not (run_dir / TABLES_DIRNAME).exists()
