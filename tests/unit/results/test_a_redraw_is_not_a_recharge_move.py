"""A figure redraw reads the recharge its trials scored with.

The by-hand Nancon calibration scores the network in a steady phase, then
promotes a transient run whose first period is a steady spin-up. The trials
read the rate the forcing gives each period (9.075e-9 m/s on average). The
redraw read the budget the solver wrote, where the spin-up period holds the
record mean in place of January (8.656e-9), so the figures cut the network at
another threshold than the one scored, and the check logged "The mean recharge
moved" though the forcing never changed. Both now average the forcing rates by
one rule, the redraw rebuilding them from the station forcing the run stores.
A real change of data or of window still warns.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.calibration.observations.network_geometry import mean_recharge_m_s
from hydromodpy.core import stream_geometry
from hydromodpy.core.stream_geometry import build_network_geometry
from hydromodpy.core.stream_recharge import criterion_mean_recharge, forcing_period_rates
from hydromodpy.core.units import factor_to_m_per_s
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NX,
    NY,
    cell,
    comparison_run,
)

MM_PER_DAY = factor_to_m_per_s("mm/day")
CELL_AREA_M2 = CELL_M * CELL_M

# Three monthly samples in mm/day, stamped at the end of their month as the
# Nancon file is, and the three monthly periods of the run.
FORCING_MM_D = pd.Series(
    [2.09, 0.76, 0.5], index=pd.DatetimeIndex(["2000-01-31", "2000-02-29", "2000-03-31"])
)
EDGES = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])
RATES_M_S = FORCING_MM_D.to_numpy() * MM_PER_DAY
RECORD_MEAN_M_S = float(RATES_M_S.mean())


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test starts as a new process: no recharge seen."""
    monkeypatch.setattr(stream_geometry, "_last_mean_recharge", None)


def _moves(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "mean recharge moved" in r.getMessage()]


def _trial_build(model) -> None:
    """Build the criterion geometry as a trial does, from its built model."""
    run = comparison_run()
    observed = np.zeros(NX * NY, dtype=bool)
    observed[[cell(AXIS_COLUMN, row) for row in range(NY)]] = True
    build_network_geometry(
        topography=run.mesh.topography,
        face_node_connectivity=run.mesh.face_node_connectivity,
        vertices=run.mesh.vertices,
        observed=observed,
        cell_area_m2=np.full(NX * NY, CELL_AREA_M2),
        mean_recharge_m_s=mean_recharge_m_s(model),
        tau_specific_ratio=1e-4,
    )


def _promoted_run(tmp_path, *, forcing_mm_d=FORCING_MM_D, edges=EDGES, store=True):
    """A promoted transient run: a spin-up budget, and the forcing it stored."""
    budget = [RECORD_MEAN_M_S, *RATES_M_S[1:]]
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    fields = {"release_flux": run.field("release_flux"), "topography": run.field("topography")}
    run.n_timesteps = len(budget)
    run.periods = SimpleNamespace(edges=edges)

    def field(variable, *, timestep=-1, **_):
        if variable == "recharge":
            return np.full(NX * NY, budget[timestep] * CELL_AREA_M2)
        return fields[variable]

    run.field = field
    if store:
        path = tmp_path / "fields.zarr"
        SimulationZarr.create(path, n_cells=0, n_layers=1).close()
        writer = SimulationZarr(path)
        writer.write_forcing_timeseries(
            "recharge",
            "NANCON",
            forcing_mm_d.index.values,
            forcing_mm_d.to_numpy(),
            unit="mm/day",
        )
        writer.close()
        run._catalog.open_zarr = lambda sim_id: SimulationZarr(path)
    return run


def test_a_period_takes_the_mean_of_its_samples_or_carries_the_last() -> None:
    samples = pd.Series(
        [1.0, 3.0, -2.0], index=pd.DatetimeIndex(["2000-01-05", "2000-01-20", "2000-03-10"])
    )
    edges = pd.DatetimeIndex(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])

    assert forcing_period_rates(samples, edges).tolist() == [2.0, 3.0, 0.0]
    assert criterion_mean_recharge([np.array([1.0, np.nan]), 3.0]) == 2.0


def test_the_steady_and_transient_models_hold_the_record_mean() -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))
    transient = SimpleNamespace(recharge=pd.Series(RATES_M_S, index=EDGES[:-1]))

    assert mean_recharge_m_s(steady) == pytest.approx(RECORD_MEAN_M_S, rel=1e-12)
    assert mean_recharge_m_s(transient) == pytest.approx(RECORD_MEAN_M_S, rel=1e-12)


def test_the_redraw_reads_the_recharge_the_trials_scored(tmp_path, caplog) -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))

    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        _trial_build(steady)
        comparison = network_comparison_from_run(_promoted_run(tmp_path))

    assert comparison.geometry.mean_recharge_m_s == pytest.approx(RECORD_MEAN_M_S, rel=1e-9)
    assert _moves(caplog) == []


def test_other_data_still_warns(tmp_path, caplog) -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))

    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        _trial_build(steady)
        network_comparison_from_run(_promoted_run(tmp_path, forcing_mm_d=FORCING_MM_D * 0.8))

    assert len(_moves(caplog)) == 1


def test_another_window_still_warns(tmp_path, caplog) -> None:
    steady = SimpleNamespace(recharge=pd.Series([RECORD_MEAN_M_S]))

    with caplog.at_level(logging.INFO, logger=stream_geometry.__name__):
        _trial_build(steady)
        network_comparison_from_run(_promoted_run(tmp_path, edges=EDGES[1:]))

    assert len(_moves(caplog)) == 1


def test_a_run_without_a_stored_forcing_reads_its_budget(tmp_path) -> None:
    comparison = network_comparison_from_run(_promoted_run(tmp_path, store=False))

    spin_up_budget = (RECORD_MEAN_M_S + RATES_M_S[1:].sum()) / 3
    assert comparison.geometry.mean_recharge_m_s == pytest.approx(spin_up_budget, rel=1e-9)


def _monthly_window(start: str, end: str):
    from hydromodpy.core.time import ResolvedSimulationTimeWindow

    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )


@pytest.mark.parametrize(
    "samples",
    [
        # The example 04 file, monthly, stamped at each month's end.
        pd.Series(
            [2.088043, 0.760928, 0.551107, 0.642604, 0.0, 1.2],
            index=pd.to_datetime(
                ["2000-01-31", "2000-02-29", "2000-03-31", "2000-04-30", "2000-05-31", "2000-06-30"]
            ),
        ),
        # A daily series with a gap: April has no sample and carries March's last one.
        pd.Series(
            [1.0, 3.0, 2.0, 5.0, 4.0],
            index=pd.to_datetime(
                ["2000-01-10", "2000-01-20", "2000-02-15", "2000-03-31", "2000-05-02"]
            ),
        ),
    ],
)
def test_the_criterion_rates_are_the_rates_the_model_is_forced_with(samples: pd.Series) -> None:
    """Two copies of one rule: the solver forcing and the criterion must not drift apart."""
    from hydromodpy.core.time import build_simulation_time_boundaries
    from hydromodpy.physics.forcing.time_alignment import align_forcing_series_to_simulation_window

    window = _monthly_window("2000-01-01", "2000-05-31")
    forced = align_forcing_series_to_simulation_window(samples, simulation_window=window)
    edges = build_simulation_time_boundaries(window)

    rates = forcing_period_rates(samples, edges)

    assert rates == pytest.approx(np.maximum(forced.to_numpy(dtype=float), 0.0))
