"""The window the protocol writes on its transient stage reaches a two-bound network.

The window is the phase's, not the hydrograph block's, so a network output
scored in that phase over calendar years leaves the spin-up year out too. The
protocol's window is expanded from the dates of the run, validated as a phase
window, and handed to the metric route every trial takes.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibPhaseDecl,
    scoring_window_bounds,
)
from hydromodpy.calibration.metrics import solver_extract as _solver_extract
from hydromodpy.calibration.metrics.composite import build_metric_extractor
from hydromodpy.calibration.protocols import expand_calibration_protocol
from tests.unit.calibration.test_the_two_bound_mode_scores_the_years_of_its_window import (
    SPIN_UP_RUN,
    _fake_ctx,
    _output,
    _stack,
    _StackAdapter,
    _thresholds,
    bench,  # noqa: F401 (fixture)
    mapped,  # noqa: F401 (fixture)
)

pytest.importorskip("geopandas")

BLOCKS = [
    CalibObjectiveBlockDecl.model_validate(
        {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
    )
]


def _protocol_window(start: str, end: str, **protocol: object):
    """Return the ``(start, end)`` the protocol's transient stage scores between."""
    document = {
        "simulation": {"time": {"start_datetime": start, "end_datetime": end}},
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": {"name": "matching_hydrographic_network", **protocol},
            "parameters": {"K": {"bounds": [1e-8, 1e-2]}, "Sy": {"bounds": [1e-4, 0.5]}},
            "outputs": {"net": {"support": "network", "stream_geometry_path": "map.gpkg"}},
        },
    }
    transient = expand_calibration_protocol(document)["calibration"]["phases"][1]
    return scoring_window_bounds(CalibPhaseDecl.model_validate(transient).scoring_window)


def _components(monkeypatch, bench, mapped, window):  # noqa: F811
    ctx = _fake_ctx(bench, SPIN_UP_RUN)
    adapter = _StackAdapter(_stack(bench, _thresholds(3)))
    monkeypatch.setattr(_solver_extract, "resolve_flow_adapter", lambda _ctx: (adapter, ctx))
    metric_fn = build_metric_extractor(
        None,
        None,
        ctx,
        outputs={"net": _output(mapped)},
        objective_blocks=BLOCKS,
        scoring_window=window,
    )
    _, components = metric_fn(ctx)
    return components


def test_the_default_window_leaves_the_spin_up_year_out(monkeypatch, bench, mapped) -> None:  # noqa: F811
    window = _protocol_window("2000-01-01", "2002-12-31")

    scored = _components(monkeypatch, bench, mapped, window)

    assert scored["net.year_scored_y2000"] == 0.0
    assert scored["net.n_years_scored"] == 2.0
    assert scored["net.first_year_scored"] == 2001.0


def test_a_declared_window_still_wins(monkeypatch, bench, mapped) -> None:  # noqa: F811
    window = _protocol_window("2000-01-01", "2002-12-31", scoring_window={"start": "2000-01-01"})

    scored = _components(monkeypatch, bench, mapped, window)

    assert scored["net.year_scored_y2000"] == 1.0
    assert scored["net.n_years_scored"] == 3.0
