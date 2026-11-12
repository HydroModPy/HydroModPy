"""Discharge (m3/s) the catchment publishes at its outlet.

It is the routed series of the river network. When the network does not route
the drainage, the drain budget (m3/s) is added to it.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.scope import CATCHMENT
from hydromodpy.results.derive.catchment_aggregation import aggregate_catchment_timeseries
from hydromodpy.workflow.steps.run_outputs import _drainage_outside_routed
from tests._helpers.run_builders import runs

__all__ = ["runs"]

N_TIMESTEPS = 3
N_CELLS = 4
ROUTED = [1.0, 2.0, 3.0]  # m3/s, series of the river network "net:7"


def run_with_a_routed_network(runs) -> str:
    sid = runs.open(
        solver="modflow6",
        n_cells=N_CELLS,
        n_layers=1,
        n_timesteps=N_TIMESTEPS,
        period_start=pd.Timestamp("2020-01-01", tz="UTC"),
        period_end=pd.Timestamp("2020-01-03", tz="UTC"),
    ).sim_id
    store = runs.store(sid)
    for t in range(N_TIMESTEPS):
        first = N_TIMESTEPS if t == 0 else None
        store.write_field(sid, "head", t, np.full((1, N_CELLS), 5.0), n_timesteps=first)
        store.write_field(sid, "drain", t, np.full((1, N_CELLS), -0.5), n_timesteps=first)
    days = pd.date_range("2020-01-01", periods=N_TIMESTEPS, freq="D")
    store.write_timeseries(sid, "net:7", "ext_outflow", pd.Series(ROUTED, index=days), unit="m3/s")
    return sid


@pytest.mark.parametrize(
    ("drainage_outside_routed", "expected"),
    [
        pytest.param(False, [1.0, 2.0, 3.0], id="routed series alone"),
        pytest.param(True, [3.0, 4.0, 5.0], id="routed plus drain"),  # 4 cells x 0.5 m3/s
    ],
)
def test_published_discharge(runs, drainage_outside_routed, expected) -> None:
    sid = run_with_a_routed_network(runs)

    aggregate_catchment_timeseries(
        sid, runs.store(sid), drainage_outside_routed=drainage_outside_routed
    )

    ts = runs.store(sid).query_timeseries(sid, CATCHMENT, "discharge")
    np.testing.assert_allclose(ts.values, expected)


def solver_run(payload, *, active: tuple[str, ...] = ("sfr",)) -> SimpleNamespace:
    boundaries = SimpleNamespace(active_ids=active)
    return SimpleNamespace(model=SimpleNamespace(boundaries=boundaries, sfr={"net": payload}))


OUTSIDE_ROUTED = [
    pytest.param({"route_drainage": False}, True, id="mapping, not routed"),
    pytest.param(SimpleNamespace(route_drainage=False), True, id="object, not routed"),
    pytest.param({"route_drainage": True}, False, id="routed"),
    pytest.param({}, False, id="no key"),
]


@pytest.mark.parametrize(("payload", "outside"), OUTSIDE_ROUTED)
def test_drainage_outside_routed(payload, outside) -> None:
    assert _drainage_outside_routed(solver_run(payload)) is outside
