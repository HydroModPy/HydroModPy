"""The hillslope drainage descends the preprocessing D8 pointer, not the raw top.

The pointer is computed on the BREACHED routing DEM, so every cell holds a path
to the outlet. Rebuilding a descent on the mesh top instead walks the raw DEM
over face neighbours only: one closed depression ends the path and strands its
whole upstream area. Measured on the Nancon at 25 m, that reached 26 per cent of
the hillslope cells against 100 per cent with the pointer.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders._sfr_drainage import receiver_from_d8_pointer
from hydromodpy.spatial.geographic.core.d8 import WBT_D8_OFFSETS

rasterio = pytest.importorskip("rasterio")

# A 3x3 grid of 10 m cells whose north-west corner is at (0, 30).
_TRANSFORM = rasterio.transform.from_origin(0.0, 30.0, 10.0, 10.0)
_CENTROIDS = np.array(
    [[5.0, 25.0], [15.0, 25.0], [25.0, 25.0]]
    + [[5.0, 15.0], [15.0, 15.0], [25.0, 15.0]]
    + [[5.0, 5.0], [15.0, 5.0], [25.0, 5.0]]
)


def _write_pointer(tmp_path, codes: np.ndarray, transform=_TRANSFORM):
    path = tmp_path / "direc.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=codes.shape[0],
        width=codes.shape[1],
        count=1,
        dtype="int16",
        transform=transform,
        crs="EPSG:2154",
    ) as dst:
        dst.write(codes.astype("int16"), 1)
    return path


def test_every_octant_lands_on_the_neighbour_the_table_names(tmp_path):
    # The centre cell is pointed at each octant in turn. A table rotated by one
    # octant would still produce a plausible descent, so each is checked apart.
    for code, (drow, dcol) in WBT_D8_OFFSETS.items():
        codes = np.zeros((3, 3), dtype="int16")
        codes[1, 1] = code
        receiver = receiver_from_d8_pointer(_write_pointer(tmp_path, codes), _CENTROIDS, 9)

        expected = (1 + drow) * 3 + (1 + dcol)
        assert receiver[4] == expected, f"code {code} should point at cell {expected}"


def test_a_pit_and_a_nodata_have_no_receiver(tmp_path):
    codes = np.zeros((3, 3), dtype="int16")
    codes[1, 1] = 0  # WBT writes 0 on a pit
    codes[0, 0] = -32768  # nodata

    receiver = receiver_from_d8_pointer(_write_pointer(tmp_path, codes), _CENTROIDS, 9)

    assert receiver[4] == -1
    assert receiver[0] == -1


def test_a_descent_leaving_the_raster_has_no_receiver(tmp_path):
    codes = np.zeros((3, 3), dtype="int16")
    codes[0, 1] = 128  # north, off the top row

    receiver = receiver_from_d8_pointer(_write_pointer(tmp_path, codes), _CENTROIDS, 9)

    assert receiver[1] == -1


class TestItRefusesRatherThanGuess:
    """A partial answer would strand cells silently; None sends the caller back."""

    def test_a_cell_outside_the_raster(self, tmp_path):
        codes = np.zeros((3, 3), dtype="int16")
        outside = np.vstack([_CENTROIDS, [[1000.0, 1000.0]]])

        assert receiver_from_d8_pointer(_write_pointer(tmp_path, codes), outside, 10) is None

    def test_two_cells_sharing_one_pixel(self, tmp_path):
        codes = np.zeros((3, 3), dtype="int16")
        # A refined mesh: four cells inside the same 10 m pixel.
        doubled = np.array([[2.5, 27.5], [7.5, 27.5], [2.5, 22.5], [7.5, 22.5]])

        assert receiver_from_d8_pointer(_write_pointer(tmp_path, codes), doubled, 4) is None

    def test_a_south_up_transform(self, tmp_path):
        # The offset table counts rows southward. A flipped grid would send every
        # descent one octant off, which looks plausible and is wrong.
        flipped = rasterio.transform.from_origin(0.0, 0.0, 10.0, -10.0)
        codes = np.zeros((3, 3), dtype="int16")

        assert (
            receiver_from_d8_pointer(_write_pointer(tmp_path, codes, flipped), _CENTROIDS, 9)
            is None
        )
