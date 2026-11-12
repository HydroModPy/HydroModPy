"""The accumulation map draws the field on a scale that spans its decades.

The mesh is a single row of unit cells carrying accumulated fluxes four
decades apart, plus one cell no release ever reached. The answer is therefore
written down here and not read back from the figure: the ramp must cover the
positive values, the empty cell must leave the ramp, and every color the ramp
uses must stay darker than the ground that cell is painted in.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figures.accumulation_map import AccumulationMap, truncated_palette

FLUXES = (0.0, 1.0e-6, 1.0e-4, 1.0e-2)
"""One empty cell and three positive ones, four decades apart."""

EMPTY_CELL = 0


def _run(values=FLUXES, *, field: str = "drain_accumulation_flux") -> SimpleNamespace:
    """Return a run holding one row of square cells carrying ``values``."""
    n = len(values)
    vertices = np.asarray(
        [[x, y, 0.0] for y in (0.0, 1.0) for x in range(n + 1)],
        dtype=float,
    )
    faces = np.asarray([[i, i + 1, n + 2 + i, n + 1 + i] for i in range(n)], dtype=int)
    fields = {field: np.asarray(values, dtype=float)}
    return SimpleNamespace(
        sim_id="sim-accumulation",
        name="nancon",
        n_timesteps=1,
        mesh=SimpleNamespace(vertices=vertices, face_node_connectivity=faces),
        has_field=lambda variable, **_: variable in fields,
        field=lambda variable, **_: fields[variable],
    )


def _axes():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt.subplots()


def _field_collection(ax):
    """Return the collection holding the drawn field, the first one added."""
    return ax.collections[0]


def test_log_scale_covers_the_positive_decades() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    fig, ax = _axes()
    try:
        AccumulationMap().render(_run(), ax)
        norm = _field_collection(ax).norm
        assert isinstance(norm, LogNorm)
        assert norm.vmin == pytest.approx(1.0e-6)
        assert norm.vmax == pytest.approx(1.0e-2)
    finally:
        plt.close(fig)


def test_the_cell_with_no_flux_leaves_the_ramp() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _axes()
    try:
        AccumulationMap().render(_run(), ax)
        drawn = _field_collection(ax).get_array()
        masked = np.ma.getmaskarray(drawn)
        assert list(np.flatnonzero(masked)) == [EMPTY_CELL]
        assert drawn[1:].tolist() == pytest.approx(list(FLUXES[1:]))
    finally:
        plt.close(fig)


def test_a_linear_scale_keeps_the_same_partition() -> None:
    """``scale='linear'`` changes the ramp, not which cells the ramp describes."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    fig, ax = _axes()
    try:
        AccumulationMap().render(_run(), ax, scale="linear")
        collection = _field_collection(ax)
        assert not isinstance(collection.norm, LogNorm)
        assert collection.get_clim() == pytest.approx((1.0e-6, 1.0e-2))
        masked = np.ma.getmaskarray(collection.get_array())
        assert list(np.flatnonzero(masked)) == [EMPTY_CELL]
    finally:
        plt.close(fig)


def test_caller_bounds_win_over_the_data_range() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _axes()
    try:
        AccumulationMap().render(_run(), ax, vmin=1.0e-5, vmax=1.0)
        norm = _field_collection(ax).norm
        assert (norm.vmin, norm.vmax) == pytest.approx((1.0e-5, 1.0))
    finally:
        plt.close(fig)


def test_a_field_that_accumulates_nowhere_still_draws() -> None:
    """Every cell empty is a result, not a failure: the map says so."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    fig, ax = _axes()
    try:
        AccumulationMap().render(_run([0.0, 0.0, 0.0, 0.0]), ax)
        collection = _field_collection(ax)
        assert not isinstance(collection.norm, LogNorm)
        assert np.ma.getmaskarray(collection.get_array()).all()
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert any("4 cells" in label for label in labels)
    finally:
        plt.close(fig)


def test_a_field_that_accumulates_everywhere_carries_no_ground_entry() -> None:
    """Nothing is painted in the ground color, so nothing claims it is."""
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _axes()
    try:
        AccumulationMap().render(_run([1.0e-6, 1.0e-4, 1.0e-2, 1.0]), ax, overlays=())
        assert ax.get_legend() is None
    finally:
        plt.close(fig)


def test_a_log_ramp_refuses_a_lower_bound_it_cannot_place() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _axes()
    try:
        with pytest.raises(ValueError, match="strictly positive lower bound"):
            AccumulationMap().render(_run(), ax, vmin=0.0)
    finally:
        plt.close(fig)


def test_an_unknown_scale_is_refused_by_name() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _axes()
    try:
        with pytest.raises(ValueError, match="'log' or 'linear'"):
            AccumulationMap().render(_run(), ax, scale="symlog")
    finally:
        plt.close(fig)


def test_a_palette_floor_outside_the_palette_is_refused() -> None:
    pytest.importorskip("matplotlib")

    with pytest.raises(ValueError, match="palette_floor"):
        truncated_palette(AccumulationMap.default_cmap, 1.0)
