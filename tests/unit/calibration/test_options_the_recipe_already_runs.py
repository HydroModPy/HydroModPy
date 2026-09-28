"""An option written the way the recipe runs it anyway has not moved off the recipe.

Example 04 writes ``sweep_points = 7``, ``steady_tolerance = 0.01`` and the
spin-up window out, so the file can be read beside the paper. The bisection's own
defaults are seven points and one per cent, and the protocol leaves the first
year out on its own: ``--check`` listed all three as moved.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.calibration.config import CalibrationProtocolDecl
from hydromodpy.calibration.optim.method_config import (
    default_relative_precision,
    method_options_are_its_defaults,
)
from hydromodpy.calibration.protocols import options_the_recipe_already_runs

NAME = "matching_hydrographic_network"
TIME = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31")
PLAIN = SimpleNamespace(scoring_window=None, warmup_periods=None)


def _same(calibration=PLAIN, **options: object) -> frozenset[str]:
    declared = CalibrationProtocolDecl.model_validate({"name": NAME, **options})
    return options_the_recipe_already_runs(declared, calibration, TIME)


def test_the_method_s_own_defaults_written_out_run_as_the_recipe() -> None:
    assert _same(steady_method_options={"sweep_points": 7}) == {"steady_method_options"}
    assert _same(steady_method_options={"sweep_points": 7, "rel_tol": 0.01}) == {
        "steady_method_options"
    }


def test_another_value_is_away_from_the_recipe() -> None:
    assert _same(steady_method_options={"sweep_points": 5}) == frozenset()


def test_the_bisection_s_own_precision_written_out_runs_as_the_recipe() -> None:
    assert _same(steady_tolerance=0.01) == {"steady_tolerance"}
    assert _same(steady_tolerance=0.05) == frozenset()


def test_a_precision_the_simplex_reads_as_a_width_is_always_a_choice() -> None:
    """Nelder-Mead writes its xatol from the bounds: no default equals a written number."""
    assert _same(transient_tolerance=0.05) == frozenset()


def test_the_spin_up_window_written_out_runs_as_the_recipe() -> None:
    assert _same(scoring_window={"start": "2001-01-01"}) == {"scoring_window"}
    assert _same(scoring_window={"start": "2001-01-01", "end": "2002-12-31"}) == {"scoring_window"}


def test_another_window_is_away_from_the_recipe() -> None:
    assert _same(scoring_window={"start": "2002-06-01"}) == frozenset()
    assert _same(scoring_window={"start": "2001-01-01", "end": "2002-06-30"}) == frozenset()


def test_the_window_is_the_recipe_s_only_when_calibration_bounds_nothing() -> None:
    bounded = SimpleNamespace(scoring_window={"start": "2000-06-01"}, warmup_periods=None)

    assert _same(bounded, scoring_window={"start": "2001-01-01"}) == frozenset()


def test_options_equal_to_the_method_s_defaults_are_recognised() -> None:
    assert method_options_are_its_defaults("bisection", {"sweep_points": 7})
    assert not method_options_are_its_defaults("bisection", {"sweep_points": 0})
    assert not method_options_are_its_defaults("bisection", {"points_per_dim": 3})
    assert not method_options_are_its_defaults("a_plugin_engine", {"x": 1})


def test_only_a_relative_stopping_option_has_a_default_precision() -> None:
    assert default_relative_precision("bisection", {}) == 0.01
    assert default_relative_precision("bisection", {"rel_tol": 0.02}) is None
    assert default_relative_precision("scipy_nelder_mead", {}) is None
    assert default_relative_precision("optuna", {}) is None
