"""The numbers the special figures write, computed in results and checked by hand."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.results.derive.main_stem import main_stem
from hydromodpy.results.derive.porosity import pore_volume, turnover_years
from hydromodpy.results.derive.root_bracket import closing_root, final_bracket, sign_changes
from hydromodpy.results.session.acceptance import acceptable_cost, phase_returned
from hydromodpy.results.session.descriptor import BestTrial, CostInterval, ParameterWidth

TOPS = np.array([[10.0, 10.0], [5.0, 5.0], [0.0, 0.0]])  # layer tops and the last bottom


def test_the_pore_volume_weighs_porosity_by_saturated_thickness_and_area():
    # Layer 0 holds 3 m and 0 m of water, layer 1 holds 5 m and 3 m, so 0.1 * (300 + 500 + 600).
    head = np.array([[8.0, 3.0], [8.0, 3.0]])
    volume = pore_volume(np.full((2, 2), 0.1), head, TOPS,
                         np.array([100.0, 200.0]), np.array([True, True]))  # fmt: skip
    assert volume == pytest.approx(140.0)
    assert pore_volume(np.full((2, 2), 0.1), np.full((2, 2), 1e30), TOPS,
                       np.array([100.0, 200.0]), np.array([True, True])) == 0.0  # fmt: skip


def test_the_turnover_is_the_volume_over_the_mean_outflow_without_storage():
    rows = pd.DataFrame({"timestep": [0, 0, 1, 1], "flux_out": [-1.0, -9.0, -3.0, -5.0],
                         "component": ["drain", "storage_in", "drain", "storage_in"]})  # fmt: skip
    assert turnover_years(2.0 * 86400.0 * 365.25, rows) == pytest.approx(1.0)  # mean outflow 2 m3/s
    with pytest.raises(NothingThereError, match="no outflow"):
        turnover_years(1.0, rows.iloc[:0])


def test_the_final_bracket_is_the_narrowest_sign_change_and_the_root_its_closer_end():
    value = np.array([1.0, 8.0, 2.0, 4.0, 3.0])
    residual = np.array([5.0, 1.0, 3.0, -2.0, 1.0])  # sorted: changes at (3, 4) and (4, 8)
    assert sign_changes(value, residual) == [(3.0, 4.0), (4.0, 8.0)]
    assert final_bracket(value, residual) == (3.0, 4.0)
    assert closing_root(value, residual) == 3.0  # |1| < |-2|
    assert final_bracket(value, np.ones(5)) is None


def test_the_acceptable_cost_is_the_band_threshold_else_the_returned_cost_with_a_margin():
    best = BestTrial(trial=3, cost=2.0)
    banded = {"K": ParameterWidth(interval=CostInterval(threshold=0.5))}
    assert acceptable_cost(best, banded) == 0.5
    assert acceptable_cost(best, {}) == pytest.approx(2.3)
    assert acceptable_cost(BestTrial(trial=3), {}, 4.0) == pytest.approx(4.6)


def test_a_phase_gives_its_own_returned_trial_and_widths():
    phase = SimpleNamespace(name="two", best=BestTrial(trial=9), widths={"w": 1})
    one = SimpleNamespace(name="one", best=None, widths={})
    session = SimpleNamespace(phases=[one, phase], descriptor=SimpleNamespace(best="s", widths={}))
    assert phase_returned(session, "two") == (phase.best, {"w": 1})
    assert phase_returned(session, "one") == ("s", {})


def test_the_main_stem_follows_the_longest_path_and_gives_the_distance_to_the_outlet():
    reaches = pd.DataFrame({"network_id": "n", "reach": [1, 2, 3], "rlen": [100.0, 150.0, 100.0],
                            "downstream": [[3], [3], []]})  # fmt: skip
    stem, distance = main_stem(reaches)
    assert stem.tolist() == [1, 2] and distance.tolist() == [175.0, 50.0]
