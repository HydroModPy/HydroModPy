"""The dark preset darkens the light greys a figure draws, not only its background.

Measured on the documentation images of example 04: with ``[display] preset =
"dark"`` the dry cells of the intermittence map, the table of the identity card
and the frames of the flow-direction legends stayed white on a dark page.
"""

from __future__ import annotations

import matplotlib as mpl
import pytest

from hydromodpy.display.figures.flow_direction_map import FlowDirectionMap
from hydromodpy.display.figures.flow_intermittence_map import FlowIntermittenceMap
from hydromodpy.display.figures.watershed_id_card import WatershedIdCardFigure
from hydromodpy.display.style import apply_theme, is_dark, neutral
from tests.unit.results._transient_network_run import transient_run

from ._network_comparison_run import comparison_run
from ._render_helpers import relative_luminance
from .test_watershed_id_card import _run as card_run

DARK_ENOUGH = 0.1
"""Relative luminance under which a colour reads as part of a dark page."""


@pytest.fixture
def dark():
    pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    with mpl.rc_context():
        apply_theme("dark")
        yield plt
        plt.close("all")


def test_a_light_grey_is_kept_on_a_light_page() -> None:
    with mpl.rc_context():
        apply_theme("default")
        assert not is_dark()
        assert neutral("#EDEDED") == "#ededed"


def test_a_light_grey_lands_near_the_background_on_a_dark_page(dark) -> None:
    assert is_dark()
    assert relative_luminance(neutral("#EDEDED")) < DARK_ENOUGH
    # A colour that carries a hue is the figure's meaning: it is left alone.
    assert neutral("#d2762a") == "#d2762a"


def test_the_dry_cells_of_the_intermittence_map_follow_the_theme(dark) -> None:
    fig, ax = dark.subplots()

    FlowIntermittenceMap().render(transient_run(), ax, overlays=())

    bad = ax.collections[0].get_cmap().get_bad()
    assert relative_luminance(tuple(bad[:3])) < DARK_ENOUGH
    (legend,) = fig.legends
    dry = next(h for h in legend.legend_handles if h.get_label().startswith("dry"))
    assert relative_luminance(tuple(dry.get_facecolor()[:3])) < DARK_ENOUGH


def test_the_identity_card_table_follows_the_theme(dark) -> None:
    fig = WatershedIdCardFigure().plot(card_run(), dpi=60)

    table = next(ax for ax in fig.axes if ax.tables).tables[0]
    for cell in table.get_celld().values():
        assert relative_luminance(tuple(cell.get_facecolor()[:3])) < DARK_ENOUGH


def test_the_flow_direction_legend_and_compass_follow_the_theme(dark) -> None:
    fig, ax = dark.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    frame = ax.get_legend().get_frame()
    assert relative_luminance(tuple(frame.get_edgecolor()[:3])) < 0.3
    assert relative_luminance(tuple(frame.get_facecolor()[:3])) < DARK_ENOUGH
    rose = next(child for child in ax.get_children() if isinstance(child, mpl.axes.Axes))
    assert relative_luminance(tuple(rose.patch.get_facecolor()[:3])) < DARK_ENOUGH
