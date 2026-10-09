"""The site selection map follows the dark theme, and its legend names an area class."""

from __future__ import annotations

import pytest

from hydromodpy.display.style import apply_theme
from hydromodpy.reporting.site_selection import figures


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    saved = matplotlib.rcParams.copy()
    yield plt
    plt.close("all")
    matplotlib.rcParams.update(saved)


def _luminance(color) -> float:
    from matplotlib.colors import to_rgb

    red, green, blue = to_rgb(color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _basin(area_km2: float | None) -> dict:
    ring = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0], [0.0, 0.0]]
    props = {} if area_km2 is None else {"area_km2": area_km2}
    return {"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": props}


def _draw(tmp_path, name: str):
    from PIL import Image

    destination = tmp_path / name
    figures._write_map_png(
        destination,
        selection_id="areas",
        dem_path=None,
        context_layers=[],
        selected_basins=[_basin(20.0)],
        rejected_basins=[_basin(300.0)],
        selected_outlets=[],
        rejected_outlets=[],
        observation_points=[],
        generated_network=[],
    )
    return Image.open(destination).convert("RGB")


def test_an_area_class_is_labelled_as_a_class_not_as_a_bound(mpl) -> None:
    from matplotlib.patches import Patch

    handles = figures._area_legend_handles(Patch=Patch, selected_basins=[_basin(20.0)])
    assert [h.get_label() for h in handles] == ["Catchment, area class <= 75 km2"]
    far = figures._area_legend_handles(Patch=Patch, selected_basins=[_basin(900.0)])
    assert [h.get_label() for h in far] == ["Catchment, area class > 500 km2"]
    unknown = figures._area_legend_handles(Patch=Patch, selected_basins=[_basin(None)])
    assert [h.get_label() for h in unknown] == ["Catchment, area not given"]


def test_the_inks_are_those_of_a_white_page_in_the_default_theme(mpl) -> None:
    apply_theme("default")
    assert figures._ink("white") == "white"
    assert figures._ink("#eef7fb") == "#eef7fb"
    assert figures._ink("#b91c1c") == "#b91c1c"


def test_the_inks_swap_for_a_twin_in_the_dark_theme(mpl) -> None:
    apply_theme("dark")
    assert _luminance(figures._ink("white")) < 0.5
    assert _luminance(figures._ink("#eef7fb")) < 0.5
    assert figures._ink("#b91c1c") != "#b91c1c"
    assert figures._ink("#2b83ba") == "#2b83ba", "a colour that reads on both is kept"
    assert figures._ink("none") == "none"


def test_the_map_is_written_on_a_dark_page_in_the_dark_theme(mpl, tmp_path) -> None:
    apply_theme("dark")
    image = _draw(tmp_path, "dark.png")
    assert _luminance(tuple(c / 255 for c in image.getpixel((2, 2)))) < 0.3


def test_the_map_is_written_on_a_white_page_in_the_default_theme(mpl, tmp_path) -> None:
    apply_theme("default")
    image = _draw(tmp_path, "light.png")
    assert image.getpixel((2, 2)) == (255, 255, 255)
