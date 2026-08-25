"""Golden comparison of the numpy downslope operator against Whitebox.

The criterion measures a length along the flow paths of the DEM, and Whitebox
already ships such a tool. It is not the one used here, for reasons the second
test pins down: its D8 mode returns nothing usable, it is file-based and
single-threaded while trials run in a thread pool, it only handles regular
grids, and it lives behind an optional extra. The internal operator must
therefore stand on its own, and this test is what keeps it honest on real
terrain: D8 on the receiver graph and Whitebox D-infinity are different
operators, so the agreement is a rank correlation and a relative spread, never
an equality.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.topographic_distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
)
from tests._helpers.tolerances import tol
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.whitebox import configure_whitebox_single_thread

pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")
scipy_stats = pytest.importorskip("scipy.stats")

# Whitebox's native binding is not fork-safe under xdist distribution.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM_PATH = REPO_ROOT / "examples" / "data" / "dem" / "DEM_cheze_burned_75m.tif"

# One channel head per 1.1 km2 on a 75 m grid: dense enough to leave a large
# comparison set, sparse enough that the distances are not all one cell.
STREAM_THRESHOLD_CELLS = 200.0

RANK_CORRELATION = tol("spearman_rank_correlation")
RELATIVE_GAP = tol("median_relative_gap")


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as source:
        values = source.read(1).astype("float64")
        nodata = source.nodata
    return np.where(values == nodata, np.nan, values) if nodata is not None else values


@pytest.fixture(scope="module")
def downslope_fields(tmp_path_factory):
    """Condition the DEM once, then run both operators on that same surface."""
    if not DEM_PATH.exists():
        pytest.skip(f"reference DEM not available: {DEM_PATH}")

    from hydromodpy.spatial.delineation import get_whitebox_backend

    workspace = tmp_path_factory.mktemp("downslope_whitebox")
    monkeypatch = pytest.MonkeyPatch()
    try:
        configure_whitebox_single_thread(monkeypatch)
        backend = get_whitebox_backend()

        filled_path = workspace / "filled.tif"
        backend.flow.fill_depressions(str(DEM_PATH), str(filled_path))
        filled = _read(filled_path)

        accumulation_path = workspace / "accumulation.tif"
        backend.flow.d8_flow_accumulation(str(filled_path), str(accumulation_path), log=False)
        streams = _read(accumulation_path) >= STREAM_THRESHOLD_CELLS

        with rasterio.open(filled_path) as source:
            profile = source.profile
            cell_size = abs(source.transform.a)
        profile.update(dtype="float64", nodata=-9999.0, count=1)
        streams_path = workspace / "streams.tif"
        with rasterio.open(streams_path, "w", **profile) as destination:
            destination.write(streams.astype("float64"), 1)

        whitebox = {}
        for use_dinf in (True, False):
            output = workspace / f"distance_dinf_{use_dinf}.tif"
            backend.flow.downslope_distance_to_stream(
                str(filled_path), str(streams_path), str(output), use_dinf=use_dinf
            )
            whitebox[use_dinf] = _read(output).reshape(-1)
    finally:
        monkeypatch.undo()

    n_rows, n_cols = filled.shape
    vertices, connectivity = quad_mesh(n_rows, n_cols, cell_size=cell_size)
    metric = build_downslope_metric(
        filled.reshape(-1),
        connectivity,
        vertices=vertices,
        inactive_mask=~np.isfinite(filled).reshape(-1),
        diagonal_neighbors=True,
    )
    return {
        "numpy": downslope_distance_to_mask(metric, streams.reshape(-1)),
        "whitebox_dinf": whitebox[True],
        "whitebox_d8": whitebox[False],
        "n_stream_cells": int(streams.sum()),
        "n_active": int(metric.graph.active.sum()),
    }


def test_numpy_operator_agrees_with_whitebox_d_infinity(downslope_fields) -> None:
    ours = downslope_fields["numpy"]
    theirs = downslope_fields["whitebox_dinf"]
    compared = np.isfinite(ours) & np.isfinite(theirs) & (ours > 0.0) & (theirs > 0.0)
    assert int(compared.sum()) > 20_000, int(compared.sum())

    ours = ours[compared]
    theirs = theirs[compared]
    assert scipy_stats.spearmanr(ours, theirs).statistic >= RANK_CORRELATION

    relative_gap = np.abs(ours - theirs) / theirs
    assert float(np.median(relative_gap)) <= RELATIVE_GAP

    # The tail matters more than the mean here: a handful of long branches
    # carry most of the criterion, so the p90 is checked as well. Measured on
    # this DEM: 1.068 on the mean, 1.071 on the median, 1.057 on the p90. D8
    # quantizes every step to eight directions and walks the longer path, but
    # that holds cell by cell, not necessarily on an aggregate over a changing
    # set of cells, so only the two-sided bound is asserted.
    for statistic in (np.mean, np.median, lambda values: np.percentile(values, 90)):
        ratio = float(statistic(ours) / statistic(theirs))
        assert abs(ratio - 1.0) <= RELATIVE_GAP, ratio


def test_whitebox_d8_mode_yields_no_usable_distance(downslope_fields) -> None:
    # In whitebox_workflows 1.3.5 the D8 mode only scores cells that already
    # belong to the stream, and it scores them zero. A port that reads the
    # criterion off this call gets D_so = D_os = 0 at every iteration, a cost
    # independent of K, and a silent convergence. That is the single reason the
    # operator is written in numpy rather than delegated.
    d8 = downslope_fields["whitebox_d8"]
    dinf = downslope_fields["whitebox_dinf"]

    scored = np.isfinite(d8) & (d8 >= 0.0)
    assert int(np.sum(scored & (d8 > 0.0))) == 0
    assert int(scored.sum()) == downslope_fields["n_stream_cells"]

    # The D-infinity mode, on the other hand, scores most of the domain.
    assert int(np.sum(np.isfinite(dinf) & (dinf > 0.0))) > 40_000

    # And so does the internal operator, on the same surface.
    ours = downslope_fields["numpy"]
    assert int(np.sum(np.isfinite(ours) & (ours > 0.0))) > 20_000
