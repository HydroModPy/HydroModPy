"""B11: the protocol's block route scores the same as the old single-metric one.

Before B11 the transient stage of ``matching_hydrographic_network`` wrote its
cost as ``variable`` + ``objective``, read by :class:`StationScorer`. After
B11 it writes a ``point`` output that ``observes`` the gauge and a block,
read by :class:`ObservableScorer` / ``ConfigBlockObjective``. Both call the
same low-level alignment (``align_observed_simulated``) and the same
registered criterion (``hydromodpy.calibration.criteria.series``), so the
same simulated series against the same observed record has to cost the same
on both routes.

Measured on a real Nancon run before this test was written: bit-identical,
0.07916512462058523 both ways (example 04, session
20260923-142058-scipy_nelder_mead-42cbb8b8, trial 4, K and Sy frozen at its
values). This pins the same property on a synthetic series, deterministically
and without a solver.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputPoint
from hydromodpy.calibration.metrics.observable_scoring import ObservableScorer, StationScorer
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.core.contracts.observables import ObservableResult
from hydromodpy.core.time.period_aggregation import period_edges

STATION = "NANCON"
TIMES = pd.date_range("2001-01-31", periods=24, freq="ME")
BOUNDARIES = period_edges(TIMES, start=pd.Timestamp("2000-12-31"))
OBSERVED = pd.Series(np.linspace(0.2, 5.0, 24), index=TIMES, name=STATION)
SIMULATED = (OBSERVED * 0.8 + 0.1).to_numpy()


def test_the_block_route_and_the_single_metric_route_cost_the_same() -> None:
    single = StationScorer(
        "discharge",
        "nse_log",
        [ObservedSeries(station_id=STATION, variable="discharge", series=OBSERVED)],
    )
    single_cost, single_components = single.score(
        {
            STATION: ObservableResult(
                request_id=STATION, values=SIMULATED, units="m3 s-1", times=TIMES
            )
        },
        boundaries=BOUNDARIES,
    )

    output = CalibOutputPoint.model_validate(
        {"variable": "discharge", "support": "point", "observes": STATION}
    )
    block = CalibObjectiveBlockDecl(name="hydrograph", metric="nse_log", uses_outputs=["gauge"])
    composite = ObservableScorer({"gauge": output}, [block], observed_records={"gauge": OBSERVED})
    block_cost, block_components = composite.score(
        {
            "gauge": ObservableResult(
                request_id="gauge", values=SIMULATED, units="m3 s-1", times=TIMES
            )
        },
        boundaries=BOUNDARIES,
    )

    assert block_cost == single_cost
    assert single_components[f"cost:nse_log@{STATION}"] == single_cost
    assert block_components["hydrograph.raw_cost"] == single_cost
    # One edge sample does not close a period on this boundary set; both
    # routes read the same alignment function and agree on how many do.
    assert block_components["gauge.n_paired"] == 23.0
