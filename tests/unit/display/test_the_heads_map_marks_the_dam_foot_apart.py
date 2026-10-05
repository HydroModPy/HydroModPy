"""The heads map marks the foot of a dam apart from the heads the map gives.

A forced head has no free end and no landing cell: it is a diamond of its own,
with its own legend entry, and the title counts it beside the traced heads.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from hydromodpy.display.figures.observed_network_heads_map import (
    FORCED_HEAD_COLOR,
    ObservedNetworkHeadsMap,
)
from hydromodpy.results.run.descent import RunDescent
from tests.unit.display._network_comparison_run import comparison_run, legend_labels

HILLSIDE = 10


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _run(cells):
    run = comparison_run()
    stored = replace(run.descent.view(), dam_foot=np.asarray(cells, dtype=np.int64))
    run.descent = RunDescent(lambda: stored)
    return run


def test_the_dam_foot_has_its_own_marker_and_legend_entry(mpl) -> None:
    fig, ax = mpl.subplots()

    ObservedNetworkHeadsMap().render(_run([HILLSIDE]), ax)

    assert "1 dam foot" in ax.get_title()
    assert "dam foot, forced head (1)" in legend_labels(ax)
    from matplotlib.colors import to_rgba

    marked = [
        collection
        for collection in ax.collections
        if collection.get_offsets().shape[0] == 1
        and len(collection.get_facecolor())
        and np.allclose(collection.get_facecolor()[0], to_rgba(FORCED_HEAD_COLOR))
    ]
    assert len(marked) == 1


def test_a_run_with_no_dam_foot_shows_no_such_entry(mpl) -> None:
    fig, ax = mpl.subplots()

    ObservedNetworkHeadsMap().render(_run([]), ax)

    assert "dam foot" not in ax.get_title()
    assert not any("dam foot" in label for label in legend_labels(ax))
