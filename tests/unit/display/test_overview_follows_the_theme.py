"""The overview tables and the catchment outline follow the dark theme of the figures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.display.overview import panels
from hydromodpy.display.style import apply_theme


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    saved = matplotlib.rcParams.copy()
    yield plt
    plt.close("all")
    matplotlib.rcParams.update(saved)


def _luminance(color) -> float:
    from matplotlib.colors import to_rgb

    red, green, blue = to_rgb(color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _tables(plt):
    fig, (ax_stats, ax_inventory) = plt.subplots(1, 2)
    summary = SimpleNamespace(
        watershed_name="Naizin",
        catchment_area_km2=12.5,
        date_start="2020-01-01",
        date_end="2020-12-31",
        n_streams=3,
        n_hydrometry=1,
        n_piezometry=2,
        n_intermittency=0,
        n_water_quality=4,
    )
    inventory = [
        {"type": "Hydrometry", "id": "H1", "x": 1.0, "y": 2.0, "start": "a", "end": "b"},
    ]
    panels.render_stats_card(ax_stats, summary=summary)
    panels.render_station_inventory(ax_inventory, inventory=inventory)
    return ax_stats.tables[0], ax_inventory.tables[0]


def test_the_tables_are_drawn_on_the_dark_background_in_the_dark_theme(mpl) -> None:
    apply_theme("dark")
    for table in _tables(mpl):
        for cell in table.get_celld().values():
            assert _luminance(cell.get_facecolor()) < 0.5, "a cell is still white"
            assert _luminance(cell.get_text().get_color()) > 0.5, "dark text on a dark cell"
            assert _luminance(cell.get_edgecolor()) < 0.5, "an edge is brighter than the text"


def test_the_tables_keep_white_cells_in_the_default_theme(mpl) -> None:
    apply_theme("default")
    for table in _tables(mpl):
        body = table[(1, 1)]
        assert _luminance(body.get_facecolor()) > 0.95
        assert _luminance(body.get_text().get_color()) < 0.1


def test_the_header_of_the_inventory_is_a_grey_that_follows_the_theme(mpl) -> None:
    apply_theme("default")
    light = _tables(mpl)[1][(0, 0)].get_facecolor()
    apply_theme("dark")
    dark = _tables(mpl)[1][(0, 0)].get_facecolor()
    assert _luminance(light) > 0.85
    assert _luminance(dark) < 0.5
    assert _luminance(dark) > _luminance(_tables(mpl)[1][(1, 0)].get_facecolor())


def test_the_catchment_outline_is_black_on_light_and_light_on_dark(mpl) -> None:
    apply_theme("default")
    assert panels._outline_color() == "#000000"
    apply_theme("dark")
    assert _luminance(panels._outline_color()) > 0.8
