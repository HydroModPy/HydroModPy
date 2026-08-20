"""Unit tests for the lake-bed reconstruction core (regrid, reconcile, carve)."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.lake_bed import (
    cell_bed_from_surface,
    reconcile_bed_to_abacus,
    regrade_column_active_top,
    regrade_column_to_bed,
    simulate_abacus,
)
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface


class _QuadMesh:
    """Minimal planar-mesh stand-in: regular quad grid over a rectangle."""

    def __init__(self, *, xmin, ymin, dx, dy, ncol, nrow):
        xs = xmin + dx * np.arange(ncol + 1)
        ys = ymin + dy * np.arange(nrow + 1)
        verts = []
        vid = {}
        for j in range(nrow + 1):
            for i in range(ncol + 1):
                vid[(i, j)] = len(verts)
                verts.append((xs[i], ys[j]))
        conn = []
        for j in range(nrow):
            for i in range(ncol):
                conn.append([vid[(i, j)], vid[(i + 1, j)], vid[(i + 1, j + 1)], vid[(i, j + 1)]])
        self.vertices = np.asarray(verts, dtype=float)
        self.flat_connectivity = np.asarray(conn, dtype=int)


def _ramp_surface(*, xmin=0.0, ymin=0.0, extent=100.0, n=100):
    """Fine raster of the plane z = x (north-up array)."""
    dx = extent / n
    cols = xmin + (np.arange(n) + 0.5) * dx
    values = np.tile(cols, (n, 1))  # z depends only on x
    support = RasterSupport(
        crs=None,
        dx=dx,
        dy=extent / n,
        xmin=xmin,
        xmax=xmin + extent,
        ymin=ymin,
        ymax=ymin + extent,
        nrows=n,
        ncols=n,
        nodata=None,
    )
    return Surface(name="bathy", values=values, support=support)


def test_zonal_regrid_matches_cell_mean():
    """Zonal mean of z=x over each coarse cell equals the cell-centre x."""
    mesh = _QuadMesh(xmin=0.0, ymin=0.0, dx=50.0, dy=50.0, ncol=2, nrow=2)
    surface = _ramp_surface(extent=100.0, n=200)
    bed = cell_bed_from_surface(planar_mesh=mesh, surface=surface, cell_ids=[0, 1, 2, 3])
    # cells 0,2 are the left column (x in [0,50] -> mean 25); 1,3 right (mean 75).
    assert bed[0] == pytest.approx(25.0, abs=0.5)
    assert bed[1] == pytest.approx(75.0, abs=0.5)
    assert bed[2] == pytest.approx(25.0, abs=0.5)
    assert bed[3] == pytest.approx(75.0, abs=0.5)


def test_reconcile_constant_sarea_gives_flat_bed():
    """A prismatic abacus (constant sarea) carves a flat bottom at the lowest stage."""
    n = 40
    bed_by_cell = {i: float(i) for i in range(n)}  # arbitrary distinct depths
    area_by_cell = {i: 1000.0 for i in range(n)}
    stage = [91.0, 93.0, 95.0, 97.0, 99.0]
    sarea = [40000.0] * 5
    carved, info = reconcile_bed_to_abacus(
        bed_by_cell=bed_by_cell,
        area_by_cell=area_by_cell,
        abacus_stage=stage,
        abacus_sarea=sarea,
    )
    values = np.array(list(carved.values()))
    assert np.allclose(values, 91.0)
    assert info["area_scale"] == pytest.approx(40000.0 / 40000.0)


def test_reconcile_reproduces_abacus_volume_and_area():
    """The simulated abacus of the carved bed matches the target abacus closely."""
    n_cells = 200
    a = 1.0
    a_top = n_cells * a
    stage = np.linspace(0.0, 10.0, 51)
    sarea = a_top * (stage / 10.0)  # area grows linearly with stage (cone-like)
    bed_by_cell = {i: float(i) for i in range(n_cells)}  # distinct regridded depths
    area_by_cell = {i: a for i in range(n_cells)}

    carved, info = reconcile_bed_to_abacus(
        bed_by_cell=bed_by_cell,
        area_by_cell=area_by_cell,
        abacus_stage=stage,
        abacus_sarea=sarea,
    )
    assert info["area_scale"] == pytest.approx(1.0)

    sim = simulate_abacus(bed_by_cell=carved, area_by_cell=area_by_cell, stages=stage)
    # Wetted area matches to about one cell of granularity.
    assert np.max(np.abs(sim["sarea"] - sarea)) <= 2.0 * a
    # Volume curve matches with high Nash-Sutcliffe efficiency.
    target_vol = a_top * (stage**2) / 20.0
    denom = np.sum((target_vol - np.mean(target_vol)) ** 2)
    nse = 1.0 - np.sum((sim["volume"] - target_vol) ** 2) / denom
    assert nse > 0.999


def test_regrade_column_monotone_and_anchored():
    """Carving sets botm[occ-1]=bed, keeps strict monotonic column and fixed base."""
    top = 100.0
    botm = np.array([90.0, 80.0, 70.0, 60.0, 50.0])
    new = regrade_column_to_bed(
        top=top, botm_col=botm, bed=85.0, occupied_layers=1, min_thickness=0.1
    )
    assert new[0] == pytest.approx(85.0)  # bed at bottom of the single occupied layer
    assert new[-1] == pytest.approx(50.0)  # aquifer base unchanged
    assert np.all(np.diff(new) < 0.0)  # strictly decreasing
    assert np.all(new < top)


def test_regrade_column_deep_bed_stays_valid():
    """A bed deeper than the original layering still yields a valid column."""
    top = 100.0
    botm = np.array([90.0, 80.0, 70.0, 60.0, 50.0])
    new = regrade_column_to_bed(
        top=top, botm_col=botm, bed=55.0, occupied_layers=2, min_thickness=0.1
    )
    assert new[1] == pytest.approx(55.0)  # bed at bottom of the 2 occupied layers
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)


def test_regrade_column_clamps_below_base():
    """A bed below the aquifer base is clamped above it by min_thickness."""
    top = 100.0
    botm = np.array([90.0, 80.0, 50.0])
    new = regrade_column_to_bed(
        top=top, botm_col=botm, bed=10.0, occupied_layers=1, min_thickness=1.0
    )
    assert new[0] >= 50.0 + 1.0 - 1e-9
    assert np.all(np.diff(new) < 0.0)


def test_regrade_holds_min_thickness_on_every_layer():
    """The floor is per layer, not just per segment.

    ``[90, 80, 50]`` re-graded into the 2 m active segment left by a clamped bed
    used to be split 0.5 m / 1.5 m in proportion to the original 10 m / 30 m: the
    segment held its aggregate floor while one layer fell under it.
    """
    top = 100.0
    botm = np.array([90.0, 80.0, 50.0])
    min_thickness = 1.0
    new = regrade_column_to_bed(
        top=top, botm_col=botm, bed=10.0, occupied_layers=1, min_thickness=min_thickness
    )
    thickness = np.concatenate(([top], new[:-1])) - new
    assert np.all(thickness >= min_thickness - 1e-9)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)


def test_regrade_active_top_holds_min_thickness_on_every_layer():
    """Same floor guarantee on the active-littoral (marnage) re-grade."""
    min_thickness = 1.0
    botm = np.array([90.0, 80.0, 50.0])
    new_top, new = regrade_column_active_top(
        orig_top=100.0, botm_col=botm, bed=10.0, min_thickness=min_thickness
    )
    thickness = np.concatenate(([new_top], new[:-1])) - new
    assert np.all(thickness >= min_thickness - 1e-9)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)


def test_regrade_keeps_the_original_shape_when_there_is_room():
    """With room to spare the split still follows the original thicknesses."""
    top = 100.0
    botm = np.array([90.0, 60.0, 0.0])
    new = regrade_column_to_bed(
        top=top, botm_col=botm, bed=90.0, occupied_layers=1, min_thickness=0.01
    )
    thickness = np.concatenate(([top], new[:-1])) - new
    # The active segment keeps the 30 / 60 proportion of the original column.
    assert thickness[2] / thickness[1] == pytest.approx(2.0, rel=1e-3)


def test_simulate_abacus_basic():
    """Flooding two cells gives the analytic volume and wetted area."""
    bed = {0: 0.0, 1: 5.0}
    area = {0: 100.0, 1: 100.0}
    sim = simulate_abacus(bed_by_cell=bed, area_by_cell=area, stages=[0.0, 5.0, 10.0])
    assert sim["sarea"].tolist() == [0.0, 100.0, 200.0]
    # at z=10: cell0 depth 10 -> 1000, cell1 depth 5 -> 500
    assert sim["volume"].tolist() == [0.0, 500.0, 1500.0]
