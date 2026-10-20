"""The build hands each lake's spillway to a reach that does not feed that lake.

The reaches are numbered against the lake order of the build, and a reach's
``terminal_lake`` is the 1-based position of its lake there. The wiring in
``build.py`` read that label 0-based: with one lake the forbidden set was empty,
with two lakes it forbade the feeders of the other lake. A spillway could then
be routed to a feeder of its own lake and close a LAK -> SFR -> LAK loop.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import numpy as np
import pytest

from hydromodpy.solver.modflow6.build import _resolve_spillway_receivers

_CENTROIDS = np.array([[float(i) * 10.0, 0.0] for i in range(8)])


def _reach(ifno: int, cell: int, *, upstream=(), terminal_lake: int | None = None) -> NS:
    return NS(
        ifno=ifno,
        cellid=(0, cell),
        upstream=tuple(upstream),
        is_terminal_to_lake=terminal_lake is not None,
        terminal_lake=terminal_lake,
    )


def test_one_lake_refuses_a_spillway_on_a_feeder_of_its_own() -> None:
    # Reach 0 on cell 2 ends in the only lake (terminal_lake = 1). The toe seed is on it.
    network = NS(reaches=[_reach(0, 2, terminal_lake=1), _reach(1, 5)])
    with pytest.raises(ValueError, match="circulate back into the reservoir"):
        _resolve_spillway_receivers(
            {"cheze": network}, {"res": 2}, lake_ids=["res"], cell_centroids=_CENTROIDS
        )


def test_two_lakes_forbid_the_feeders_of_the_right_lake() -> None:
    # Lake order: res (1), forebay (2). Reach 1 on cell 3 ends in the forebay;
    # reach 0 on cell 2 feeds it from upstream. Reach 2 on cell 5 ends in res.
    network = NS(
        reaches=[
            _reach(0, 2),
            _reach(1, 3, upstream=(0,), terminal_lake=2),
            _reach(2, 5, terminal_lake=1),
        ]
    )
    # The forebay toe on a reach upstream of its own terminal: refused.
    with pytest.raises(ValueError, match="circulate back into the reservoir"):
        _resolve_spillway_receivers(
            {"cheze": network},
            {"forebay": 2},
            lake_ids=["res", "forebay"],
            cell_centroids=_CENTROIDS,
        )
    # The forebay spilling into a feeder of res is a cascade: allowed.
    assert _resolve_spillway_receivers(
        {"cheze": network},
        {"forebay": 5},
        lake_ids=["res", "forebay"],
        cell_centroids=_CENTROIDS,
    ) == {"forebay": 2}
