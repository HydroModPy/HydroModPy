"""Conditioning impact map: the change of mesh top elevation (m) between two runs.

The map colors each cell by the top elevation of the run minus that of its
reference run, on a symmetric scale clipped at a percentile of the changes.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figures.conditioning_impact_map import ConditioningImpactMap
from hydromodpy.display.subject import FigureNotApplicable

# Two square cells side by side.
VERTICES = np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
FACES = np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int)


def run_with_tops(tops, sim_id: str = "sim") -> SimpleNamespace:
    mesh = SimpleNamespace(
        vertices=VERTICES,
        face_node_connectivity=FACES,
        z_interfaces=np.asarray([0.0, -10.0]),
        topography=None if tops is None else np.asarray(tops, dtype=float),
    )
    return SimpleNamespace(mesh=mesh, sim_id=sim_id)


def test_two_runs_on_one_mesh_give_their_top_difference(mpl) -> None:
    sim = run_with_tops([12.0, 10.0])
    ref = run_with_tops([10.0, 10.0], sim_id="ref")  # cell 0 raised by 2 m, cell 1 unchanged
    fig, ax = mpl.subplots()

    ConditioningImpactMap().render(sim, ax, reference=ref, clip_percentile=100.0)

    collection = ax.collections[0]
    np.testing.assert_allclose(collection.get_array(), [2.0, 0.0])
    assert collection.get_clim() == (-2.0, 2.0)
    assert "50% of cells" in ax.get_title()


def test_run_without_mesh_topography_is_unavailable() -> None:
    assert "no mesh topography" in ConditioningImpactMap().unavailable_reason(run_with_tops(None))


def test_skipped_figure_leaves_no_figure_open(mpl) -> None:
    mpl.close("all")

    with pytest.raises(FigureNotApplicable):
        ConditioningImpactMap().plot(run_with_tops([1.0, 2.0]))

    assert mpl.get_fignums() == []


REFUSALS = [
    pytest.param(
        run_with_tops([1.0, 2.0]),
        {"reference": None},
        FigureNotApplicable,
        r"reference=<run>",
        id="no reference run",
    ),
    pytest.param(
        run_with_tops([1.0, 2.0]),
        {"reference": run_with_tops([1.0, 2.0, 3.0], sim_id="ref")},  # 3 cells against 2
        ValueError,
        "meshes differ",
        id="reference on another mesh",
    ),
]


@pytest.mark.parametrize(("run", "kwargs", "error", "message"), REFUSALS)
def test_refusals(mpl, run, kwargs, error, message) -> None:
    fig, ax = mpl.subplots()

    with pytest.raises(error, match=message):
        ConditioningImpactMap().render(run, ax, **kwargs)
