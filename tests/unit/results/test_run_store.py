"""The store of a run writes its directory alone and remembers its facts.

Every table carries the identity of the run in its footer; the facts a step
records (parameters, metrics, environment, inputs, grid) survive the close of
the store and the next open, so a later step or a later attempt finds them.
A simulated series needs a descriptor, and an observed one is not judged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.scope import OBSERVED, SIMULATED
from hydromodpy.core.tracking.input_file import TrackedFileEntry
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME
from hydromodpy.results.storage.run_facts import RunFacts, read_facts
from hydromodpy.results.storage.run_store import RunStore

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
        solution_key="c0ffee" * 10 + "c0ff",
        request_id="d00d" * 8,
        crs_wkt="EPSG:2154",
        crs_epsg=2154,
        bbox=(340000.0, 6790000.0, 360000.0, 6810000.0),
    )


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "runs" / "nancon_monthly"
    directory.mkdir(parents=True)
    return directory


def test_the_store_refuses_another_run(run_dir: Path) -> None:
    with RunStore.open(run_dir, facts=_facts()) as store, pytest.raises(KeyError):
        store.write_parameters("other-sim", [{"param_name": "K", "value": 1.0}])


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


def test_a_store_that_keeps_no_parquet_writes_no_table(run_dir: Path) -> None:
    from hydromodpy.core.config_kit.persistence import PersistenceConfig

    policy = PersistenceConfig(save_parquet=False)
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    with RunStore.open(run_dir, facts=_facts(), persistence=policy) as store:
        store.write_timeseries(SIM_ID, "P01", "head", pd.Series(np.ones(3), index=index))
    assert not (run_dir / TABLES_DIRNAME).exists()


def test_the_field_store_shares_the_value_digests_of_the_facts(run_dir: Path) -> None:
    with RunStore.open(run_dir, facts=_facts()) as store:
        handle = store.open_zarr(SIM_ID)
        try:
            assert handle.field_digests is store.facts.field_digests
            handle.field_digests["head"] = {"0": "ab" * 32}
        finally:
            handle.close()

    assert read_facts(run_dir).field_digests == {"head": {"0": "ab" * 32}}


UNKNOWN_SERIES = "lake_volume_change"


def _write_one(store: RunStore, method: str, source: str) -> None:
    """Write one series of three steps named ``UNKNOWN_SERIES`` through ``method``."""
    index = pd.date_range("2020-01-01", periods=3, freq="D", tz="UTC")
    if method == "write_timeseries":
        series = pd.Series(np.ones(3), index=index)
        store.write_timeseries(SIM_ID, "P01", UNKNOWN_SERIES, series, source=source)
        return
    columns = {
        "station_id": "P01",
        "variable": UNKNOWN_SERIES,
        "timestep": np.arange(3, dtype="int64"),
        "time": index,
        "value": np.ones(3),
        "unit": "m3",
        "source": source,
    }
    if method == "write_timeseries_columns":
        store.write_timeseries_columns(SIM_ID, columns)
        return
    records = [
        {**columns, "timestep": step, "time": index[step], "value": 1.0} for step in range(3)
    ]
    store.write_timeseries_batch(SIM_ID, records)


SERIES_METHODS = ("write_timeseries", "write_timeseries_batch", "write_timeseries_columns")


@pytest.mark.parametrize("method", SERIES_METHODS)
def test_a_simulated_series_without_a_descriptor_is_refused(run_dir: Path, method: str) -> None:
    with RunStore.open(run_dir, facts=_facts()) as store:
        with pytest.raises(DataContractViolation, match="has no descriptor"):
            _write_one(store, method, SIMULATED)
    assert not (run_dir / TABLES_DIRNAME / f"timeseries{PARQUET_FILE_SUFFIX}").exists()


def test_a_columnar_payload_judges_only_its_simulated_rows(run_dir: Path) -> None:
    index = pd.date_range("2020-01-01", periods=2, freq="D", tz="UTC")
    columns = {
        "station_id": "P01",
        "variable": np.array([UNKNOWN_SERIES, "head"], dtype=object),
        "timestep": np.zeros(2, dtype="int64"),
        "time": index,
        "value": np.ones(2),
        "unit": "m",
        "source": np.array([OBSERVED, SIMULATED], dtype=object),
    }
    with RunStore.open(run_dir, facts=_facts()) as store:
        store.write_timeseries_columns(SIM_ID, columns)
        columns["source"] = np.array([SIMULATED, SIMULATED], dtype=object)
        with pytest.raises(DataContractViolation, match=repr(UNKNOWN_SERIES)):
            store.write_timeseries_columns(SIM_ID, columns)
