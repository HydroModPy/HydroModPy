"""The dark preset darkens the ground grey of every map, not only its page.

Measured on the documentation images drawn with ``[display] preset = "dark"``:
the cells a map measures nothing on (seepage, confusion, network, accumulation
and boundary-package maps), the cell edges of the mesh map and the text box of
the SFR network map kept the grey written for a white page, and were the
brightest thing on a dark one.
"""

from __future__ import annotations

from types import SimpleNamespace

import matplotlib as mpl
import numpy as np
import pytest
from matplotlib.colors import to_rgb
from matplotlib.legend import Legend

from hydromodpy.display.figures.accumulation_map import AccumulationMap
from hydromodpy.display.figures.boundary_package_map import BoundaryPackageMap
from hydromodpy.display.figures.mesh_map import MeshMap
from hydromodpy.display.figures.seepage_map import SeepageMap
from hydromodpy.display.figures.seepage_network_confusion_map import SeepageNetworkConfusionMap
from hydromodpy.display.figures.sfr_reach_network import SfrReachNetwork
from hydromodpy.display.figures.simulated_active_network import SimulatedActiveNetworkMap
from hydromodpy.display.style import apply_theme, neutral
from hydromodpy.results.derive import views

from ._network_comparison_run import AXIS_COLUMN, NX, NY, cell, comparison_run
from ._render_helpers import relative_luminance
from .test_accumulation_map import _run as accumulation_run
from .test_boundary_package_map import _flux_on
from .test_boundary_package_map import _run as boundary_run

LIGHT = 0.4
"""Relative luminance over which a grey reads as light on the dark page."""


@pytest.fixture
def dark():
    pytest.importorskip("matplotlib")
    mpl.use("Agg")
    import matplotlib.pyplot as plt

    with mpl.rc_context():
        apply_theme("dark")
        yield plt
        plt.close("all")


def _is_grey(color) -> bool:
    red, green, blue = to_rgb(color)
    return max(red, green, blue) - min(red, green, blue) < 0.02


def _light_greys(fig) -> list[str]:
    """Return what the figure draws in a light grey, as ``artist: colour``."""
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
        stations=lambda variable: ["sfr:main:0", "sfr:main:1"],
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


def test_the_sfr_network_text_box_follows_the_theme(dark) -> None:
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
