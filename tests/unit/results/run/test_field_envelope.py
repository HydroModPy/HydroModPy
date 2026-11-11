"""The seepage a refinement zone reads is the drain outflow per cell area, in mm/d.

A drain budget in m3/s over a cell area in m2 is a depth rate in m/s, and one m/s is
1000 mm * 86 400 s/day = 86 400 000 mm/d. The mover term adds to the drain, and water
that enters leaves nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.results.run.field_envelope import MM_PER_DAY, _rows

# One square cell of 1 km by 1 km, so 1e6 m2.
_MESH = {
    "vertices": np.array([[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]]),
    "face_node_connectivity": np.array([[0, 1, 2, 3]]),
}


def _root(drain, mover=None) -> dict:
    budget = {"drain": np.array(drain, dtype=float).reshape(-1, 1, 1)}
    if mover is not None:
        budget["drain_to_mover"] = np.array(mover, dtype=float).reshape(-1, 1, 1)
    return {"mesh": _MESH, "budget": budget}


def test_one_meter_per_second_is_86_400_000_mm_per_day() -> None:
    assert MM_PER_DAY == 86_400_000.0


# One row per case: the drain and the mover terms in m3/s, one per step, and the seepage in
# mm/d they give on a cell of 1e6 m2 (1 m3/s over 1e6 m2 is 86.4 mm/d).
_SEEPAGE = [
    pytest.param([-1.0], None, [86.4], id="a_drain_losing_one_m3_s"),
    pytest.param([-1.0], [-0.25], [108.0], id="the_mover_adds_to_the_drain"),
    pytest.param([0.5], None, [0.0], id="water_entering_leaves_nothing"),
    pytest.param([0.0], None, [0.0], id="no_flow"),
    pytest.param([-1.0, 0.0, -2.0], None, [86.4, 0.0, 172.8], id="one_value_per_step"),
]


@pytest.mark.parametrize(("drain", "mover", "expected"), _SEEPAGE)
def test_the_seepage_is_the_drain_outflow_per_area_in_mm_per_day(drain, mover, expected) -> None:
    rows, unit, n_steps = _rows(
        _root(drain, mover), "seepage", 1, reference="first", name="first.v1"
    )

    assert unit == "mm/d"
    assert n_steps == len(expected)
    np.testing.assert_allclose(rows(0, n_steps).reshape(-1), expected, rtol=1e-12, atol=0.0)


def test_a_run_without_a_drain_budget_is_refused_by_name() -> None:
    root = {"mesh": _MESH, "budget": {}}

    with pytest.raises(ConfigError, match="kept no drain budget"):
        _rows(root, "seepage", 1, reference="first", name="first.v1")


def test_a_run_without_a_head_gives_no_water_table_depth() -> None:
    with pytest.raises(ConfigError, match="stores no head"):
        _rows({"mesh": _MESH}, "watertable_depth", 1, reference="first", name="first.v1")
