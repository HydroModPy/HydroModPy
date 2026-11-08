"""The published discharge adds the drain budget when the network does not route the drainage."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from hydromodpy.core.scope import CATCHMENT
from hydromodpy.results.derive.catchment_aggregation import aggregate_catchment_timeseries
from hydromodpy.workflow.steps.run_outputs import _drainage_outside_routed
from tests._helpers.run_builders import runs

__all__ = ["runs"]


def _setup(runs) -> str:
    n_ts, n_cells = 3, 4
    sid = runs.open(
        solver="modflow6",
        n_cells=n_cells,
        n_layers=1,
        n_timesteps=n_ts,
        period_start=pd.Timestamp("2020-01-01", tz="UTC"),
        period_end=pd.Timestamp("2020-01-03", tz="UTC"),
    ).sim_id
    store = runs.store(sid)
    for t in range(n_ts):
        store.write_field(
            sid, "head", t, np.full((1, n_cells), 5.0), n_timesteps=n_ts if t == 0 else None
        )
        store.write_field(
            sid, "drain", t, np.full((1, n_cells), -0.5), n_timesteps=n_ts if t == 0 else None
        )
    idx = pd.date_range("2020-01-01", periods=n_ts, freq="D")
    store.write_timeseries(
        sid, "net:7", "ext_outflow", pd.Series([1.0, 2.0, 3.0], index=idx), unit="m3/s"
    )
    return sid


def test_a_network_that_routes_the_drainage_publishes_the_routed_series(runs) -> None:
    sid = _setup(runs)

    aggregate_catchment_timeseries(sid, runs.store(sid), drainage_outside_routed=False)

    ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
    np.testing.assert_allclose(ts.values, [1.0, 2.0, 3.0])


def test_a_network_that_keeps_the_drainage_out_publishes_routed_plus_drain(runs) -> None:
    sid = _setup(runs)

    aggregate_catchment_timeseries(sid, runs.store(sid), drainage_outside_routed=True)

    ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
    np.testing.assert_allclose(ts.values, [3.0, 4.0, 5.0])


def _model(payload, *, active: tuple[str, ...] = ("sfr",)) -> SimpleNamespace:
    return SimpleNamespace(boundaries=SimpleNamespace(active_ids=active), sfr={"net": payload})


def _ctx(payload, *, active: tuple[str, ...] = ("sfr",)) -> SimpleNamespace:
    setup = SimpleNamespace(model=_model(payload, active=active))
    return SimpleNamespace(state=SimpleNamespace(setup=setup))


def test_the_run_context_says_whether_the_drainage_is_routed() -> None:
    assert _drainage_outside_routed(_ctx({"route_drainage": False})) is True
    assert _drainage_outside_routed(_ctx(SimpleNamespace(route_drainage=False))) is True
    assert _drainage_outside_routed(_ctx({"route_drainage": True})) is False
    assert _drainage_outside_routed(_ctx({})) is False


def test_a_lake_without_a_network_keeps_the_drainage_outside_the_routed_series() -> None:
    assert _drainage_outside_routed(_ctx({}, active=("lake",))) is True
    model = SimpleNamespace(boundaries=SimpleNamespace(active_ids=("lake",)), sfr={})
    state = SimpleNamespace(setup=SimpleNamespace(model=model))
    assert _drainage_outside_routed(SimpleNamespace(state=state)) is True
    assert _drainage_outside_routed(SimpleNamespace(state=None)) is True
