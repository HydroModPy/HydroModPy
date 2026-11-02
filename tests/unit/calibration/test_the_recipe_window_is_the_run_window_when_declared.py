"""The window the recipe runs is ``[metrics] window`` once the file declares one.

Since the protocol writes ``[metrics] window`` on its transient stage
(d0390cb68), the first year after the start is the recipe's window only for a
file without ``[metrics] window``. ``hmp config check`` still compared a
protocol ``scoring_window`` with the spin-up year, and called the spin-up window
"written as the recipe runs it" while the recipe now scores the run window.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.calibration.config import CalibrationProtocolDecl
from hydromodpy.calibration.protocols import options_the_recipe_already_runs
from hydromodpy.config.metrics_config import MetricsWindow

NAME = "matching_hydrographic_network"
TIME = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31")
PLAIN = SimpleNamespace(scoring_window=None, warmup_periods=None)
RUN_WINDOW = MetricsWindow.model_validate({"start": "2001-01-01", "end": "2002-06-30"})


def _same(window: dict, metrics_window=RUN_WINDOW) -> frozenset[str]:
    declared = CalibrationProtocolDecl.model_validate({"name": NAME, "scoring_window": window})
    return options_the_recipe_already_runs(declared, PLAIN, TIME, metrics_window=metrics_window)


def test_the_spin_up_window_is_away_from_a_recipe_that_scores_the_run_window() -> None:
    assert _same({"start": "2001-01-01"}) == frozenset()
    assert _same({"start": "2001-01-01", "end": "2002-12-31"}) == frozenset()


def test_the_run_window_written_out_runs_as_the_recipe() -> None:
    assert _same({"start": "2001-01-01", "end": "2002-06-30"}) == {"scoring_window"}


def test_without_a_run_window_the_spin_up_year_is_still_the_recipe_s() -> None:
    assert _same({"start": "2001-01-01"}, metrics_window=None) == {"scoring_window"}
