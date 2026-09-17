"""A MODFLOW dry/no-flow sentinel is NaN by the time it is stored.

``mask_sentinels`` had no test. It is the reason the extensive NWT regression
golden went stale: that golden, published 2026-07-12, counts 1 497 cells
carrying a sentinel in ``concentration_seepage`` and ``mass_seepage``, and
since ``f62a14c62`` (2026-07-25) those cells reach Zarr as NaN, so the count
is 0. Refreshing the golden without covering the behaviour would leave the
new 0 guarded by nothing but a six-minute nightly run nobody reads.

The three write entry points each mask, because a field can arrive by any of
them: per timestep, as a stack, or without a time axis.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.results.zarr_store import SimulationZarr

HDRY = -1.0e30
HNOFLO = 1.0e30
MF_PACKAGE_DRY = -6.0e30


@pytest.fixture
def fresh_store(tmp_path: Path):
    store = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=6, n_layers=1)
    yield store
    store.close()


def test_the_three_modflow_sentinels_are_stored_as_nan(fresh_store: SimulationZarr) -> None:
    values = np.array([[1.5, HDRY, HNOFLO, MF_PACKAGE_DRY, -2.5, 0.0]], dtype="float64")

    fresh_store.write_field_stack("head", values)

    stored = np.asarray(fresh_store.root["head"][:])
    assert np.isnan(stored[0, 1:4]).all()
    np.testing.assert_array_equal(stored[0, [0, 4, 5]], [1.5, -2.5, 0.0])


def test_every_write_path_masks(fresh_store: SimulationZarr) -> None:
    """Per timestep, as a stack, and without a time axis."""
    sentinel_row = np.array([HNOFLO] * 6, dtype="float64")

    fresh_store.write_field("head", 0, sentinel_row, n_timesteps=1)
    fresh_store.write_field_stack("release_flux", sentinel_row[None, :], subgroup="derived")
    fresh_store.write_static_field("hydraulic_conductivity", sentinel_row, subgroup="derived")

    assert np.isnan(np.asarray(fresh_store.root["head"][:])).all()
    assert np.isnan(np.asarray(fresh_store.root["derived"]["release_flux"][:])).all()
    assert np.isnan(np.asarray(fresh_store.root["derived"]["hydraulic_conductivity"][:])).all()


def test_a_physical_value_at_the_threshold_survives(fresh_store: SimulationZarr) -> None:
    """The mask is a strict comparison: the threshold itself is kept."""
    values = np.array(
        [[SENTINEL_ABS_THRESHOLD, -SENTINEL_ABS_THRESHOLD, SENTINEL_ABS_THRESHOLD * 1.1]],
        dtype="float64",
    )

    fresh_store.write_field_stack("head", values, n_timesteps=1)

    stored = np.asarray(fresh_store.root["head"][:])
    assert stored[0, 0] == SENTINEL_ABS_THRESHOLD
    assert stored[0, 1] == -SENTINEL_ABS_THRESHOLD
    assert np.isnan(stored[0, 2])


def test_an_integer_field_keeps_its_values(fresh_store: SimulationZarr) -> None:
    """NaN is not an integer, so an integer array is returned untouched."""
    values = np.array([[0, 1, 2, 3, 4, 5]], dtype="int32")

    fresh_store.write_field_stack("seepage_mask", values, subgroup="derived")

    stored = np.asarray(fresh_store.root["derived"]["seepage_mask"][:])
    np.testing.assert_array_equal(stored, values)
