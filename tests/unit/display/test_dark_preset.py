"""The dark preset darkens the grays a figure draws, not only its page.

Relative luminance runs from 0 (black) to 1 (white). A gray written for a white
page (the ground of a map, a table cell, a note box, mesh edges) must land near
the dark background, and a color that carries a hue is left alone. The legend
placement of a dense map is checked here too, since it lives in the same module
(``display/style.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_rgb
from matplotlib.legend import Legend
from shapely.geometry import LineString, box

from hydromodpy.display.figure import new_subplots
from hydromodpy.display.figures.mesh_map import MeshMap
from hydromodpy.display.figures.seepage_map import SeepageMap
from hydromodpy.display.figures.sfr_reach_network import SfrReachNetwork
from hydromodpy.display.figures.watershed_id_card import WatershedIdCardFigure
from hydromodpy.display.style import (
    LEGEND_BEST_PLACEMENT_LIMIT,
    is_dark,
    neutral,
    place_legend,
    relative_luminance,
    themed,
)

from ._network_comparison_run import AXIS_COLUMN, NX, NY, cell, comparison_run

DARK_ENOUGH = 0.1  # under this a color reads as part of a dark page
LIGHT = 0.4  # over this a gray reads as light on a dark page


@pytest.fixture
def dark():
    with themed("dark"):
        yield SimpleNamespace(subplots=new_subplots)


def is_grey(color) -> bool:
    red, green, blue = to_rgb(color)
    return max(red, green, blue) - min(red, green, blue) < 0.02


def light_greys(fig) -> list[str]:
    """What the figure draws in a light gray, as ``artist: color``."""
    found: list[str] = []

    def check(where: str, colors) -> None:
        for color in np.atleast_2d(np.asarray(colors, dtype=float).reshape(-1, 4)):
            if (
                color[3] > 0.0
                and is_grey(color[:3])
                and relative_luminance(tuple(color[:3])) > LIGHT
            ):
                found.append(f"{where}: {tuple(round(float(c), 2) for c in color[:3])}")

    for ax in (ax for ax in fig.axes if ax.get_label() != "<colorbar>"):
        for collection in ax.collections:
            label = str(collection.get_label())
            check(f"{label} face", collection.get_facecolor())
            check(f"{label} edge", collection.get_edgecolor())
            if collection.get_array() is not None:
                check(f"{label} masked cells", [collection.get_cmap().get_bad()])
        for text in ax.texts:
            patch = text.get_bbox_patch()
            if patch is not None:
                check(f"note {text.get_text()[:20]!r} box face", patch.get_facecolor())
                check(f"note {text.get_text()[:20]!r} box edge", patch.get_edgecolor())
    for legend in filter(None, [*fig.legends, *(ax.get_legend() for ax in fig.axes)]):
        assert isinstance(legend, Legend)
        for handle in legend.legend_handles:
            check(f"legend {handle.get_label()!r} face", handle.get_facecolor())
    return found


def seepage_run():
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, 1), cell(4, 0)])
    mask = np.zeros(NX * NY)
    mask[[cell(AXIS_COLUMN, 1), cell(AXIS_COLUMN, 2)]] = 1.0
    run.has_field = lambda variable, **_: variable == "seepage_mask"
    run.field = lambda variable, **_: mask
    return run


def mesh_run():
    run = comparison_run()
    topography = np.linspace(100.0, 140.0, NX * NY)
    run.has_field = lambda variable, **_: variable == "topography"
    run.field = lambda variable, **_: topography
    run.n_layers = 1
    return run


def sfr_run():
    network = gpd.GeoDataFrame(
        {"strahler": [1, 2]},
        geometry=[LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 1)])],
        crs="EPSG:2154",
    )
    return SimpleNamespace(
        sim_id="sim-sfr",
        name="nancon",
        stations=lambda variable: ["main:1", "main:2"],
        timeseries=lambda variable, station=None: pd.Series([0.5, 1.5], index=[0, 1]),
        hydrographic_network=lambda role: network,
        geographic=lambda feature: (_ for _ in ()).throw(KeyError(feature)),
        n_timesteps=2,
    )


def id_card_run():
    watershed = gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 8_000.0, 8_000.0)], crs="EPSG:2154")
    dem = np.linspace(100.0, 200.0, 16, dtype=float).reshape(4, 4)
    raster = SimpleNamespace(
        data=dem, transform=(2_000.0, 0.0, 0.0, 0.0, -2_000.0, 8_000.0), nodata=None
    )
    return SimpleNamespace(
        sim_id="c11914ab-5f1e-4a55-9f1c-2e6d9b0a7d11",
        name="nancon_intermittence_mf6_daily",
        project="04_streamflow_intermittence_in_transient",
        solver="modflow6",
        flow_regime="transient",
        status="running",
        n_cells=21_406,
        n_layers=1,
        n_timesteps=1_096,
        periods=SimpleNamespace(edges=pd.date_range("2000-01-01", "2003-01-01", freq="D")),
        geographic=lambda feature: watershed,
        geographic_raster=lambda name: raster,
        has_field=lambda *_, **__: False,
        has_table=lambda *_, **__: False,
    )


def test_light_grey_is_kept_on_a_light_page() -> None:
    with themed("default"):
        assert not is_dark()
        assert neutral("#EDEDED") == "#ededed"


def test_light_grey_lands_near_the_background_on_a_dark_page(dark) -> None:
    assert is_dark()
    assert relative_luminance(neutral("#EDEDED")) < DARK_ENOUGH
    # A color that carries a hue is the figure's meaning: it is left alone.
    assert neutral("#d2762a") == "#d2762a"


def test_identity_card_table_follows_the_theme(dark) -> None:
    fig = WatershedIdCardFigure().plot(id_card_run(), dpi=60)

    table = next(ax for ax in fig.axes if ax.tables).tables[0]
    for table_cell in table.get_celld().values():
        assert relative_luminance(tuple(table_cell.get_facecolor()[:3])) < DARK_ENOUGH


def test_mesh_edges_follow_the_theme(dark) -> None:
    _, ax = dark.subplots()

    MeshMap().render(mesh_run(), ax, overlays=())

    edge = ax.collections[0].get_edgecolor()[0][:3]
    assert tuple(edge) == pytest.approx(to_rgb(neutral("0.25")))
    assert relative_luminance(tuple(edge)) > relative_luminance("#404040")


def test_sfr_network_text_box_follows_the_theme(dark, monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.display.figures.sfr_reach_timeseries.sfr_reach_links",
        lambda _run: pd.DataFrame(
            {"reach_id": ["main:1", "main:2"], "network_id": ["main"] * 2, "reach": [1, 2]}
        ),
    )
    _, ax = dark.subplots()

    SfrReachNetwork().render(sfr_run(), ax)

    box_patch = next(
        text for text in ax.texts if text.get_bbox_patch() is not None
    ).get_bbox_patch()
    assert relative_luminance(tuple(box_patch.get_facecolor()[:3])) < LIGHT


def test_light_page_keeps_its_greys() -> None:
    with themed("default"):
        fig, ax = new_subplots()
        SeepageMap().render(seepage_run(), ax)
        assert light_greys(fig), "the light preset keeps the light ground"


def dense_axes(n_paths: int):
    """Axes holding ``n_paths`` unit squares in one collection and one labelled line."""
    from matplotlib.collections import PolyCollection
    from matplotlib.figure import Figure

    ax = Figure().subplots()
    squares = [
        np.array([[i, 0.0], [i + 1.0, 0.0], [i + 1.0, 1.0], [i, 1.0]]) for i in range(n_paths)
    ]
    ax.add_collection(PolyCollection(squares))
    ax.plot([0, 1], [0, 1], label="something")
    return ax


# loc="best" scores every candidate corner against every artist. On the Nancon
# at 25 m one entry over 243 552 polygons took 99.3 s to place against 1.1 s pinned.
def test_dense_axes_gets_a_pinned_legend() -> None:
    legend = place_legend(dense_axes(LEGEND_BEST_PLACEMENT_LIMIT + 1))

    assert legend is not None
    assert legend._loc != 0


def test_explicit_legend_location_is_kept() -> None:
    legend = place_legend(dense_axes(LEGEND_BEST_PLACEMENT_LIMIT + 1), loc="lower left")

    assert legend is not None
    assert legend._loc == 3  # matplotlib's code for "lower left"
