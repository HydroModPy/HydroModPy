"""The redraw of a heads output lands its heads by the settings the run sealed.

A run scored under ``observed_rasterization = "heads"`` sealed where a head may
land: a snap radius and a minimum drained area. The redraw reads both back, so
a figure traces the map the trials scored, and a key the run left out takes
the criterion's default.

On the 5 x 3 valley of cells of 1 ha, the mapped axis starts 40 m north of the
centre of its head cell, which drains 5 ha; the cell below drains 10 ha.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from tests.unit.display._network_comparison_run import AXIS_COLUMN, cell, comparison_run


def _sealed_run(**heads):
    run = comparison_run()
    output = {
        "support": "network",
        "observed_network": "data.hydrography",
        "tau_specific_ratio": 0.0,
        "observed_rasterization": "heads",
        **heads,
    }
    run.config_snapshot = {"calibration": {"outputs": {"streams": output}}}
    return run


def _redraw(run):
    settings = network_criterion_settings(run)
    return network_comparison_from_run(
        run,
        tau_specific_ratio=settings.tau_specific_ratio,
        observed_rasterization=settings.observed_rasterization,
        heads_snap_radius_m=settings.heads_snap_radius_m,
        heads_min_drained_area_km2=settings.heads_min_drained_area_km2,
    )


def test_a_key_left_out_takes_the_default() -> None:
    settings = network_criterion_settings(_sealed_run())

    assert settings.observed_rasterization == "heads"
    assert settings.heads_snap_radius_m == STREAM_CRITERION_DEFAULTS.heads_snap_radius_m
    assert settings.heads_min_drained_area_km2 == (
        STREAM_CRITERION_DEFAULTS.heads_min_drained_area_km2
    )


def test_the_sealed_area_moves_the_landing_cell() -> None:
    comparison = _redraw(_sealed_run(heads_snap_radius=150.0, heads_min_drained_area_km2=0.06))

    trace = comparison.geometry.heads
    assert trace is not None
    assert trace.settings.min_drained_area_m2 == pytest.approx(6.0e4)
    assert trace.head_cell.tolist() == [cell(AXIS_COLUMN, 1)]
    assert trace.snap_distance_m[0] == pytest.approx(140.0)


def test_the_sealed_radius_loses_a_head_the_default_would_keep() -> None:
    kept = _redraw(_sealed_run(heads_snap_radius=50.0, heads_min_drained_area_km2=0.04))
    assert kept.geometry.heads is not None
    assert kept.geometry.heads.head_cell.tolist() == [cell(AXIS_COLUMN, 2)]

    with pytest.raises(ValueError, match="snap radius 30 m"):
        _redraw(_sealed_run(heads_snap_radius="30 m", heads_min_drained_area_km2=0.04))
