"""The D8 code table must be the one the solver actually writes.

``WBT_D8_OFFSETS`` declared the ESRI encoding while Whitebox writes its own,
which is the same eight octants rotated by one. Nothing failed: every descent
walked beside the talweg instead of down it, and the flow paths stayed
plausible. The agreement ratio of the stream-network criterion sat near 0.45
whatever the burning depth, including on the network the DEM derives from its
own pointer, where it is 1.0 by construction.

Two tests, because either alone can be satisfied by a wrong table: one reads
back the code Whitebox writes on a plane tilted in a known direction, the other
checks that descending a network closed under descent adds no cell.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.geographic.core.d8 import WBT_D8_OFFSETS

pytest.importorskip("whitebox_workflows")
rasterio = pytest.importorskip("rasterio")

# Whitebox's native binding is not fork-safe under xdist distribution.
pytestmark = pytest.mark.xdist_group(name="whitebox_backend")

# Whitebox's non-ESRI pointer, clockwise from the north-east:
#     64 128   1
#     32   X   2
#     16   8   4
CARDINALS = {
    "east": ((0, 1), 2),
    "south": ((1, 0), 8),
    "west": ((0, -1), 32),
    "north": ((-1, 0), 128),
}


def _write_plane(path, drow: int, dcol: int, size: int = 40):
    """Write a DEM whose steepest descent is exactly ``(drow, dcol)`` everywhere."""
    from rasterio.transform import from_origin

    rows, cols = np.mgrid[0:size, 0:size]
    # Fall by one metre per cell in the wanted direction.
    surface = 100.0 - (drow * rows + dcol * cols)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        nodata=-9999.0,
        transform=from_origin(0.0, size * 25.0, 25.0, 25.0),
    ) as dst:
        dst.write(surface.astype("float32"), 1)
    return path


@pytest.fixture(scope="module")
def backend():
    from tests._helpers.whitebox import configure_whitebox_single_thread

    monkeypatch = pytest.MonkeyPatch()
    try:
        configure_whitebox_single_thread(monkeypatch)
        from hydromodpy.spatial.delineation import get_whitebox_backend

        yield get_whitebox_backend()
    finally:
        monkeypatch.undo()


@pytest.mark.parametrize("direction", sorted(CARDINALS))
def test_the_table_matches_the_code_whitebox_writes(direction, backend, tmp_path) -> None:
    offset, expected_code = CARDINALS[direction]
    dem = _write_plane(tmp_path / f"{direction}.tif", *offset)
    pointer = tmp_path / f"{direction}_direc.tif"
    backend.flow.d8_pointer(str(dem), str(pointer))

    with rasterio.open(pointer) as src:
        codes = src.read(1)
    # Drop the frame: an edge cell has no downslope neighbour to point at.
    inner = codes[5:-5, 5:-5]
    values, counts = np.unique(inner[inner > 0], return_counts=True)
    dominant = int(values[np.argmax(counts)])

    assert dominant == expected_code, (
        f"a plane falling {direction} is coded {dominant}, not {expected_code}"
    )
    assert WBT_D8_OFFSETS[expected_code] == offset, (
        f"the table maps {expected_code} to {WBT_D8_OFFSETS[expected_code]}, not {offset}"
    )


def test_a_network_closed_under_descent_adds_no_cell(backend, tmp_path) -> None:
    """The floor of a valley is its own downstream closure, so alpha is 1.

    This is the regression the rotated table failed: it measured 0.45 on a
    network that cannot, by construction, leave itself. The floor is used rather
    than a flow-accumulation threshold so the test depends on the pointer alone.
    """
    from rasterio.transform import from_origin

    from hydromodpy.spatial.geographic.core.stream_dem_agreement import (
        _d8_receivers,
        _downstream_closure,
    )

    size = 60
    floor = size // 2
    rows, cols = np.mgrid[0:size, 0:size]
    # A V-shaped valley draining south: every floor cell descends to the next
    # one down the column, so the floor is closed under descent.
    surface = 100.0 - rows * 0.5 + np.abs(cols - floor) * 2.0
    dem = tmp_path / "valley.tif"
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="float32",
        crs="EPSG:2154",
        nodata=-9999.0,
        transform=from_origin(0.0, size * 25.0, 25.0, 25.0),
    ) as dst:
        dst.write(surface.astype("float32"), 1)

    pointer = tmp_path / "direc.tif"
    backend.flow.d8_pointer(str(dem), str(pointer))
    with rasterio.open(pointer) as src:
        codes = src.read(1)

    network = cols == floor
    seeds = np.flatnonzero(network.ravel())

    closure = _downstream_closure(_d8_receivers(codes), seeds)
    assert int(closure.sum()) == seeds.size, (
        f"descending the valley floor added {int(closure.sum()) - seeds.size} cells; "
        "the floor is closed under descent"
    )
