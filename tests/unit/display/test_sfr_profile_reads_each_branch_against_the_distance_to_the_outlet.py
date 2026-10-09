"""The SFR profile draws each branch as its own line, against the distance to the outlet.

Reaches are numbered downstream-increasing, so on a branched network the
numbering interleaves the tributaries: a profile against the number zigzags
between branches. Here two tributaries of two reaches meet at a confluence
reach, which drains to the outlet reach. The numbering interleaves them on
purpose (0, 1, 2, 3 are the four tributary reaches in build order)::

    0 -> 2 -> 4 -> 5
    1 -> 3 -/

Every reach is 100 m long.
"""

from __future__ import annotations

from types import SimpleNamespace

import matplotlib as mpl
import pandas as pd
import pytest

from hydromodpy.display.figure import FigureNotApplicable
from hydromodpy.display.figures.sfr_longitudinal_profile import (
    SfrLongitudinalProfile,
    distance_to_outlet,
)

LINKS = pd.DataFrame(
    {
        "network_id": ["main"] * 6,
        "ifno": [0, 1, 2, 3, 4, 5],
        "rlen": [100.0] * 6,
        "ustrf": [1.0] * 6,
        "downstream": [[2], [3], [4], [4], [5], []],
    }
)

FLOW = {0: 1.0, 1: 2.0, 2: 3.0, 3: 5.0, 4: 8.0, 5: 9.0}
"""A flow that grows downstream on each branch, so a branch reads as a rising line."""


def _run(links: pd.DataFrame = LINKS) -> SimpleNamespace:
    stations = {ifno: f"sfr:main:{ifno}" for ifno in FLOW}
    return SimpleNamespace(
        sim_id="sim-sfr",
        name="nancon",
        n_timesteps=1,
        stations=lambda variable: list(stations.values()),
        timeseries=lambda variable, station=None: pd.Series(
            [FLOW[int(station.rsplit(":", 1)[1])]], index=[pd.Timestamp("2000-01-31")]
        ),
        _catalog=SimpleNamespace(backend=SimpleNamespace(query=lambda *_a, **_k: links)),
    )


def test_the_distance_counts_from_the_middle_of_a_reach_to_the_outlet() -> None:
    distance = distance_to_outlet(LINKS)

    assert distance[("main", 5)] == pytest.approx(50.0)
    assert distance[("main", 4)] == pytest.approx(150.0)
    assert distance[("main", 2)] == pytest.approx(250.0)
    assert distance[("main", 3)] == pytest.approx(250.0)
    assert distance[("main", 0)] == pytest.approx(350.0)


def test_a_fork_follows_the_branch_that_takes_the_larger_share_of_the_flow() -> None:
    links = pd.DataFrame(
        {
            "network_id": ["main"] * 4,
            "ifno": [0, 1, 2, 3],
            "rlen": [100.0, 400.0, 100.0, 100.0],
            "ustrf": [1.0, 0.3, 0.7, 1.0],
            "downstream": [[1, 2], [3], [3], []],
        }
    )

    distance = distance_to_outlet(links)

    # Reach 0 drains 70 % of its flow by reach 2, so the long reach 1 is not its path.
    assert distance[("main", 0)] == pytest.approx(50.0 + 100.0 + 100.0)


def test_each_branch_is_a_line_that_stops_at_the_reach_it_joins() -> None:
    pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        SfrLongitudinalProfile().render(_run(), ax, variable="downstream_flow", timestep=-1)
        segments = {
            tuple(map(tuple, segment.tolist())) for segment in ax.collections[0].get_segments()
        }
    finally:
        plt.close(fig)

    expected = {
        ((350.0, 1.0), (250.0, 3.0)),
        ((350.0, 2.0), (250.0, 5.0)),
        ((250.0, 3.0), (150.0, 8.0)),
        ((250.0, 5.0), (150.0, 8.0)),
        ((150.0, 8.0), (50.0, 9.0)),
    }
    assert segments == expected
    assert ax.xaxis_inverted(), "the outlet is on the right, as the profile has always read"


def test_the_axis_says_what_it_measures() -> None:
    pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        SfrLongitudinalProfile().render(_run(), ax)
        assert ax.get_xlabel() == "distance to the outlet, along the main path (m)"
    finally:
        plt.close(fig)


def test_a_run_sealed_before_the_table_stored_its_links_is_skipped_with_the_remedy() -> None:
    pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    old = LINKS.drop(columns="downstream")
    fig, ax = plt.subplots()
    try:
        with pytest.raises(FigureNotApplicable, match="Run it again"):
            SfrLongitudinalProfile().render(_run(old), ax)
    finally:
        plt.close(fig)
