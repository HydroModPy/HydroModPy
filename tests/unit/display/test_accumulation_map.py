"""The accumulation map draws the field on a scale that spans its decades.

The mesh is a single row of unit cells carrying accumulated fluxes four
decades apart, plus one cell no release ever reached. The answer is therefore
written down here and not read back from the figure: the ramp must cover the
positive values, the empty cell must leave the ramp, and every colour the ramp
uses must stay darker than the ground that cell is painted in.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figures.accumulation_map import (
    GROUND_COLOR,
    PALETTE_FLOOR,
    AccumulationMap,
    truncated_palette,
)

FLUXES = (0.0, 1.0e-6, 1.0e-4, 1.0e-2)
"""One empty cell and three positive ones, four decades apart."""

EMPTY_CELL = 0


def _run(values=FLUXES, *, field: str = "accumulation_flux") -> SimpleNamespace:
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


def _lightness(rgb) -> float:
    """Return the CIE L* of one RGB triple, which is what greyscale keeps."""
    channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb[:3]]
    y = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    return 116.0 * y ** (1 / 3) - 16.0 if y > 0.008856 else 903.3 * y


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


def test_the_legend_counts_the_cells_outside_the_network() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib.pyplot as plt

    fig, ax = _axes()
    try:
        AccumulationMap().render(_run(), ax)
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "no accumulated flux (1 cell)" in labels
    finally:
        plt.close(fig)


def test_a_field_that_accumulates_everywhere_carries_no_ground_entry() -> None:
    """Nothing is painted in the ground colour, so nothing claims it is."""
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


@pytest.mark.parametrize("cmap", ["Blues", "viridis", "cividis"])
def test_every_drawn_colour_stays_darker_than_the_ground(cmap: str) -> None:
    """The property the map is legible by, in colour and in greyscale alike.

    The ground carries the cells the ramp says nothing about. A ramp reaching
    its lightness would make the cells it does describe disappear into it.
    The figure's own defaults are read here rather than repeated, and the
    palettes a caller may set are checked beside them: ``Blues`` is light at
    the bottom and ``viridis`` at the top, so a truncation that always cut
    the bottom would leave the second one pale exactly where it matters.
    """
    pytest.importorskip("matplotlib")
    from matplotlib.colors import to_rgb

    palette = truncated_palette(cmap, PALETTE_FLOOR)
    ramp = [_lightness(palette(value)) for value in np.linspace(0.0, 1.0, 32)]
    ground = _lightness(to_rgb(GROUND_COLOR))
    assert max(ramp) < ground - 10.0
    assert ramp == sorted(ramp) or ramp == sorted(ramp, reverse=True)


def test_the_default_palette_darkens_as_the_flux_climbs() -> None:
    """What the figure ships with, and the direction it reads in."""
    pytest.importorskip("matplotlib")

    palette = truncated_palette(AccumulationMap.default_cmap, PALETTE_FLOOR)
    ramp = [_lightness(palette(value)) for value in np.linspace(0.0, 1.0, 32)]

    assert AccumulationMap.default_cmap == "Blues"
    assert ramp == sorted(ramp, reverse=True)


def test_the_light_end_is_the_one_that_is_cut_whichever_end_it_is() -> None:
    """A palette light at the top keeps its dark colours, not its pale ones."""
    pytest.importorskip("matplotlib")
    from matplotlib.colors import to_hex

    from hydromodpy.display.colormaps import get_cmap

    base = get_cmap("viridis")
    palette = truncated_palette("viridis", PALETTE_FLOOR)

    assert to_hex(palette(0.0)) == to_hex(base(0.0)), "the dark end is kept"
    assert to_hex(palette(1.0)) == to_hex(base(1.0 - PALETTE_FLOOR)), "the light end is cut"


def test_the_palette_paints_the_empty_cells_in_the_ground_colour() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import to_hex, to_rgb

    palette = truncated_palette(AccumulationMap.default_cmap, PALETTE_FLOOR)
    assert to_hex(palette.get_bad()) == to_hex(to_rgb(GROUND_COLOR))


def test_a_palette_floor_outside_the_palette_is_refused() -> None:
    pytest.importorskip("matplotlib")

    with pytest.raises(ValueError, match="palette_floor"):
        truncated_palette(AccumulationMap.default_cmap, 1.0)


def test_unavailable_reason_names_the_field_a_run_lacks() -> None:
    reason = AccumulationMap().unavailable_reason(_run(field="head"))
    assert isinstance(reason, str)
    assert "accumulation_flux" in reason
    assert AccumulationMap().unavailable_reason(_run()) is None


def test_the_figure_is_requestable_from_a_toml() -> None:
    """Registered, and reachable through ``[display].figures`` with its knobs."""
    from hydromodpy.display import figure_registry
    from hydromodpy.display.config import DisplayConfig

    assert isinstance(figure_registry.get("accumulation_map"), AccumulationMap)
    config = DisplayConfig(
        figures=["accumulation_map"],
        overrides={"accumulation_map": {"scale": "linear", "cmap": "cividis"}},
    )
    assert config.overrides["accumulation_map"]["scale"] == "linear"
