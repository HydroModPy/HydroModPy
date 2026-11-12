"""Label of the instant a map draws, in words, from the end stamps of a run's periods.

A monthly period is stamped by the date that closes it, so the label names
the month before the stamp. A negative index counts from the last period.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.display.figures._instant import instant_label

MONTHLY = pd.date_range("2000-01-01", "2003-01-01", freq="MS")


def dated(edges) -> SimpleNamespace:
    return SimpleNamespace(
        periods=SimpleNamespace(edges=None if edges is None else pd.DatetimeIndex(edges))
    )


LABELS = [
    pytest.param(dated(MONTHLY), -1, "December 2002", id="negative index counts from the end"),
    pytest.param(dated(None), 0, "", id="run without dates"),
    pytest.param(dated(MONTHLY), 36, "", id="step the run does not hold"),
    pytest.param(
        SimpleNamespace(time_index=MONTHLY[1:]), 33, "October 2002", id="only end stamps exposed"
    ),
]


@pytest.mark.parametrize(("run", "index", "label"), LABELS)
def test_instant_label(run, index, label) -> None:
    assert instant_label(run, index) == label
