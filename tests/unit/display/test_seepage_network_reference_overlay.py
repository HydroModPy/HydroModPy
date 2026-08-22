"""The visual check of a simulated stream network against the mapped one.

The figure answers one question before any number is trusted: do the two
networks live in the same place, and does the simulated one follow the
talwegs of the routing surface. So the tests assert on the relief behind the
linework, on the two networks staying apart without colour, and on what the
figure says when one of them is empty.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.display.figures.seepage_network_reference_overlay import (
    NETWORK_COLORS,
    SeepageNetworkReferenceOverlay,
)


@pytest.fixture
def mpl():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    yield plt
    plt.close("all")


def _grid_run(
    nx: int = 4,
    ny: int = 3,
    *,
    topography: np.ndarray | str | None = "valley",
    cell_m: float = 10.0,
    name: str = "cheze",
    outlet: tuple[float, float] | None = None,
) -> SimpleNamespace:
    """A run whose mesh is a ``nx x ny`` grid of square cells, row-major.

    ``topography`` defaults to a V-shaped valley running north-south, the
    relief this figure exists to show a network against. ``None`` builds a run
    that persisted no topography at all.
    """
    vertices = [[i * cell_m, j * cell_m, 0.0] for j in range(ny + 1) for i in range(nx + 1)]
    faces = [
        [
            j * (nx + 1) + i,
            j * (nx + 1) + i + 1,
            (j + 1) * (nx + 1) + i + 1,
            (j + 1) * (nx + 1) + i,
        ]
        for j in range(ny)
        for i in range(nx)
    ]
    mesh = SimpleNamespace(
        vertices=np.asarray(vertices, dtype=float),
        face_node_connectivity=np.asarray(faces, dtype=int),
    )

    if isinstance(topography, str):
        centre = nx * cell_m / 2.0
        x = np.asarray([(i + 0.5) * cell_m for _ in range(ny) for i in range(nx)])
        elevation = np.abs(x - centre) * 2.0
    elif topography is None:
        elevation = None
    else:
        elevation = np.asarray(topography, dtype=float)

    run = SimpleNamespace(
        sim_id="sim-mesh",
        name=name,
        mesh=mesh,
        has_field=lambda variable, _has=elevation is not None: variable == "topography" and _has,
        field=lambda variable, **_: elevation,
    )
    if outlet is not None:
        run.outlet = outlet
    return run


def _column_mask(nx: int, ny: int, columns: list[int]) -> np.ndarray:
    """A mask holding every cell of the given grid columns."""
    mask = np.zeros(nx * ny, dtype=bool)
    for j in range(ny):
        for i in columns:
            mask[j * nx + i] = True
    return mask


def _relative_luminance(color: str) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _polygon_area(vertices: np.ndarray) -> float:
    x, y = vertices[:, 0], vertices[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _collection(ax, label_prefix: str):
    return next(
        collection
        for collection in ax.collections
        if str(collection.get_label()).startswith(label_prefix)
    )


# --------------------------------------------------------------------------- #
# the composition
# --------------------------------------------------------------------------- #


def test_overlay_draws_the_two_networks_over_the_relief(mpl) -> None:
    run = _grid_run(4, 3)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1, 2]),
    )

    try:
        relief = _collection(ax, "_relief")
        assert len(relief.get_paths()) == 12, "the relief covers every mesh cell"
        assert relief.get_zorder() < _collection(ax, "_observed").get_zorder()
        assert (
            _collection(ax, "_observed").get_zorder() < _collection(ax, "_simulated").get_zorder()
        ), "the simulated network is drawn over the mapped one"
        assert len(_collection(ax, "_observed").get_paths()) == 3
        assert len(_collection(ax, "_simulated").get_paths()) == 6
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert labels[:2] == ["mapped network (3 cells)", "simulated network (6 cells)"]
        assert ax.get_xlabel() == "x (m)"
        assert ax.get_ylabel() == "y (m)"
        assert "cheze" in ax.get_title()
    finally:
        mpl.close(fig)


def test_overlay_frames_the_whole_mesh(mpl) -> None:
    run = _grid_run(4, 3)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        assert xmin <= 0.0 and xmax >= 40.0
        assert ymin <= 0.0 and ymax >= 30.0
    finally:
        mpl.close(fig)


def test_overlay_draws_the_outlet_when_the_run_carries_one(mpl) -> None:
    run = _grid_run(4, 3, outlet=(15.0, 5.0))
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "Outlet" in labels
        assert _collection(ax, "Outlet").get_offsets().tolist() == [[15.0, 5.0]]
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the two networks stay apart without colour
# --------------------------------------------------------------------------- #


def test_the_two_networks_stay_apart_in_greyscale() -> None:
    luminances = [_relative_luminance(color) for color in NETWORK_COLORS.values()]

    assert abs(luminances[0] - luminances[1]) > 0.1, (
        "the mapped and simulated networks must survive a greyscale print, so "
        f"their lightnesses may not collide: {luminances}"
    )


def test_the_simulated_network_is_inset_so_shape_carries_the_distinction(mpl) -> None:
    run = _grid_run(4, 3)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        mapped = _polygon_area(_collection(ax, "_observed").get_paths()[0].vertices)
        simulated = _polygon_area(_collection(ax, "_simulated").get_paths()[0].vertices)
        assert mapped == pytest.approx(100.0), "the mapped network fills its cell"
        assert simulated < 0.5 * mapped, (
            "the simulated network must be drawn inset inside the cell, so the "
            "two networks are told apart by shape and not only by colour"
        )
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the relief
# --------------------------------------------------------------------------- #


def test_the_relief_lights_the_flank_that_faces_the_lamp(mpl) -> None:
    # A V-shaped valley lit from the west: the east flank faces the lamp and
    # must come out brighter than the west one, otherwise the shading carries
    # no aspect and the talwegs do not read.
    run = _grid_run(4, 3)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
        azimuth_deg=270.0,
    )

    try:
        shading = np.asarray(_collection(ax, "_relief").get_array(), dtype=float)
        assert shading.shape == (12,)
        assert np.all((shading >= 0.0) & (shading <= 1.0))
        west = shading.reshape(3, 4)[:, 0]
        east = shading.reshape(3, 4)[:, 3]
        assert np.all(east > west)
    finally:
        mpl.close(fig)


def test_flat_ground_takes_one_uniform_shade(mpl) -> None:
    run = _grid_run(4, 3, topography=np.full(12, 120.0))
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        relief = _collection(ax, "_relief")
        shading = np.asarray(relief.get_array(), dtype=float)
        assert np.allclose(shading, shading[0])
        assert 0.0 < float(shading[0]) < 1.0
        assert relief.get_clim() == (0.0, 1.0), (
            "ground with no relief keeps the full grey scale; stretching a "
            "spread of zero would print rounding noise as topography"
        )
    finally:
        mpl.close(fig)


def test_a_gentle_relief_is_stretched_over_the_greys_it_occupies(mpl) -> None:
    # A shallow valley lights within a narrow band of the theoretical range.
    # Left on that range it prints as one flat plate and no talweg reads.
    centre = 20.0
    x = np.asarray([(i + 0.5) * 10.0 for _ in range(3) for i in range(4)])
    run = _grid_run(4, 3, topography=np.abs(x - centre) * 0.08)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        relief = _collection(ax, "_relief")
        shading = np.asarray(relief.get_array(), dtype=float)
        assert shading.max() - shading.min() < 0.2, "the synthetic relief is a gentle one"
        low, high = relief.get_clim()
        assert low > 0.3 and high < 0.95
        assert low == pytest.approx(float(np.percentile(shading, 2.0)))
        assert high == pytest.approx(float(np.percentile(shading, 98.0)))
    finally:
        mpl.close(fig)


def test_a_cell_without_an_elevation_stays_unshaded(mpl) -> None:
    elevation = np.full(12, 120.0)
    elevation[5] = np.nan
    run = _grid_run(4, 3, topography=elevation)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        shading = np.asarray(_collection(ax, "_relief").get_array(), dtype=float)
        assert np.isnan(shading[5]), (
            "a cell the run gave no elevation must stay blank, never take the shade of flat ground"
        )
        assert np.isfinite(shading[np.arange(12) != 5]).all()
    finally:
        mpl.close(fig)


def test_overlay_says_when_the_run_persisted_no_topography(mpl) -> None:
    run = _grid_run(4, 3, topography=None)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        assert not [
            collection
            for collection in ax.collections
            if str(collection.get_label()).startswith("_relief")
        ]
        assert "no per-cell topography" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_overlay_says_when_no_cell_carries_an_elevation(mpl) -> None:
    # A field of nothing but NaN prints exactly like flat white ground. Left
    # unsaid, a reader takes the blank for a relief with no talweg in it.
    run = _grid_run(4, 3, topography=np.full(12, np.nan))
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        assert "relief background is missing" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_overlay_refuses_a_topography_that_does_not_match_the_mesh(mpl) -> None:
    run = _grid_run(4, 3, topography=np.arange(5.0))
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="the mesh holds 12"):
            SeepageNetworkReferenceOverlay().render(
                run,
                ax,
                observed=_column_mask(4, 3, [1]),
                simulated=_column_mask(4, 3, [1]),
            )
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# an empty network is said, never drawn as an agreement
# --------------------------------------------------------------------------- #


def test_overlay_says_when_the_simulated_network_is_empty(mpl) -> None:
    run = _grid_run(4, 3)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=_column_mask(4, 3, [1]),
        simulated=np.zeros(12, dtype=bool),
    )

    try:
        assert "simulated network is empty" in ax.texts[0].get_text()
        labels = [text.get_text() for text in ax.get_legend().get_texts()]
        assert "simulated network (0 cells)" in labels
    finally:
        mpl.close(fig)


def test_overlay_says_when_the_mapped_network_is_empty(mpl) -> None:
    run = _grid_run(4, 3)
    fig, ax = mpl.subplots()

    SeepageNetworkReferenceOverlay().render(
        run,
        ax,
        observed=np.zeros(12, dtype=bool),
        simulated=_column_mask(4, 3, [1]),
    )

    try:
        assert "mapped network is empty" in ax.texts[0].get_text()
    finally:
        mpl.close(fig)


def test_overlay_refuses_a_mask_of_the_wrong_size(mpl) -> None:
    run = _grid_run(2, 1)
    fig, ax = mpl.subplots()

    try:
        with pytest.raises(ValueError, match="the mesh holds 2"):
            SeepageNetworkReferenceOverlay().render(
                run,
                ax,
                observed=np.array([True, False, False]),
                simulated=np.array([False, True]),
            )
    finally:
        mpl.close(fig)


# --------------------------------------------------------------------------- #
# the gallery
# --------------------------------------------------------------------------- #


def test_overlay_is_skipped_by_the_gallery_rather_than_crashing(mpl, tmp_path) -> None:
    # The two masks live inside the criterion and no run persists them, so
    # driven from a config the figure must report itself as not applicable
    # instead of dying on its own signature.
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run

    cfg = DisplayConfig(
        enabled=True,
        figures=["seepage_network_reference_overlay"],
        on_error="raise",
    )

    report = render_figures_for_run(_grid_run(4, 3), cfg, output_dir=tmp_path)

    assert report.rendered == ()
    assert [item.name for item in report.skipped] == ["seepage_network_reference_overlay"]
    reason = report.skipped[0].reason
    assert all(word in reason for word in ("simulated", "observed"))
    assert "render failed" not in reason


def test_overlay_names_what_it_needs_when_it_cannot_be_drawn() -> None:
    reason = SeepageNetworkReferenceOverlay().unavailable_reason(_grid_run(2, 1))

    assert reason is not None
    assert "calibration" in reason


def test_the_figure_is_registered_under_its_own_name() -> None:
    figure = get_figure("seepage_network_reference_overlay")

    assert isinstance(figure, SeepageNetworkReferenceOverlay)
    assert figure.spec.name == "seepage_network_reference_overlay"
    assert figure.spec.kind == "comparison"
