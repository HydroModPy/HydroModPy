"""The stream maps redraw the comparison with the settings the run was scored by.

``comparison_from_run`` reads the network output the run sealed, so a map of a
trial scored at ``tau = 0`` over a ``touch`` map, weighted by area, draws that
partition and not the defaults. A knob a caller names wins over the run's.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.display.figures import _stream_comparison
from hydromodpy.display.figures._stream_comparison import comparison_from_run
from tests.unit.display._network_comparison_run import AXIS_COLUMN, cell, comparison_run

SEALED = {
    "calibration": {
        "outputs": {
            "streams": {
                "support": "network",
                "observed_network": "data.hydrography",
                "tau_specific_ratio": 0.0,
                "diagonal_neighbors": False,
                "observed_rasterization": "touch",
                "weighting": "area",
                "observed_position_accuracy": 40.0,
                "time": "first",
            }
        }
    }
}


@pytest.fixture
def captured(monkeypatch):
    """Record the knobs the redraw is asked for, without building it."""
    calls: list[dict] = []

    def record(sim, **knobs):
        calls.append(knobs)
        return object()

    monkeypatch.setattr(_stream_comparison, "network_comparison_from_run", record)
    return calls


def test_a_run_that_sealed_no_output_is_redrawn_with_the_defaults(captured) -> None:
    comparison_from_run(comparison_run())

    assert captured == [
        {
            "tau_specific_ratio": STREAM_CRITERION_DEFAULTS.tau_specific_ratio,
            "diagonal_neighbors": STREAM_CRITERION_DEFAULTS.diagonal_neighbors,
            "timestep": -1,
            "observed_rasterization": STREAM_CRITERION_DEFAULTS.observed_rasterization,
            "weighting": "cell",
            "observed_position_accuracy_m": None,
        }
    ]


def test_a_run_that_sealed_an_output_is_redrawn_with_its_settings(captured) -> None:
    run = comparison_run()
    run.config_snapshot = SEALED
    comparison_from_run(run)

    assert captured == [
        {
            "tau_specific_ratio": 0.0,
            "diagonal_neighbors": False,
            "timestep": 0,
            "observed_rasterization": "touch",
            "weighting": "area",
            "observed_position_accuracy_m": 40.0,
        }
    ]


def test_a_knob_the_caller_names_wins_over_the_run(captured) -> None:
    run = comparison_run()
    run.config_snapshot = SEALED
    comparison_from_run(run, tau_specific_ratio=1.0e-3, diagonal_neighbors=True, timestep=-1)

    knobs = captured[0]
    assert knobs["tau_specific_ratio"] == 1.0e-3
    assert knobs["diagonal_neighbors"] is True
    assert knobs["timestep"] == -1
    assert knobs["observed_rasterization"] == "touch"


class _WeakRun(SimpleNamespace):
    """A run the memo can key on by identity, as it keys on a real one."""

    __eq__ = object.__eq__
    __hash__ = object.__hash__


def test_the_redraw_is_built_once_per_run_and_settings(captured) -> None:
    run = _WeakRun(**vars(comparison_run()))
    comparison_from_run(run)
    comparison_from_run(run)
    run.config_snapshot = SEALED
    comparison_from_run(run)

    assert len(captured) == 2


def _without_recharge():
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, 2)])
    run.has_field = lambda variable, **_: variable in {"release_flux", "topography"}
    return run


def test_the_sealed_threshold_reaches_the_partition() -> None:
    """A trial scored at tau = 0 needed no recharge, and neither does its redraw."""
    with pytest.raises(ValueError, match="persisted no recharge budget"):
        comparison_from_run(_without_recharge())

    run = _without_recharge()
    run.config_snapshot = SEALED
    comparison = comparison_from_run(run)

    assert comparison.tau_specific_ratio == 0.0
    assert sorted(int(i) for i in comparison.simulated.nonzero()[0]) == [
        cell(AXIS_COLUMN, row) for row in range(3)
    ]
