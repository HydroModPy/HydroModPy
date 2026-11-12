"""Map of accumulated flux (m3/s) on a color scale that spans its decades.

The mesh is a single row of unit cells carrying fluxes four decades apart, plus
one cell no release ever reached. The ramp must cover the positive values, the
empty cell must leave the ramp, and every ramp color must stay darker than the
ground that cell is painted in.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from matplotlib.colors import LogNorm

from hydromodpy.display.figures.accumulation_map import AccumulationMap, truncated_palette

FLUXES = (0.0, 1.0e-6, 1.0e-4, 1.0e-2)  # one empty cell, three positive ones
EMPTY_CELL = 0


def accumulation_run(values=FLUXES) -> SimpleNamespace:
    """One row of unit cells carrying ``values`` as the accumulated drain flux."""
    n = len(values)
    vertices = np.asarray([[x, y, 0.0] for y in (0.0, 1.0) for x in range(n + 1)], dtype=float)
    faces = np.asarray([[i, i + 1, n + 2 + i, n + 1 + i] for i in range(n)], dtype=int)
    fields = {"drain_accumulation_flux": np.asarray(values, dtype=float)}
    return SimpleNamespace(
        sim_id="sim-accumulation",
        name="nancon",
        n_timesteps=1,
        mesh=SimpleNamespace(vertices=vertices, face_node_connectivity=faces),
        has_field=lambda variable, **_: variable in fields,
        field=lambda variable, **_: fields[variable],
    )


def draw(mpl, values=FLUXES, **kwargs):
    """Render the map and return its axes and the collection holding the field."""
    _, ax = mpl.subplots()
    AccumulationMap().render(accumulation_run(values), ax, **kwargs)
    return ax, ax.collections[0]


def test_log_scale_covers_the_positive_decades(mpl) -> None:
    _, field = draw(mpl)

    assert isinstance(field.norm, LogNorm)
    assert (field.norm.vmin, field.norm.vmax) == pytest.approx((1.0e-6, 1.0e-2))


def test_the_cell_with_no_flux_leaves_the_ramp(mpl) -> None:
    _, field = draw(mpl)

    drawn = field.get_array()
    assert list(np.flatnonzero(np.ma.getmaskarray(drawn))) == [EMPTY_CELL]
    assert drawn[1:].tolist() == pytest.approx(list(FLUXES[1:]))


def test_linear_scale_keeps_the_same_partition(mpl) -> None:
    # scale="linear" changes the ramp, not which cells the ramp describes.
    _, field = draw(mpl, scale="linear")

    assert not isinstance(field.norm, LogNorm)
    assert field.get_clim() == pytest.approx((1.0e-6, 1.0e-2))
    assert list(np.flatnonzero(np.ma.getmaskarray(field.get_array()))) == [EMPTY_CELL]


def test_caller_bounds_win_over_the_data(mpl) -> None:
    _, field = draw(mpl, vmin=1.0e-5, vmax=1.0)

    assert (field.norm.vmin, field.norm.vmax) == pytest.approx((1.0e-5, 1.0))


def test_a_field_that_accumulates_nowhere_still_draws(mpl) -> None:
    # Every cell empty is a result, not a failure: the map says so.
    ax, field = draw(mpl, [0.0, 0.0, 0.0, 0.0])

    assert not isinstance(field.norm, LogNorm)
    assert np.ma.getmaskarray(field.get_array()).all()
    assert any("4 cells" in text.get_text() for text in ax.get_legend().get_texts())


def test_a_field_that_accumulates_everywhere_has_no_ground_entry(mpl) -> None:
    # Nothing is painted in the ground color, so nothing claims it is.
    ax, _ = draw(mpl, [1.0e-6, 1.0e-4, 1.0e-2, 1.0], overlays=())

    assert ax.get_legend() is None


REFUSALS = [
    pytest.param({"vmin": 0.0}, "strictly positive lower bound", id="log scale with a zero bound"),
    pytest.param({"scale": "symlog"}, "'log' or 'linear'", id="unknown scale"),
]


@pytest.mark.parametrize(("kwargs", "message"), REFUSALS)
def test_refusals(mpl, kwargs, message) -> None:
    _, ax = mpl.subplots()

    with pytest.raises(ValueError, match=message):
        AccumulationMap().render(accumulation_run(), ax, **kwargs)


def test_palette_floor_outside_the_palette_is_refused() -> None:
    with pytest.raises(ValueError, match="palette_floor"):
        truncated_palette(AccumulationMap.default_cmap, 1.0)
