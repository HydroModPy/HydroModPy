"""Unit tests for the two-run top difference figure."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figure import FigureNotApplicable
from hydromodpy.display.figures.conditioning_impact_map import ConditioningImpactMap

_VERTS = np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
_CONN = np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int)


def _run(tops, sim_id: str = "sim") -> SimpleNamespace:
    mesh = SimpleNamespace(
        vertices=_VERTS,
        face_node_connectivity=_CONN,
        z_interfaces=np.asarray([0.0, -10.0]),
        topography=None if tops is None else np.asarray(tops, dtype=float),
    )
    return SimpleNamespace(mesh=mesh, sim_id=sim_id)


def _ax():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots()


def test_two_runs_on_one_mesh_render_their_top_difference() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run([12.0, 10.0])
    ref = _run([10.0, 10.0], sim_id="ref")  # cell 0 raised +2, cell 1 unchanged
    fig, ax = _ax()
    try:
        ConditioningImpactMap().render(sim, ax, reference=ref, clip_percentile=100.0)
        coll = ax.collections[0]
        np.testing.assert_allclose(coll.get_array(), [2.0, 0.0])
        assert coll.get_clim() == (-2.0, 2.0)
        assert "50% of cells" in ax.get_title()
    finally:
        plt.close(fig)


def test_a_run_without_reference_is_skipped_with_a_sentence() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _ax()
    try:
        with pytest.raises(FigureNotApplicable, match=r"reference=<run>"):
            ConditioningImpactMap().render(_run([1.0, 2.0]), ax, reference=None)
    finally:
        plt.close(fig)


def test_a_run_without_mesh_topography_is_unavailable() -> None:
    assert "no mesh topography" in ConditioningImpactMap().unavailable_reason(_run(None))


def test_reference_run_on_another_mesh_is_rejected() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run([1.0, 2.0])
    ref = _run([1.0, 2.0, 3.0], sim_id="ref")  # 3 cells
    fig, ax = _ax()
    try:
        with pytest.raises(ValueError, match="meshes differ"):
            ConditioningImpactMap().render(sim, ax, reference=ref)
    finally:
        plt.close(fig)


def test_a_skipped_figure_leaves_no_matplotlib_figure_open() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.close("all")

    with pytest.raises(FigureNotApplicable):
        ConditioningImpactMap().plot(_run([1.0, 2.0]))

    assert plt.get_fignums() == []
