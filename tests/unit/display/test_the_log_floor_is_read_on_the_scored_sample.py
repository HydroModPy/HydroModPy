"""The log floor of the figure is the epsilon of the score, read on the scored sample.

The floor was one percent of the median of every observed station over the whole
series, before the scoring window. The score takes its epsilon on the pairs it
scores, so the two disagreed whenever the flow before the window differed from
the flow inside it.
"""

from __future__ import annotations

import pytest

from hydromodpy.display.figures.hydrograph_log_nse import HydrographLogNseFigure

from .test_hydrograph_log_nse import _line, _Run, _scored, mpl  # noqa: F401


def test_the_floor_is_read_on_the_samples_the_score_read(mpl) -> None:  # noqa: F811
    # The window holds the last two days, observed at 1.0; the whole series
    # has a median of 50.5.
    run = _scored(_Run([2.0, 3.0, 0.0, 0.0], observed=[100.0, 100.0, 1.0, 1.0]))
    fig, ax = mpl.subplots()

    HydrographLogNseFigure().render(run, ax)

    try:
        floor = _line(ax, "on the log floor").get_ydata()
        assert floor.tolist() == pytest.approx([0.01, 0.01])
    finally:
        mpl.close(fig)
