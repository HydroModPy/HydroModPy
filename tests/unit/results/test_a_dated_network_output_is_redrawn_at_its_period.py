"""A network output sealed with a date is redrawn at the state its trials scored.

``[calibration.outputs.<n>] time`` is ``"last"``, ``"first"`` or one date.
The trials read a date as the period ``[s, e)`` that holds it. The results
layer read only the two words and refused the date, so a promoted run whose
output named ``"2002-10-15"`` could not render its figures and the promotion
failed. The settings now resolve the date on the run's own periods, by the one
rule of :func:`hydromodpy.core.time.selection.resolve_state`.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.calibration.metrics.observable_scoring import network_state_period
from hydromodpy.display.figures._stream_comparison import compared_timestep, dated_title
from hydromodpy.results.derive.network_criterion_settings import network_criterion_settings

# 36 monthly periods, 2000-01 to 2002-12. October 2002 is period 33.
MONTHS = pd.date_range("2000-01-01", "2003-01-01", freq="MS")
OCTOBER_2002 = 33


def _run(time, *, edges=MONTHS, stamps=None, n_timesteps=None) -> SimpleNamespace:
    """A run-shaped object with one network output sealed at ``time``."""
    snapshot = {
        "calibration": {
            "outputs": {
                "seepage_network": {
                    "support": "network",
                    "observed_network": "data.hydrography",
                    "time": time,
                }
            }
        }
    }
    run = SimpleNamespace(sim_id="sim-x", config_snapshot=snapshot)
    if edges is not None:
        run.periods = SimpleNamespace(edges=pd.DatetimeIndex(edges))
    if stamps is not None:
        run.time_index = pd.DatetimeIndex(stamps)
    if n_timesteps is not None:
        run.n_timesteps = n_timesteps
    return run


@pytest.mark.parametrize("time", ["2002-10-15", "2002-10-01", datetime.date(2002, 10, 31)])
def test_a_date_reads_the_period_that_holds_it(time) -> None:
    settings = network_criterion_settings(_run(time))

    assert settings.timestep == OCTOBER_2002


def test_the_redraw_reads_the_state_the_trials_scored() -> None:
    for time in ("2000-01-01", "2001-06-30", "2002-10-15", "2003-01-01"):
        scored = network_state_period(time, MONTHS, n_periods=len(MONTHS) - 1)
        assert network_criterion_settings(_run(time)).timestep == scored


def test_the_words_keep_their_timestep() -> None:
    assert network_criterion_settings(_run("last")).timestep == -1
    assert network_criterion_settings(_run("first")).timestep == 0


def test_a_run_known_by_its_stamps_alone_reads_the_same_period() -> None:
    run = _run("2002-10-15", edges=None, stamps=MONTHS[1:])

    assert network_criterion_settings(run).timestep == OCTOBER_2002


def test_a_steady_run_over_its_window_reads_its_one_state() -> None:
    window = pd.DatetimeIndex(["2000-01-01", "2003-01-01"])

    assert network_criterion_settings(_run("2002-10-15", edges=window)).timestep == 0


def test_a_run_of_one_state_without_dates_serves_it() -> None:
    run = _run("2002-10-15", edges=None, n_timesteps=1)

    assert network_criterion_settings(run).timestep == 0


def test_a_date_the_run_does_not_hold_is_refused() -> None:
    with pytest.raises(ValueError, match="names no state of this run"):
        network_criterion_settings(_run("2004-01-15"))


@pytest.mark.parametrize("time", ["all", ["2001-10-15", "2002-10-15"], 3])
def test_what_no_trial_could_read_is_refused(time) -> None:
    with pytest.raises(ValueError, match="seepage_network"):
        network_criterion_settings(_run(time))


def test_the_stream_figures_draw_the_dated_period() -> None:
    run = _run("2002-10-15")

    assert compared_timestep(run) == OCTOBER_2002
    assert dated_title("Seepage network", run).endswith("October 2002")
