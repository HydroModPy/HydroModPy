"""The recession cloud of a run that stores no discharge series is not applicable.

A steady run, or a run without a gauge, writes no ``discharge`` series at the
catchment. The figure says so with ``FigureNotApplicable``, the refusal a run's
figure list reads as "skip", rather than with the reader's ``KeyError``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.display.figures.recession_power_law import RecessionPowerLaw
from hydromodpy.display.subject import FigureNotApplicable


def test_a_run_without_the_series_is_not_applicable(mpl) -> None:
    def timeseries(variable, *, station):
        raise KeyError(f"No timeseries for sim=steady, station={station}, var={variable}")

    steady = SimpleNamespace(sim_id="steady", timeseries=timeseries)
    _, ax = mpl.subplots()

    with pytest.raises(FigureNotApplicable, match="stores no series 'discharge'"):
        RecessionPowerLaw().render(steady, ax)
