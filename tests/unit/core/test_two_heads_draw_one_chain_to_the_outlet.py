"""Two heads of a mapped network draw one chain down the criterion graph.

The heads rule keeps only where the map starts a stream and lets the model's
own descent draw the rest, so the drawn map is connected and reaches the
outlet by construction, whatever path the mapped lines take below the heads.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._heads_valley import (
    AXIS,
    N_ROWS,
    candidates,
    cell,
    centre,
    valley_geometry,
)


def test_two_heads_draw_one_connected_chain_to_the_outlet() -> None:
    junction = centre(15, AXIS)
    # The axis reach from row 2, and a tributary from the west hillside.
    heads = candidates(
        [
            (centre(2, AXIS), junction),
            (centre(15, 3), junction),
            (centre(N_ROWS - 1, AXIS), junction),
        ]
    )

    geometry = valley_geometry(heads)

    drawn = geometry.observed
    downstream = geometry.metric.graph.downstream
    assert drawn[geometry.outlet]
    assert drawn[cell(2, AXIS)] and drawn[cell(15, 3)]
    # Every drawn cell drains into a drawn cell, or leaves the domain.
    receivers = downstream[drawn]
    assert np.all((receivers < 0) | drawn[np.maximum(receivers, 0)])
    # Exactly two drawn cells have no drawn cell upstream: the two heads.
    fed = np.zeros(drawn.size, dtype=bool)
    fed[receivers[receivers >= 0]] = True
    assert int(np.count_nonzero(drawn & ~fed)) == 2
    assert geometry.heads is not None
    assert geometry.diagnostics["n_heads"] == 2.0
    assert geometry.diagnostics["n_heads_lost"] == 0.0
    assert geometry.diagnostics["head_snap_p90_m"] == 0.0
