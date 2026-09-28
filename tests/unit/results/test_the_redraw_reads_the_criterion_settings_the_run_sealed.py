"""A run's network criterion settings are read back from the config it sealed.

A figure redraws what a trial scored, so it reads the settings of the network
output the run sealed under ``[calibration.outputs]``, and the defaults when
the run sealed none. The snapshot is the plain mapping a run stores: the
results layer never imports the calibration schema.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.stream_extent import DEFAULT_VISIBLE_FLOW
from hydromodpy.results.derive.network_criterion_settings import (
    DEFAULT_CRITERION_SETTINGS,
    DEFAULT_EXTENT_RULES,
    NetworkExtentRules,
    network_criterion_settings,
    network_outputs_of_run,
)


def _network(**fields) -> dict:
    return {"support": "network", "observed_network": "data.hydrography", **fields}


def _run(outputs: dict | None = None, **sections) -> SimpleNamespace:
    snapshot = dict(sections)
    if outputs is not None:
        snapshot["calibration"] = {"outputs": outputs}
    return SimpleNamespace(sim_id="sim-x", config_snapshot=snapshot)


def test_a_run_without_a_snapshot_reads_the_defaults() -> None:
    settings = network_criterion_settings(SimpleNamespace(sim_id="sim-x"))

    assert settings == DEFAULT_CRITERION_SETTINGS
    assert settings.tau_specific_ratio == STREAM_CRITERION_DEFAULTS.tau_specific_ratio
    assert settings.diagonal_neighbors is STREAM_CRITERION_DEFAULTS.diagonal_neighbors
    assert settings.extent_rules == DEFAULT_EXTENT_RULES
    assert settings.extent_rules.visible_flow == DEFAULT_VISIBLE_FLOW
    assert "the defaults" in settings.note()


def test_a_run_without_a_network_output_reads_the_defaults() -> None:
    run = _run({"head": {"support": "point", "variable": "head"}})

    assert network_outputs_of_run(run) == {}
    assert network_criterion_settings(run).output is None


def test_every_setting_the_output_sealed_is_read() -> None:
    run = _run(
        {
            "streams": _network(
                tau_specific_ratio=0.0,
                diagonal_neighbors=False,
                observed_rasterization="touch",
                weighting="area",
                observed_position_accuracy=25.0,
                time="first",
                extent={
                    "maximal_flowing_steps": 3,
                    "minimal_dry_steps": 2,
                    "year_quorum": 0.75,
                    "visible_flow": "2%",
                    "weights": {"minimal": 0.5, "maximal": 0.5},
                },
            )
        }
    )

    settings = network_criterion_settings(run)

    assert settings.output == "streams"
    assert settings.tau_specific_ratio == 0.0
    assert settings.diagonal_neighbors is False
    assert settings.observed_rasterization == "touch"
    assert settings.weighting == "area"
    assert settings.observed_position_accuracy_m == 25.0
    assert settings.timestep == 0
    assert settings.extent == NetworkExtentRules(
        maximal_flowing_steps=3, minimal_dry_steps=2, year_quorum=0.75, visible_flow="2%"
    )
    assert settings.note() == "criterion settings: calibration output 'streams'"


def test_a_key_the_output_left_out_takes_the_default() -> None:
    settings = network_criterion_settings(_run({"streams": _network(extent={})}))

    assert settings.tau_specific_ratio == STREAM_CRITERION_DEFAULTS.tau_specific_ratio
    assert settings.observed_rasterization == STREAM_CRITERION_DEFAULTS.observed_rasterization
    assert settings.weighting == "cell"
    assert settings.observed_position_accuracy_m is None
    assert settings.timestep == -1
    assert settings.extent == DEFAULT_EXTENT_RULES


def test_a_single_state_output_carries_no_extent_rules() -> None:
    settings = network_criterion_settings(_run({"streams": _network()}))

    assert settings.extent is None
    assert settings.extent_rules == DEFAULT_EXTENT_RULES


def test_a_positional_accuracy_with_its_unit_is_read_in_metres() -> None:
    run = _run({"streams": _network(observed_position_accuracy="0.05 km")})

    assert network_criterion_settings(run).observed_position_accuracy_m == pytest.approx(50.0)


def test_several_network_outputs_read_the_first_and_say_so() -> None:
    run = _run(
        {
            "first": _network(tau_specific_ratio=0.0),
            "head": {"support": "point", "variable": "head"},
            "second": _network(tau_specific_ratio=1.0e-2),
        }
    )

    settings = network_criterion_settings(run)

    assert settings.output == "first"
    assert settings.n_network_outputs == 2
    assert "one of 2 network outputs" in settings.note()
    assert network_criterion_settings(run, output="second").tau_specific_ratio == 1.0e-2


def test_an_output_the_run_did_not_seal_is_refused() -> None:
    with pytest.raises(ValueError, match="sealed no network output 'other'"):
        network_criterion_settings(_run({"streams": _network()}), output="other")


def test_a_sealed_value_no_trial_could_read_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown observed_rasterization"):
        network_criterion_settings(_run({"streams": _network(observed_rasterization="all")}))
    with pytest.raises(ValueError, match="carries no unit"):
        network_criterion_settings(_run({"streams": _network(extent={"visible_flow": "1"})}))


def test_the_snap_the_run_sealed_is_named() -> None:
    run = _run({"streams": _network()}, geographic={"snap_streams": {"mode": "apply"}})

    settings = network_criterion_settings(run)

    assert settings.snap is not None
    assert settings.note().endswith("snap_streams apply")


def test_the_scoring_window_the_run_sealed_is_read_and_named() -> None:
    run = _run({"streams": _network()})
    run.config_snapshot["calibration"]["scoring_window"] = {
        "start": "2002-01-01T00:00:00+01:00",
        "end": None,
    }

    settings = network_criterion_settings(run)

    assert settings.scoring_window == (pd.Timestamp("2002-01-01"), None)
    assert settings.note().endswith("scoring_window 2002-01-01 to open")


def test_a_window_with_both_bounds_open_is_no_window() -> None:
    run = _run({"streams": _network()})
    run.config_snapshot["calibration"]["scoring_window"] = {"start": None, "end": None}

    assert network_criterion_settings(run).scoring_window is None
    assert network_criterion_settings(_run({"streams": _network()})).scoring_window is None


def test_a_window_bound_that_is_not_a_date_is_refused() -> None:
    run = _run({"streams": _network()})
    run.config_snapshot["calibration"]["scoring_window"] = {"start": "spring", "end": None}

    with pytest.raises(ValueError, match="scoring_window.start 'spring' is not a date"):
        network_criterion_settings(run)
