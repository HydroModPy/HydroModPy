"""The dark preset reaches every colour a figure draws."""

from __future__ import annotations

from types import SimpleNamespace

import matplotlib as mpl
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_rgb
from matplotlib.legend import Legend

from hydromodpy.display.figures.accumulation_map import AccumulationMap
from hydromodpy.display.figures.boundary_package_map import BoundaryPackageMap
from hydromodpy.display.figures.flow_direction_map import FlowDirectionMap
from hydromodpy.display.figures.flow_intermittence_map import FlowIntermittenceMap
from hydromodpy.display.figures.mesh_map import MeshMap
from hydromodpy.display.figures.seepage_map import SeepageMap
from hydromodpy.display.figures.seepage_network_confusion_map import SeepageNetworkConfusionMap
from hydromodpy.display.figures.sfr_reach_network import SfrReachNetwork
from hydromodpy.display.figures.simulated_active_network import SimulatedActiveNetworkMap
from hydromodpy.display.figures.watershed_id_card import WatershedIdCardFigure
from hydromodpy.display.style import apply_theme, is_dark, neutral, relative_luminance
from hydromodpy.results.derive import views
from tests.unit.results._transient_network_run import transient_run

from ._network_comparison_run import AXIS_COLUMN, NX, NY, cell, comparison_run
from .test_accumulation_map import _run as accumulation_run
from .test_boundary_package_map import _flux_on
from .test_boundary_package_map import _run as boundary_run
from .test_watershed_id_card import _run as card_run

# The dark preset darkens the light grays a figure draws, not only its background.
#
# Measured on the documentation images of example 04: with ``[display] preset =
# "dark"`` the dry cells of the intermittence map, the table of the identity card
# and the frames of the flow-direction legends stayed white on a dark page.

DARK_ENOUGH = 0.1


"""Relative luminance under which a color reads as part of a dark page."""


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
    # A color that carries a hue is the figure's meaning: it is left alone.
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
    for table_cell in table.get_celld().values():
        assert relative_luminance(tuple(table_cell.get_facecolor()[:3])) < DARK_ENOUGH


def test_the_flow_direction_legend_and_compass_follow_the_theme(dark) -> None:
    fig, ax = dark.subplots()

    FlowDirectionMap().render(comparison_run(), ax)

    frame = ax.get_legend().get_frame()
    assert relative_luminance(tuple(frame.get_edgecolor()[:3])) < 0.3
    assert relative_luminance(tuple(frame.get_facecolor()[:3])) < DARK_ENOUGH
    rose = next(child for child in ax.get_children() if isinstance(child, mpl.axes.Axes))
    assert relative_luminance(tuple(rose.patch.get_facecolor()[:3])) < DARK_ENOUGH


# The dark preset darkens the ground gray of every map, not only its page.
#
# Measured on the documentation images drawn with ``[display] preset = "dark"``:
# the cells a map measures nothing on (seepage, confusion, network, accumulation
# and boundary-package maps), the cell edges of the mesh map and the text box of
# the SFR network map kept the gray written for a white page, and were the
# brightest thing on a dark one.

LIGHT = 0.4


"""Relative luminance over which a gray reads as light on the dark page."""


def _is_grey(color) -> bool:
    red, green, blue = to_rgb(color)
    return max(red, green, blue) - min(red, green, blue) < 0.02


def _light_greys(fig) -> list[str]:
    """Return what the figure draws in a light gray, as ``artist: color``."""
    found: list[str] = []

    def check(where: str, colors) -> None:
        for color in np.atleast_2d(np.asarray(colors, dtype=float).reshape(-1, 4)):
            if (
                color[3] > 0.0
                and _is_grey(color[:3])
                and relative_luminance(tuple(color[:3])) > LIGHT
            ):
                found.append(f"{where}: {tuple(round(float(c), 2) for c in color[:3])}")

    for ax in (ax for ax in fig.axes if ax.get_label() != "<colorbar>"):
        for collection in ax.collections:
            label = str(collection.get_label())
            check(f"{label} face", collection.get_facecolor())
            check(f"{label} edge", collection.get_edgecolor())
            cmap = collection.get_cmap() if collection.get_array() is not None else None
            if cmap is not None:
                check(f"{label} masked cells", [cmap.get_bad()])
        for text in ax.texts:
            patch = text.get_bbox_patch()
            if patch is not None:
                check(f"note {text.get_text()[:20]!r} box face", patch.get_facecolor())
                check(f"note {text.get_text()[:20]!r} box edge", patch.get_edgecolor())
    legends = [*fig.legends, *(ax.get_legend() for ax in fig.axes)]
    for legend in filter(None, legends):
        assert isinstance(legend, Legend)
        for handle in legend.legend_handles:
            check(f"legend {handle.get_label()!r} face", handle.get_facecolor())
    return found


def _seepage_run():
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, 1), cell(4, 0)])
    mask = np.zeros(NX * NY)
    mask[[cell(AXIS_COLUMN, 1), cell(AXIS_COLUMN, 2)]] = 1.0
    fields = {"seepage_mask": mask}
    run.has_field = lambda variable, **_: variable in fields
    run.field = lambda variable, **_: fields[variable]
    return run


def _mesh_run():
    run = comparison_run()
    topography = np.linspace(100.0, 140.0, NX * NY)
    fields = {"topography": topography}
    run.has_field = lambda variable, **_: variable in fields
    run.field = lambda variable, **_: fields[variable]
    run.n_layers = 1
    return run


def _sfr_run():
    import geopandas as gpd
    from shapely.geometry import LineString

    network = gpd.GeoDataFrame(
        {"strahler": [1, 2]},
        geometry=[LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 1)])],
        crs="EPSG:2154",
    )
    series = SimpleNamespace(
        iloc=[0.5, 1.5],
        index=[0, 1],
    )
    return SimpleNamespace(
        sim_id="sim-sfr",
        name="nancon",
        stations=lambda variable: ["main:1", "main:2"],
        timeseries=lambda variable, station=None: __import__("pandas").Series(
            [0.5, 1.5], index=[0, 1]
        ),
        hydrographic_network=lambda role: network,
        geographic=lambda feature: (_ for _ in ()).throw(KeyError(feature)),
        n_timesteps=2,
    )


CASES = {
    "seepage_map": lambda: (SeepageMap(), _seepage_run(), {}),
    "seepage_network_confusion_map": lambda: (
        SeepageNetworkConfusionMap(),
        comparison_run(seepage_cells=[cell(AXIS_COLUMN, 1), cell(4, 0)]),
        {},
    ),
    "accumulation_map": lambda: (
        AccumulationMap(),
        accumulation_run(),
        {"overlays": ()},
    ),
    "boundary_package_map": lambda: (
        BoundaryPackageMap(),
        boundary_run({"drain": _flux_on([0, 1])}),
        {},
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_no_ground_stays_light_on_a_dark_page(dark, name: str) -> None:
    figure, run, options = CASES[name]()
    fig, ax = dark.subplots()

    figure.render(run, ax, **options)

    assert _light_greys(fig) == []


def test_the_simulated_network_ground_follows_the_theme(dark, monkeypatch) -> None:
    mask = np.zeros(NX * NY)
    mask[[cell(2, 0), cell(2, 1)]] = 1.0
    monkeypatch.setattr(views, "cell_field_active_mask", lambda *_a, **_k: mask)
    monkeypatch.setattr(views, "resolve_cell_field_active_mode", lambda *_a, **_k: "last")
    monkeypatch.setattr(views, "cell_field_active_mode_label", lambda *_a, **_k: "active cells")
    fig, ax = dark.subplots()

    SimulatedActiveNetworkMap().render(comparison_run(), ax)

    assert _light_greys(fig) == []


def test_the_mesh_edges_follow_the_theme(dark) -> None:
    fig, ax = dark.subplots()

    MeshMap().render(_mesh_run(), ax, overlays=())

    edge = ax.collections[0].get_edgecolor()[0][:3]
    assert tuple(edge) == pytest.approx(to_rgb(neutral("0.25")))
    assert relative_luminance(tuple(edge)) > relative_luminance("#404040")


def test_the_sfr_network_text_box_follows_the_theme(dark, monkeypatch) -> None:
    monkeypatch.setattr(
        "hydromodpy.display.figures.sfr_reach_timeseries.sfr_reach_links",
        lambda _run: pd.DataFrame(
            {"reach_id": ["main:1", "main:2"], "network_id": ["main"] * 2, "reach": [1, 2]}
        ),
    )
    fig, ax = dark.subplots()

    SfrReachNetwork().render(_sfr_run(), ax)

    box = next(text for text in ax.texts if text.get_bbox_patch() is not None).get_bbox_patch()
    assert relative_luminance(tuple(box.get_facecolor()[:3])) < LIGHT


def test_a_light_page_keeps_its_greys() -> None:
    pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    with mpl.rc_context():
        apply_theme("default")
        fig, ax = plt.subplots()
        try:
            SeepageMap().render(_seepage_run(), ax)
            assert _light_greys(fig), "the light preset keeps the light ground"
        finally:
            plt.close(fig)
