"""A Boussinesq run stamps each stress period at its end, as MODFLOW does.

The transient history starts with the initial state, 0 s after the run start.
That snapshot closes no period. Written to the store it took timestep 0: the
lumped budget carried a zero-flux row there, one step ahead of MODFLOW 6 for
the same period, the catchment series began with a zero at the run start, and
the store held one slice more than the catalog's ``n_timesteps``, so
``Run.time_index`` fell back to rebuilt stamps and a point read lost its dates.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run.view import Run
from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
    aggregate_catchment_timeseries,
)
from hydromodpy.solver.boussinesq.calibration_extractors import (
    extract_discharge_history,
    extract_head_history_at_cells,
)
from hydromodpy.solver.boussinesq.export_payload import first_period_snapshot
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter

DAY_S = 86400.0
START = pd.Timestamp("2020-01-01")
PERIOD_ENDS = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-04"])


def _transient_payload() -> dict[str, np.ndarray]:
    """Return a history of three daily periods after the initial state."""
    return {
        "head_history_m": np.asarray([[5.0, 6.0], [5.1, 6.1], [5.2, 6.2], [5.3, 6.3]]),
        "snapshot_elapsed_seconds": np.asarray([0.0, 1.0, 2.0, 3.0]) * DAY_S,
        "step_end_elapsed_seconds": np.asarray([1.0, 2.0, 3.0]) * DAY_S,
        "period_lengths_seconds": np.full(3, DAY_S),
        "recharge_rate_history_m_s": np.zeros((4, 2)),
        "well_flux_history_m3_s": np.asarray([[0.0, 0.0], [-0.1, 0.0], [-0.2, 0.0], [-0.3, 0.0]]),
        "drainage_flux_history_m3_s": np.asarray([[0.0, 0.0], [0.0, 1.0], [0.0, 2.0], [0.0, 3.0]]),
        "z_top_m": np.asarray([10.0, 12.0]),
        "z_bottom_m": np.asarray([0.0, 1.0]),
        "cell_area_m2": np.asarray([100.0, 200.0]),
    }


@pytest.fixture
def extracted(tmp_path: Path):
    """Extract the transient history into a fresh catalog, registered with 3 periods."""
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    np.savez(output_dir / "_boussinesq_state_history.npz", **_transient_payload())
    catalog = Catalog(
        tmp_path / "workspace", persistence=PersistenceConfig(field_precision="exact")
    )
    sim_id = str(uuid4())
    registration = catalog.register_simulation(
        sim_id,
        project="test",
        solver="boussinesq",
        n_cells=2,
        n_layers=1,
        n_timesteps=3,
        period_start="2020-01-01",
        period_end="2020-01-04",
        time_unit="day",
    )
    if registration.zarr is not None:
        registration.zarr.close()
    BoussinesqOutputAdapter().extract(sim_id, output_dir, catalog, start_datetime=START)
    try:
        yield catalog, sim_id, output_dir
    finally:
        catalog.close()


def test_first_period_snapshot_skips_only_the_initial_state() -> None:
    assert first_period_snapshot(_transient_payload(), n_snapshots=4) == 1
    steady = {"snapshot_elapsed_seconds": np.asarray([0.0])}
    assert first_period_snapshot(steady, n_snapshots=1) == 0
    assert first_period_snapshot({"period_lengths_seconds": np.full(3, DAY_S)}, n_snapshots=4) == 1


def test_store_holds_one_slice_per_period_stamped_at_its_end(extracted) -> None:
    catalog, sim_id, _ = extracted
    with catalog.open_zarr(sim_id) as store:
        stamps = pd.DatetimeIndex(store.read_time())
        heads = np.asarray(store.root["head"][:]).reshape(3, 2)
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)

    pd.testing.assert_index_equal(stamps, PERIOD_ENDS, check_names=False)
    np.testing.assert_allclose(heads[:, 0], [5.1, 5.2, 5.3])
    # The run's calendar is the solver's own axis, and a point read keeps its dates.
    pd.testing.assert_index_equal(Run(sim_id, catalog).time_index, PERIOD_ENDS, check_names=False)


def test_lumped_budget_timestep_is_the_period_index(extracted) -> None:
    catalog, sim_id, _ = extracted
    budget = Run(sim_id, catalog).budget()
    well = budget[budget["component"] == "well"].sort_values("timestep")

    assert well["timestep"].tolist() == [0, 1, 2]
    np.testing.assert_allclose(well["flux_out"], [0.1, 0.2, 0.3])


def test_catchment_series_start_at_the_first_period_end(extracted) -> None:
    catalog, sim_id, _ = extracted
    aggregate_catchment_timeseries(sim_id, catalog)
    rows = catalog.connection.execute(
        "SELECT variable, time, value FROM timeseries WHERE sim_id = ? ORDER BY variable, time",
        [sim_id],
    ).fetchdf()

    for variable, expected in (("well_pumping", [-0.1, -0.2, -0.3]), ("discharge", [1, 2, 3])):
        series = rows[rows["variable"] == variable]
        times = pd.DatetimeIndex(series["time"]).tz_convert("UTC").tz_localize(None).as_unit("ns")
        pd.testing.assert_index_equal(times, PERIOD_ENDS, check_names=False)
        np.testing.assert_allclose(series["value"], expected)


def test_calibration_readers_return_dated_period_series(extracted) -> None:
    _, _, output_dir = extracted
    discharge = extract_discharge_history(output_dir, time_index=PERIOD_ENDS)
    heads = extract_head_history_at_cells(
        output_dir, station_cells={"P1": (0, 0, 1)}, time_index=PERIOD_ENDS
    )

    pd.testing.assert_index_equal(discharge.index, PERIOD_ENDS)
    np.testing.assert_allclose(discharge.to_numpy(), [1.0, 2.0, 3.0])
    pd.testing.assert_index_equal(heads["P1"].index, PERIOD_ENDS)
    np.testing.assert_allclose(heads["P1"].to_numpy(), [6.1, 6.2, 6.3])
