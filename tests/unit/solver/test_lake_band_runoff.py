"""Unit tests for the exposed-band (marnage) runoff sizing (no live solver)."""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.modflow6.lake_band_runoff import (
    LakeBandRunoffSpec,
    exposed_band_area,
)

_BED = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
_AREA = np.full(5, 10000.0)


def test_exposed_band_area_grows_as_stage_drops():
    # Stage above every bed -> nothing exposed.
    assert exposed_band_area(_BED, _AREA, 60.0) == 0.0
    # Stage 35 -> beds 40 and 50 are exposed (>= stage) -> 2 cells.
    assert exposed_band_area(_BED, _AREA, 35.0) == 2 * 10000.0
    # Stage below every bed -> whole footprint exposed.
    assert exposed_band_area(_BED, _AREA, 5.0) == 5 * 10000.0


def test_runoff_at_adds_band_to_base():
    spec = LakeBandRunoffSpec(
        pkg="LAK",
        lake_index=0,
        bed=_BED,
        area=_AREA,
        rate_per_period=(2.0e-7, 2.0e-7),
        base_runoff_per_period=(1.0e-3, 1.0e-3),
    )
    # Period 0, full pool (stage 60): only the base runoff.
    assert spec.runoff_at(60.0, 0) == 1.0e-3
    # Period 1, drawn down (stage 35): base + rate * 20000.
    assert spec.runoff_at(35.0, 1) == 1.0e-3 + 2.0e-7 * 20000.0


def test_runoff_at_clamps_period_index_and_empty_rates():
    spec = LakeBandRunoffSpec(pkg=None, lake_index=0, bed=_BED, area=_AREA, rate_per_period=())
    # No rate and no base -> zero, and an out-of-range kper is clamped.
    assert spec.runoff_at(35.0, 99) == 0.0
