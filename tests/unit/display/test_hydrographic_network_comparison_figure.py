from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib
from shapely.geometry import LineString, box

from hydromodpy.display.figure_registry import get
from hydromodpy.spatial.geographic.core.hydrographic_network_comparison import (
    compare_hydrographic_networks,
)


class _StubRun:
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


def test_hydrographic_network_comparison_figure_renders(tmp_path: Path) -> None:
    matplotlib.use("Agg", force=True)
    fig = get("hydrographic_network_comparison")
    out = tmp_path / "hydrographic_network_comparison.png"

    rendered = fig.plot(_StubRun(), save_path=out, tolerance_m=50.0)

    assert rendered is not None
    assert len(rendered.axes) == 4
    assert out.exists()


def test_hydrographic_network_role_figures_render(tmp_path: Path) -> None:
    matplotlib.use("Agg", force=True)
    stub = _StubRun()

    for figure_name in ("hydrographic_network_reference", "hydrographic_network_generated"):
        fig = get(figure_name)
        out = tmp_path / f"{figure_name}.png"
        rendered = fig.plot(stub, save_path=out)
        assert rendered is not None
        assert len(rendered.axes) == 1
        assert out.exists()


def test_hydrographic_network_difference_role_figures_render(tmp_path: Path) -> None:
    matplotlib.use("Agg", force=True)
    stub = _StubRun()

    for figure_name in (
        "hydrographic_network_reference_missing_only",
        "hydrographic_network_generated_extra_only",
    ):
        fig = get(figure_name)
        out = tmp_path / f"{figure_name}.png"
        rendered = fig.plot(stub, save_path=out)
        assert rendered is not None
        assert len(rendered.axes) == 1
        assert out.exists()


class _PermanenceStubRun(_StubRun):
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


def test_permanence_figure_splits_the_map_into_its_two_bounds(tmp_path: Path) -> None:
    matplotlib.use("Agg", force=True)
    fig = get("hydrographic_network_permanence")
    stub = _PermanenceStubRun()
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


def test_permanence_figure_names_a_source_without_permanence() -> None:
    reason = get("hydrographic_network_permanence").unavailable_reason(
        _PermanenceStubRun(with_permanent=False)
    )
    assert reason is not None
    assert "reference_permanent" in reason
