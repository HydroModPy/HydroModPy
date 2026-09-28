"""``[geographic.snap_streams]``: the mapped network snapped onto the talwegs.

The V-valley bench knows its talweg in closed form: the axis column. A map
drawn on it must come back unchanged, a map shifted by one column must come
back on it with a displacement of one cell everywhere, and a radius too small
to reach the axis must move nothing and reject what it cannot place. The floor
``F`` of the shifted map is the value the design study measured on the same
bench (127.0 m).
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.stream_geometry import build_network_geometry
from hydromodpy.core.stream_snap import (
    SNAP_MERGED,
    SNAP_MOVED,
    SNAP_REJECTED,
    SNAP_UNCHANGED,
    SnapStreamsConfig,
    normalise_snap_length,
    snap_length_m,
)
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    AXIS_COL,
    CELL_SIZE,
    N_CELLS,
    N_COLS,
    N_ROWS,
    OUTLET_ROW,
    build_bench,
    cell_id,
    observed_network,
)

SNAP_KEYS = {
    "snap_mode",
    "snap_radius_m",
    "snap_displacement_p50_m",
    "snap_displacement_p90_m",
    "snap_rejected_share",
    "snap_length_ratio",
    "snap_floor_m",
}


@pytest.fixture(scope="module")
def mesh():
    return quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _geometry(bench, mesh, observed: np.ndarray, snap: SnapStreamsConfig | None, **kwargs):
    vertices, connectivity = mesh
    return build_network_geometry(
        topography=bench.elevation,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        cell_area_m2=np.full(N_CELLS, CELL_SIZE * CELL_SIZE),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
        snap=snap,
        **kwargs,
    )


# -- the setting --------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("2 cells", "2 cells"),
        ("1 cell", "1 cell"),
        ("1 cells", "1 cell"),
        ("0.5 cell", "0.5 cells"),
        ("200 m", "200.0 m"),
        ("0.2 km", "200.0 m"),
        (150, "150.0 m"),
        ("150", "150.0 m"),
    ],
)
def test_a_snap_length_is_stored_in_one_form(given, stored) -> None:
    assert normalise_snap_length(given) == stored
    assert normalise_snap_length(stored) == stored


def test_a_length_in_cells_counts_h_obs() -> None:
    assert snap_length_m("2 cells", 75.0) == pytest.approx(150.0)
    assert snap_length_m("200 m", 75.0) == pytest.approx(200.0)


@pytest.mark.parametrize("bad", ["0 m", "-2 cells", "0 cells", True, "2 kg"])
def test_a_snap_length_must_be_a_positive_length(bad) -> None:
    with pytest.raises((ValidationError, ValueError)):
        SnapStreamsConfig(radius=bad)


def test_the_defaults_are_off_two_cells_one_cell_and_ten_per_cent() -> None:
    setting = SnapStreamsConfig()
    assert setting.mode == "off"
    assert not setting.enabled
    assert setting.radius_m(75.0) == pytest.approx(150.0)
    assert setting.displacement_bound_m(75.0) == pytest.approx(75.0)
    assert setting.max_rejected_share == pytest.approx(0.10)


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValidationError):
        SnapStreamsConfig(max_bridge="2 cells")


def test_the_geographic_section_carries_the_setting() -> None:
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

    config = GeographicConfig(
        source_mode="synthetic", snap_streams={"mode": "apply", "radius": "150 m"}
    )
    assert config.snap_streams.mode == "apply"
    assert config.snap_streams.radius == "150.0 m"
    assert GeographicConfig(source_mode="synthetic").snap_streams.mode == "off"


# -- off, diagnose, apply -------------------------------------------------------


def test_off_computes_nothing_and_publishes_nothing(bench, mesh) -> None:
    shifted = observed_network("shifted")
    plain = _geometry(bench, mesh, shifted, None)
    off = _geometry(bench, mesh, shifted, SnapStreamsConfig(mode="off"))

    assert off.snap is None
    assert not SNAP_KEYS & set(off.diagnostics)
    assert off.diagnostics == pytest.approx(plain.diagnostics, nan_ok=True)
    assert np.array_equal(off.observed, plain.observed)
    assert np.array_equal(off.distance_to_observed, plain.distance_to_observed)


def test_diagnose_publishes_and_scores_the_raw_map(bench, mesh) -> None:
    shifted = observed_network("shifted")
    off = _geometry(bench, mesh, shifted, None)
    diagnose = _geometry(bench, mesh, shifted, SnapStreamsConfig(mode="diagnose"))

    assert SNAP_KEYS <= set(diagnose.diagnostics)
    assert diagnose.diagnostics["snap_mode"] == 1.0
    assert np.array_equal(diagnose.observed, off.observed)
    assert np.array_equal(diagnose.distance_to_observed, off.distance_to_observed)
    assert diagnose.h_obs_m == off.h_obs_m
    # Only the validity length reads the floor the snap measured.
    h, floor = off.h_obs_m, diagnose.snap.floor_m
    assert off.validity_length().length_m == pytest.approx(2.0 * h)
    validity = diagnose.validity_length()
    assert validity.length_m == pytest.approx(h + max(h, floor))
    assert validity.provenance == ("auto_floor" if floor > h else "auto")


def test_apply_scores_the_snapped_map(bench, mesh) -> None:
    applied = _geometry(bench, mesh, observed_network("shifted"), SnapStreamsConfig(mode="apply"))

    assert applied.diagnostics["snap_mode"] == 2.0
    assert np.array_equal(applied.observed, observed_network("aligned"))
    assert np.array_equal(applied.observed_raw, observed_network("shifted"))


# -- the algorithm on the bench -----------------------------------------------


def test_an_aligned_map_is_left_where_it_is(bench, mesh) -> None:
    aligned = observed_network("aligned")
    snap = _geometry(bench, mesh, aligned, SnapStreamsConfig(mode="diagnose")).snap

    assert np.array_equal(snap.snapped, aligned)
    assert np.all(snap.status[aligned] == SNAP_UNCHANGED)
    assert snap.displacement_p90_m == 0.0
    assert snap.length_ratio == pytest.approx(1.0)
    assert snap.connected_share == pytest.approx(1.0)
    assert snap.floor_m == pytest.approx(0.0)


@pytest.mark.parametrize("radius", ["1 cell", "2 cells"])
def test_a_shifted_map_lands_on_the_axis_one_cell_away(bench, mesh, radius) -> None:
    shifted = observed_network("shifted")
    snap = _geometry(bench, mesh, shifted, SnapStreamsConfig(mode="apply", radius=radius)).snap

    assert np.array_equal(snap.snapped, observed_network("aligned"))
    assert np.all(snap.status[shifted] == SNAP_MOVED)
    assert snap.displacement_m[shifted] == pytest.approx(np.full(int(shifted.sum()), CELL_SIZE))
    assert snap.rejected_share == 0.0
    assert snap.within_bounds


def test_snapping_twice_is_snapping_once(bench, mesh) -> None:
    setting = SnapStreamsConfig(mode="apply")
    once = _geometry(bench, mesh, observed_network("shifted"), setting).snap.snapped
    twice = _geometry(bench, mesh, once, setting).snap.snapped

    assert np.array_equal(once, twice)


def test_a_radius_under_one_cell_moves_nothing(bench, mesh) -> None:
    shifted = observed_network("shifted")
    snap = _geometry(bench, mesh, shifted, SnapStreamsConfig(mode="diagnose", radius="5 m")).snap

    assert not np.any(snap.status == SNAP_MOVED)
    # Two cells at the foot of the column already drain into the outlet and
    # stay; everything above them has nothing within half a cell to attach to.
    assert int(np.count_nonzero(snap.status == SNAP_REJECTED)) == int(shifted.sum()) - 2
    assert np.array_equal(snap.snapped, shifted)
    assert not snap.within_bounds


def test_a_line_far_from_any_talweg_is_rejected_and_kept_raw(bench, mesh) -> None:
    far = np.zeros(N_CELLS, dtype=bool)
    far[[cell_id(row, AXIS_COL + 5) for row in range(12, N_ROWS)]] = True
    snap = _geometry(bench, mesh, far, SnapStreamsConfig(mode="diagnose")).snap

    assert snap.rejected_share == pytest.approx(1.0)
    assert np.array_equal(snap.snapped, far)
    assert np.isnan(snap.displacement_p90_m)


def test_a_gap_is_never_bridged(bench, mesh) -> None:
    hole = observed_network("hole")
    snap = _geometry(bench, mesh, hole, SnapStreamsConfig(mode="diagnose")).snap

    # No talweg cell is added: the reach above the gap attaches one cell lower
    # instead, and its displacement says so.
    assert int(snap.snapped.sum()) == int(hole.sum())
    assert snap.connected_share == pytest.approx(1.0)
    assert snap.displacement_p90_m == pytest.approx(CELL_SIZE)


def test_a_map_ending_upstream_of_the_outlet_is_not_extended(bench, mesh) -> None:
    truncated = observed_network("truncated")
    snap = _geometry(bench, mesh, truncated, SnapStreamsConfig(mode="diagnose")).snap

    # Nothing within two cells of its foot is attached to the outlet, so the
    # continuity rule places none of it: the map stays raw and says so.
    assert np.array_equal(snap.snapped, truncated)
    assert snap.rejected_share == pytest.approx(1.0)
    assert not snap.snapped[cell_id(OUTLET_ROW, AXIS_COL)]


def test_the_floor_of_a_one_column_shift_is_the_measured_one(bench, mesh) -> None:
    snap = _geometry(
        bench, mesh, observed_network("shifted"), SnapStreamsConfig(mode="diagnose")
    ).snap

    # D_so: the axis descends to the sealed outlet, 10 m per row over 49 rows,
    # a mean of 240 m. D_os: each shifted cell steps diagonally onto the axis,
    # 14.14 m, but the last one steps sideways, 10 m. F is their mean.
    expected = 0.5 * (240.0 + (48 * 10.0 * np.sqrt(2.0) + 10.0) / 49)
    assert snap.floor_m == pytest.approx(expected, rel=1e-9)
    assert snap.floor_m == pytest.approx(127.0, abs=0.1)


# -- a branched network --------------------------------------------------------


@pytest.fixture(scope="module")
def dendritic():
    """A noisy tilted valley whose D8 talwegs branch, and its talweg map."""
    n_rows, n_cols, size = 50, 40, 10.0
    rng = np.random.default_rng(7)
    rows = np.arange(n_rows)[:, None]
    cols = np.arange(n_cols)[None, :]
    surface = 1000.0 - 0.5 * rows + 0.3 * np.abs(cols - 20) + rng.normal(0.0, 0.1, (n_rows, n_cols))
    vertices, connectivity = quad_mesh(n_rows, n_cols, cell_size=size)
    options = {
        "topography": surface.reshape(-1),
        "face_node_connectivity": connectivity,
        "vertices": vertices,
        "cell_area_m2": np.full(n_rows * n_cols, size * size),
        "mean_recharge_m_s": 1e-8,
        "tau_specific_ratio": 0.0,
    }
    probe = build_network_geometry(observed=np.ones(n_rows * n_cols, dtype=bool), **options)
    drained = accumulate_on_downhill_graph(probe.metric.graph, np.ones(n_rows * n_cols))
    talwegs = (drained >= 30.0) & probe.catchment
    return options, talwegs, (n_rows, n_cols)


def test_a_branched_talweg_map_is_left_where_it_is(dendritic) -> None:
    options, talwegs, _ = dendritic
    snap = build_network_geometry(
        observed=talwegs, snap=SnapStreamsConfig(mode="apply"), **options
    ).snap

    assert np.array_equal(snap.snapped, talwegs)
    assert np.all(snap.status[talwegs] == SNAP_UNCHANGED)


def test_every_placed_cell_descends_to_the_outlet_through_placed_cells(dendritic) -> None:
    options, talwegs, (n_rows, n_cols) = dendritic
    shifted = np.roll(talwegs.reshape(n_rows, n_cols), 1, axis=1).reshape(-1)
    geometry = build_network_geometry(
        observed=shifted, snap=SnapStreamsConfig(mode="apply"), **options
    )
    snap = geometry.snap
    placed = np.zeros(shifted.size, dtype=bool)
    placed[snap.target[snap.target >= 0]] = True
    receivers = geometry.metric.graph.downstream
    for cell in np.flatnonzero(placed):
        steps = 0
        while cell != geometry.outlet:
            cell = int(receivers[cell])
            steps += 1
            assert cell >= 0 and placed[cell], "a placed cell left the placed map"
            assert steps < shifted.size
    # A one-column shift of a branched map is mostly placed.
    assert snap.rejected_share < 0.10
    assert np.count_nonzero(snap.status == SNAP_MERGED) <= 0.05 * int(snap.raw.sum())


def test_the_snap_is_logged(bench, mesh, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="hydromodpy.core.stream_geometry"):
        _geometry(bench, mesh, observed_network("shifted"), SnapStreamsConfig(mode="diagnose"))
    assert any("floor F" in record.getMessage() for record in caplog.records)
