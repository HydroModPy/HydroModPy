"""A series figure titles its curve by the outlet it draws, never by the internal station id.

Measured on the example 04 gallery, titles ended with ``@ catchment``, the id a
run stores its outlet series under.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures.duration_curve import DurationCurveFigure
from hydromodpy.display.figures.hydrograph import Hydrograph
from hydromodpy.display.figures.recession import RecessionCurveFigure


class SeriesRun:
    sim_id = "sim-a"
    name = "nancon"

    def timeseries(self, variable: str, *, station: str | None = None, **_) -> pd.Series:
        index = pd.date_range("2001-01-01", periods=12, freq="D")
        return pd.Series(np.linspace(2.0, 0.5, 12), index=index, name=variable)


@pytest.mark.parametrize(
    "figure", [Hydrograph(), DurationCurveFigure(), RecessionCurveFigure()], ids=type
)
def test_title_names_the_outlet_not_the_station_id(mpl, figure) -> None:
    fig, ax = mpl.subplots()

    figure.render(SeriesRun(), ax)

    assert "@ catchment outlet" in ax.get_title()
