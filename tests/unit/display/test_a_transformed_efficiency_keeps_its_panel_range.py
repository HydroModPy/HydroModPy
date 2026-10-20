"""The fit panel of a transformed efficiency frames the values it draws.

A block with a ``transform`` draws its cost, not its efficiency. The panel used
to take its range from the efficiency (one minus the cost) and its "higher is
better" from the metric alone, so the points fell off the axis under a label
that read them the wrong way up.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from hydromodpy.display.figures.calibration_progress import CalibrationProgressFigure
from tests.unit.display.test_calibration_progress import _ylabels, nelder_mead_session

pytestmark = pytest.mark.unit


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _with_log_transform(run):
    session = run.calibration_sessions.iloc[0].to_dict()
    config = json.loads(session["config"])
    config["objective_blocks"][0]["transform"] = "log"
    run.calibration_sessions.loc[0, "config"] = json.dumps(config)
    return run


def test_a_transformed_efficiency_is_drawn_inside_its_range(mpl) -> None:
    fig = CalibrationProgressFigure().plot(_with_log_transform(nelder_mead_session()))

    fit_ax = next(ax for ax in fig.get_axes() if ax.get_title().startswith("Fit to the"))
    low, high = fit_ax.get_ylim()
    drawn = np.concatenate(
        [np.asarray(line.get_ydata(), dtype=float) for line in fit_ax.get_lines()]
    )
    drawn = drawn[np.isfinite(drawn)]
    assert drawn.size
    assert low <= drawn.min() and drawn.max() <= high
    assert "1 - NSElog (-), lower is better" in _ylabels(fig)
