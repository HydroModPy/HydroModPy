"""Unit tests for the conditioning-impact map figure."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figures.conditioning_impact_map import ConditioningImpactMap

_VERTS = np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
_CONN = np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int)


def _run(tops, reference=None, sim_id: str = "sim") -> SimpleNamespace:
    # topography = conditioned per-cell top; topography_reference = pre-conditioning.
    mesh = SimpleNamespace(
        vertices=_VERTS,
        face_node_connectivity=_CONN,
        z_interfaces=np.asarray([0.0, -10.0]),
        topography=np.asarray(tops, dtype=float),
        topography_reference=None if reference is None else np.asarray(reference, dtype=float),
    )
    return SimpleNamespace(mesh=mesh, sim_id=sim_id)


def _ax():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots()


def test_single_run_renders_delta_from_persisted_reference() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    sim = _run([12.0, 10.0], reference=[10.0, 10.0])  # cell 0 raised +2, cell 1 unchanged
    fig, ax = _ax()
    try:
        ConditioningImpactMap().render(sim, ax, clip_percentile=100.0)
        coll = ax.collections[0]
        np.testing.assert_allclose(coll.get_array(), [2.0, 0.0])
        assert coll.get_clim() == (-2.0, 2.0)
        assert "50% of cells" in ax.get_title()
    finally:
        plt.close(fig)


def test_errors_without_any_reference() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _ax()
    try:
        with pytest.raises(ValueError, match="pre-conditioning top"):
            ConditioningImpactMap().render(_run([1.0, 2.0]), ax, reference=None)
    finally:
        plt.close(fig)


def test_reference_run_overrides_and_rejects_mismatched_meshes() -> None:
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
