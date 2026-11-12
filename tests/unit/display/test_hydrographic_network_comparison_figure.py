"""Hydrographic network figures drawn on a 1 km reference stream, with coordinates in m (EPSG:2154).

The reference runs 1000 m. The candidate follows it for 700 m and adds a 300 m
reach 100 m away, so the comparison has matched, missing and extra parts.
Maps color each cell by its topography under every solver.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.catchment.algorithms.hydrographic_network_comparison import (
    compare_hydrographic_networks,
)
from hydromodpy.display.figure_registry import get
from hydromodpy.display.figures.hydrographic_network import plot_topography_background

VERTICES = np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
CONNECTIVITY = np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int)


class StubRun:
    sim_id = "11111111-2222-3333-4444-555555555555"
    name = "nancon"

    def __init__(self) -> None:
        self._reference = gpd.GeoDataFrame(
            geometry=[LineString([(0.0, 0.0), (1000.0, 0.0)])],
            crs="EPSG:2154",
        )
        self._candidate = gpd.GeoDataFrame(
            geometry=[
                LineString([(0.0, 0.0), (700.0, 0.0)]),
                LineString([(1000.0, 100.0), (1300.0, 100.0)]),
            ],
            crs="EPSG:2154",
        )
        self._watershed = gpd.GeoDataFrame(
            geometry=[box(-100.0, -200.0, 1400.0, 300.0)],
            crs="EPSG:2154",
        )

    def hydrographic_network_comparison(self, **kwargs):
        kwargs.pop("reference_role", None)
        kwargs.pop("candidate_role", None)
        return compare_hydrographic_networks(self._reference, self._candidate, **kwargs)

    def hydrographic_network(self, role: str = "generated"):
        if role == "reference":
            return self._reference
        if role == "generated":
            return self._candidate
        raise KeyError(role)

    def geographic(self, feature_name: str):
        if feature_name == "watershed":
            return self._watershed
        raise KeyError(feature_name)


class PermanenceStubRun(StubRun):
    """A run whose map holds 1 km of permanent and 0.5 km of intermittent reaches."""

    def __init__(self, *, with_permanent: bool = True) -> None:
        super().__init__()
        self._reference = gpd.GeoDataFrame(
            {"permanence": ["permanent", "intermittent"]},
            geometry=[
                LineString([(0.0, 0.0), (1000.0, 0.0)]),
                LineString([(1000.0, 0.0), (1000.0, 500.0)]),
            ],
            crs="EPSG:2154",
        )
        self._permanent = self._reference.iloc[[0]].copy() if with_permanent else None

    def has_hydrographic_network(self, role: str = "generated") -> bool:
        if role == "reference_permanent":
            return self._permanent is not None
        return role in ("reference", "generated")

    def hydrographic_network(self, role: str = "generated"):
        if role == "reference_permanent" and self._permanent is not None:
            return self._permanent
        return super().hydrographic_network(role)


def mesh_run(*, topography, z_interfaces) -> SimpleNamespace:
    mesh = SimpleNamespace(
        vertices=VERTICES,
        face_node_connectivity=CONNECTIVITY,
        z_interfaces=np.asarray(z_interfaces, dtype=float),
        topography=None if topography is None else np.asarray(topography, dtype=float),
    )
    return SimpleNamespace(mesh=mesh)


def test_comparison_figure(mpl, tmp_path: Path) -> None:
    out = tmp_path / "hydrographic_network_comparison.png"

    rendered = get("hydrographic_network_comparison").plot(
        StubRun(), save_path=out, tolerance_m=50.0
    )

    assert rendered is not None
    assert len(rendered.axes) == 4
    assert out.exists()


ONE_MAP_FIGURES = [
    pytest.param("hydrographic_network_reference", id="reference"),
    pytest.param("hydrographic_network_generated", id="generated"),
    pytest.param("hydrographic_network_reference_missing_only", id="reference missing only"),
    pytest.param("hydrographic_network_generated_extra_only", id="generated extra only"),
]


@pytest.mark.parametrize("figure_name", ONE_MAP_FIGURES)
def test_one_map_figures(mpl, tmp_path: Path, figure_name: str) -> None:
    out = tmp_path / f"{figure_name}.png"

    rendered = get(figure_name).plot(StubRun(), save_path=out)

    assert rendered is not None
    assert len(rendered.axes) == 1
    assert out.exists()


def test_permanence_legend(mpl, tmp_path: Path) -> None:
    fig = get("hydrographic_network_permanence")
    stub = PermanenceStubRun()
    assert fig.unavailable_reason(stub) is None

    rendered = fig.plot(stub, save_path=tmp_path / "permanence.png")

    legend = rendered.axes[0].get_legend()
    labels = [text.get_text() for text in legend.get_texts()]
    assert labels == [
        "permanent, minimal map: 1.00 km, 1 reaches",
        "maximal map beyond it: 0.50 km, 1 reaches",
    ]
    note = legend.get_title().get_text()
    assert "intermittent: 0.50 km, 1 reaches" in note
    assert "permanent: 1.00 km, 1 reaches" in note


def test_permanence_needs_its_source() -> None:
    reason = get("hydrographic_network_permanence").unavailable_reason(
        PermanenceStubRun(with_permanent=False)
    )

    assert reason is not None
    assert "reference_permanent" in reason


def test_topography_of_a_layer_column(mpl) -> None:
    # MODFLOW stores z_interfaces as one column of n_layers + 1 values.
    run = mesh_run(topography=[12.0, 10.0], z_interfaces=[12.0, 5.0, -10.0])
    fig, ax = mpl.subplots()

    plot_topography_background(ax, run)

    np.testing.assert_allclose(ax.collections[0].get_array(), [12.0, 10.0])


def test_no_topography(mpl) -> None:
    fig, ax = mpl.subplots()

    plot_topography_background(ax, mesh_run(topography=None, z_interfaces=[12.0, -10.0]))

    assert not ax.collections
