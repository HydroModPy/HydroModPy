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

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pytest

from hydromodpy.display.figures.sfr_longitudinal_profile import (
    SfrLongitudinalProfile,
    distance_to_outlet,
)
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARQUET_SCHEMA_VERSION

LINKS = pd.DataFrame(
    {
        "reach_id": [f"main:{reach}" for reach in range(6)],
        "network_id": ["main"] * 6,
        "reach": [0, 1, 2, 3, 4, 5],
        "rlen": [100.0] * 6,
        "ustrf": [1.0] * 6,
        "downstream": [[2], [3], [4], [4], [5], []],
    }
)

# A flow (m3/s) that grows downstream on each branch, so a branch reads as a rising line.
FLOW = {0: 1.0, 1: 2.0, 2: 3.0, 3: 5.0, 4: 8.0, 5: 9.0}


def _run(tables: Path, links: pd.DataFrame = LINKS) -> SimpleNamespace:
    """A run whose ``sfr_reaches`` table sits in *tables*, as in a run directory."""
    tables.mkdir(parents=True, exist_ok=True)
    write_table_atomic(
        pa.Table.from_pandas(links, preserve_index=False),
        tables / "sfr_reaches.parquet",
        kv_metadata={"hmp.schema_version": PARQUET_SCHEMA_VERSION},
    )
    stations = {reach: f"main:{reach}" for reach in FLOW}
    return SimpleNamespace(
        sim_id="sim-sfr",
        name="nancon",
        n_timesteps=1,
        stations=lambda variable: list(stations.values()),
        timeseries=lambda variable, station=None: pd.Series(
            [FLOW[int(station.rsplit(":", 1)[1])]], index=[pd.Timestamp("2000-01-31")]
        ),
        _catalog=SimpleNamespace(tables_dir_for=lambda _sim_id: tables),
    )


def test_distance_to_the_outlet() -> None:
    distance = distance_to_outlet(LINKS)

    assert distance[("main", 5)] == pytest.approx(50.0)
    assert distance[("main", 4)] == pytest.approx(150.0)
    assert distance[("main", 2)] == pytest.approx(250.0)
    assert distance[("main", 3)] == pytest.approx(250.0)
    assert distance[("main", 0)] == pytest.approx(350.0)


def test_fork_follows_the_larger_flow() -> None:
    links = pd.DataFrame(
        {
            "network_id": ["main"] * 4,
            "reach_id": [f"main:{reach}" for reach in range(4)],
            "reach": [0, 1, 2, 3],
            "rlen": [100.0, 400.0, 100.0, 100.0],
            "ustrf": [1.0, 0.3, 0.7, 1.0],
            "downstream": [[1, 2], [3], [3], []],
        }
    )

    distance = distance_to_outlet(links)

    # Reach 0 drains 70 % of its flow by reach 2, so the long reach 1 is not its path.
    assert distance[("main", 0)] == pytest.approx(50.0 + 100.0 + 100.0)


def test_each_branch_is_a_line(mpl, tmp_path: Path) -> None:
    fig, ax = mpl.subplots()

    SfrLongitudinalProfile().render(_run(tmp_path), ax, variable="downstream_flow", timestep=-1)

    segments = {tuple(map(tuple, segment.tolist())) for segment in ax.collections[0].get_segments()}
    expected = {
        ((350.0, 1.0), (250.0, 3.0)),
        ((350.0, 2.0), (250.0, 5.0)),
        ((250.0, 3.0), (150.0, 8.0)),
        ((250.0, 5.0), (150.0, 8.0)),
        ((150.0, 8.0), (50.0, 9.0)),
    }
    assert segments == expected
    assert ax.xaxis_inverted(), "the outlet is on the right, as the profile has always read"


def test_axis_label(mpl, tmp_path: Path) -> None:
    fig, ax = mpl.subplots()

    SfrLongitudinalProfile().render(_run(tmp_path), ax)

    assert ax.get_xlabel() == "distance to the outlet, along the main path (m)"
