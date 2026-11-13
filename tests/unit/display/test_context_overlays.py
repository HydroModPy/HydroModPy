"""The overlays draw on a small fake run, or return silently when data is absent."""

from __future__ import annotations

import logging
from dataclasses import replace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from hydromodpy.display import overlays, subject
from hydromodpy.display.request import OVERLAY_FIELDS
from hydromodpy.display.theme import get_theme

THEME = get_theme("default")
GRID = np.array([[x, y] for y in range(3) for x in range(3)], float) * 100.0
MESH = subject.MeshView(
    centres=np.array([[50, 50], [150, 50], [50, 150], [150, 150]], float),
    vertices=GRID,
    faces=np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]]),
    areas=np.full(4, 1e4),
    zones={"catchment": np.array([True, True, True, False]), "domain": np.ones(4, bool)},
    crs=None,
    n_layers=1,
    outlet=(100.0, 0.0),
)
LINES = gpd.GeoDataFrame({"geometry": [LineString([(0, 0), (100, 100), (200, 100)])]})
TWO = gpd.GeoDataFrame({"geometry": [*LINES.geometry, LineString([(0, 200), (100, 100)])]})
NETWORKS = {"reference": TWO, "reference_permanent": LINES, "generated": LINES, "barrier": LINES}
POINTS = pd.DataFrame({"station_id": ["P1"], "x": [50.0], "y": [50.0]})


def network(_run, role):
    if role not in NETWORKS:
        raise subject.FigureNotApplicable(f"no {role} layer")
    return NETWORKS[role]


@pytest.fixture
def reads(monkeypatch):
    monkeypatch.setattr(subject, "read_mesh", lambda _run: MESH)
    monkeypatch.setattr(subject, "read_network", network)
    monkeypatch.setattr(subject, "read_table", lambda _run, name: POINTS)
    monkeypatch.setattr(
        subject,
        "read_field",
        lambda _run, name, **_: np.array(
            [10.0, 12, 15, 20] if name == "topography" else [0, 1, np.nan, 2]
        ),
    )


def axes():
    ax = Figure().subplots()
    ax.set_xlim(0, 200)
    ax.set_ylim(0, 200)
    return ax


def artists(ax):
    return len(ax.collections) + len(ax.images) + len(ax.lines)


def test_the_table_and_the_request_hold_the_same_names():
    assert set(overlays.OVERLAYS) == set(OVERLAY_FIELDS)
    assert all(draw.__name__ == name for name, draw in overlays.OVERLAYS.items())


@pytest.mark.parametrize("name", sorted(OVERLAY_FIELDS))
def test_each_overlay_draws_an_artist(reads, name):
    ax = axes()
    overlays.OVERLAYS[name](ax, None, THEME)
    assert artists(ax) >= 1


def test_what_each_one_draws(reads):
    ax = axes()
    overlays.network(ax, None, THEME)
    assert len(ax.collections) == 2
    ax = axes()
    overlays.outline(ax, None, THEME)
    assert len(ax.collections[0].get_segments()) == 8
    ax = axes()
    for name in ("mesh", "lake", "wells"):
        overlays.OVERLAYS[name](ax, None, THEME)
    assert all(c.get_rasterized() for c in ax.collections)
    ax = axes()
    overlays.relief(ax, None, THEME)
    assert ax.get_aspect() == 1.0


def test_absent_data_logs_one_line_and_draws_nothing(monkeypatch, caplog):
    def missing(*_args, **_kwargs):
        raise subject.FigureNotApplicable("not held")

    for read in ("read_mesh", "read_field", "read_network", "read_table"):
        monkeypatch.setattr(subject, read, missing)
    for name in ("relief", "network", "generated_network", "stations", "barrier", "lake", "wells"):
        ax = axes()
        with caplog.at_level(logging.INFO):
            overlays.OVERLAYS[name](ax, None, THEME)
        assert artists(ax) == 0
    assert sum("not held" in r.getMessage() for r in caplog.records) == 7


def test_an_outlet_without_a_point_is_silent(monkeypatch):
    monkeypatch.setattr(subject, "read_mesh", lambda _run: replace(MESH, outlet=None))
    ax = axes()
    overlays.outlet(ax, None, THEME)
    assert artists(ax) == 0


def test_every_kind_of_geometry_and_the_degenerate_cases(reads, monkeypatch):
    shapes = gpd.GeoDataFrame(
        {
            "geometry": [
                MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]]),
                Polygon([(0, 0), (9, 0), (9, 9)]),
                Point(1, 1),
            ]
        }
    )
    monkeypatch.setattr(
        subject,
        "read_network",
        lambda _run, role: shapes if role == "barrier" else NETWORKS["reference"],
    )
    ax = axes()
    overlays.barrier(ax, None, THEME)
    assert len(ax.collections[0].get_segments()) == 3
    ax = axes()
    overlays.network(ax, None, THEME)
    assert len(ax.collections) == 1
    monkeypatch.setattr(
        subject, "read_network", lambda _run, role: gpd.GeoDataFrame({"geometry": []})
    )
    monkeypatch.setattr(subject, "read_field", lambda _run, name, **_: np.zeros(4))
    ax = axes()
    for name in ("generated_network", "lake", "wells"):
        overlays.OVERLAYS[name](ax, None, THEME)
    assert artists(ax) == 0
