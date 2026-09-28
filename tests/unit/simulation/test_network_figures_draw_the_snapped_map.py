"""The figures that draw the reference network follow ``[geographic.snap_streams]``.

In ``apply`` the reference map, the ``network`` overlay and the active-network
overlay draw the snapped map the run stored, one square per mapped cell, and
say so. In ``diagnose`` they draw the raw map and name it. In ``off`` they draw
what they always drew and add no note.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import pytest
from matplotlib.collections import LineCollection, PathCollection
from shapely.geometry import LineString, Point

from hydromodpy.display.figure_registry import get
from hydromodpy.display.maps.overlays import draw_network, network_map_of_role
from hydromodpy.results.derive.snapped_network import SNAPPED_NETWORK_FEATURES
from hydromodpy.results.run import Run
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
)

from ._test_simulation_api_builders import _register, catalog
from .test_simulation_cell_field_views import _write_active_accumulation_flux_case

__all__ = ["catalog"]

matplotlib.use("Agg", force=True)

RAW = LineString([(1.5, 0.5), (1.5, 1.5)])


def _run(catalog, mode: str | None, *, store_snapped: bool = True) -> Run:
    snapshot = None if mode is None else {"geographic": {"snap_streams": {"mode": mode}}}
    sid = _register(catalog, n_cells=4, n_layers=1, n_timesteps=3, config_snapshot=snapshot)
    _write_active_accumulation_flux_case(catalog, sid, write_plot_mesh=True)
    for name in (
        HYDROGRAPHIC_NETWORK_REFERENCE_FEATURE_NAME,
        HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    ):
        catalog.write_geographic_feature(
            sid, name, gpd.GeoDataFrame({"id": [1]}, geometry=[RAW], crs="EPSG:2154")
        )
    if store_snapped:
        # The raw map crosses cells 1 and 3; the snap moved cell 3 onto cell 1.
        catalog.write_geographic_feature(
            sid,
            SNAPPED_NETWORK_FEATURES["maximal"],
            gpd.GeoDataFrame(
                {
                    "raw_cell": [1, 3],
                    "snapped_cell": [1, 1],
                    "status": ["unchanged", "merged"],
                    "displacement_m": [0.0, 1.0],
                    "raw_x": [1.5, 1.5],
                    "raw_y": [0.5, 1.5],
                    "accumulation_percentile": [90.0, 90.0],
                },
                geometry=[Point(1.5, 0.5), Point(1.5, 0.5)],
                crs="EPSG:2154",
            ),
        )
    return Run(sid, catalog)


def _texts(ax) -> str:
    return "\n".join(text.get_text() for text in ax.texts)


def _collections(ax, kind: type) -> list:
    return [c for c in ax.collections if isinstance(c, kind)]


# network_map_of_role


def test_apply_picks_the_snapped_map(catalog) -> None:
    network = network_map_of_role(_run(catalog, "apply"), "reference")

    assert network.snapped
    assert network.snap_mode == "apply"
    assert len(network.frame) == 2
    assert network.label() == "snapped map ([geographic.snap_streams] apply)"


@pytest.mark.parametrize(
    ("mode", "label"),
    [
        (None, None),
        ("off", None),
        ("diagnose", "raw map ([geographic.snap_streams] diagnose)"),
    ],
)
def test_off_and_diagnose_pick_the_raw_map(catalog, mode, label) -> None:
    network = network_map_of_role(_run(catalog, mode), "reference")

    assert not network.snapped
    assert network.snap_mode == (mode or "off")
    assert list(network.frame.geometry) == [RAW]
    assert network.label() == label


def test_apply_without_a_stored_map_picks_the_raw_one_and_says_so(catalog, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        network = network_map_of_role(_run(catalog, "apply", store_snapped=False), "reference")

    assert not network.snapped
    assert network.label() == "raw map: the run stored no snapped map"
    assert "stored no snapped" in caplog.text


def test_the_generated_network_is_never_snapped(catalog) -> None:
    network = network_map_of_role(_run(catalog, "apply"), "generated")

    assert not network.snapped
    assert network.label() is None


# hydrographic_network_reference


def test_the_reference_figure_draws_the_snapped_cells_in_apply(catalog, tmp_path) -> None:
    rendered = get("hydrographic_network_reference").plot(
        _run(catalog, "apply"), save_path=tmp_path / "reference.png"
    )
    ax = rendered.axes[0]

    assert _collections(ax, PathCollection)
    assert not _collections(ax, LineCollection)
    note = _texts(ax)
    assert "snapped map ([geographic.snap_streams] apply)" in note
    assert "cells: 1 from 2 mapped" in note
    plt.close(rendered)


@pytest.mark.parametrize("mode", [None, "off"])
def test_the_reference_figure_is_unchanged_when_the_snap_is_off(catalog, tmp_path, mode) -> None:
    rendered = get("hydrographic_network_reference").plot(
        _run(catalog, mode), save_path=tmp_path / "reference.png"
    )
    ax = rendered.axes[0]

    assert _collections(ax, LineCollection)
    assert not _collections(ax, PathCollection)
    assert "data.hydrography\nsegments: 1\nlength: 0.00 km" in _texts(ax)
    assert "map" not in _texts(ax)
    plt.close(rendered)


def test_the_reference_figure_names_the_raw_map_in_diagnose(catalog, tmp_path) -> None:
    rendered = get("hydrographic_network_reference").plot(
        _run(catalog, "diagnose"), save_path=tmp_path / "reference.png"
    )
    ax = rendered.axes[0]

    assert _collections(ax, LineCollection)
    assert "raw map ([geographic.snap_streams] diagnose)" in _texts(ax)
    plt.close(rendered)


# network overlay


def test_the_network_overlay_draws_the_snapped_cells_in_apply(catalog) -> None:
    fig, ax = plt.subplots()
    draw_network(ax, _run(catalog, "apply"))

    (points,) = _collections(ax, PathCollection)
    assert points.get_label() == "reference network, snapped map ([geographic.snap_streams] apply)"
    assert not _collections(ax, LineCollection)
    plt.close(fig)


@pytest.mark.parametrize("mode", [None, "off"])
def test_the_network_overlay_is_unchanged_when_the_snap_is_off(catalog, mode) -> None:
    fig, ax = plt.subplots()
    draw_network(ax, _run(catalog, mode))

    (lines,) = _collections(ax, LineCollection)
    assert lines.get_label().startswith("_")
    assert not _collections(ax, PathCollection)
    plt.close(fig)


# simulated_active_network_reference_overlay


def _overlay(catalog, mode, tmp_path):
    rendered = get("simulated_active_network_reference_overlay").plot(
        _run(catalog, mode),
        save_path=tmp_path / "overlay.png",
        mode="persistent",
        threshold=0.5,
    )
    ax = rendered.axes[0]
    legend = [text.get_text() for text in ax.get_legend().get_texts()]
    return rendered, ax, legend


def test_the_active_overlay_draws_the_snapped_map_in_apply(catalog, tmp_path) -> None:
    rendered, ax, legend = _overlay(catalog, "apply", tmp_path)

    assert _collections(ax, PathCollection)
    assert "Reference network (snapped)" in legend
    note = _texts(ax)
    assert "snapped map ([geographic.snap_streams] apply)" in note
    # The drawn map and the scored map are the same: one cell, fully covered.
    assert "coverage: 1.000" in note
    plt.close(rendered)


@pytest.mark.parametrize("mode", [None, "off"])
def test_the_active_overlay_is_unchanged_when_the_snap_is_off(catalog, tmp_path, mode) -> None:
    rendered, ax, legend = _overlay(catalog, mode, tmp_path)

    assert not _collections(ax, PathCollection)
    assert "Reference network" in legend
    note = _texts(ax)
    assert "map" not in note
    assert "coverage: 0.500" in note
    plt.close(rendered)
