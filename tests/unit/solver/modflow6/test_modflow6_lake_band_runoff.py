"""Runoff (m3/s) from the band of a lake bed exposed when the stage drops.

A lake with a bed reconstruction and a drawdown (marnage) sheds runoff over the
cells whose bed (m) lies above the stage. The runoff is a rate per unit area (m/s)
times the exposed area (m2), added to any base runoff. It needs the API runner.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.sinks_sources.lake import BathymetryReconstructionConfig
from hydromodpy.solver.modflow6.builders.lake import build_exposed_band_runoff_specs
from hydromodpy.solver.modflow6.support.lake_band_runoff import (
    LakeBandRunoffSpec,
    exposed_band_area,
)
from hydromodpy.solver.modflow_common.flow_run import resolve_modflow_runner
from tests._helpers.model_factory import make_model

BED = np.array([10.0, 20.0, 30.0, 40.0, 50.0])  # m
AREA = np.full(5, 10000.0)  # m2 per cell

EXPOSED_AREAS = [
    pytest.param(60.0, 0.0, id="stage above every bed"),
    pytest.param(35.0, 2 * 10000.0, id="two beds above the stage"),
    pytest.param(5.0, 5 * 10000.0, id="stage below every bed"),
]


@pytest.mark.parametrize(("stage", "area"), EXPOSED_AREAS)
def test_exposed_band_area(stage, area) -> None:
    assert exposed_band_area(BED, AREA, stage) == area


def test_runoff_adds_the_band_to_the_base() -> None:
    spec = LakeBandRunoffSpec(
        pkg="LAK",
        lake_index=0,
        bed=BED,
        area=AREA,
        rate_per_period=(2.0e-7, 2.0e-7),
        base_runoff_per_period=(1.0e-3, 1.0e-3),
    )

    assert spec.runoff_at(60.0, 0) == 1.0e-3  # full pool, base runoff only
    assert spec.runoff_at(35.0, 1) == 1.0e-3 + 2.0e-7 * 20000.0  # two cells exposed


def test_runoff_clamps_the_period_and_has_no_default_rate() -> None:
    spec = LakeBandRunoffSpec(pkg=None, lake_index=0, bed=BED, area=AREA, rate_per_period=())

    assert spec.runoff_at(35.0, 99) == 0.0


def test_exposed_band_runoff_requires_dynamic_area() -> None:
    with pytest.raises(ValueError, match="dynamic_area"):
        BathymetryReconstructionConfig(exposed_band_runoff=True)

    config = BathymetryReconstructionConfig(dynamic_area=True, exposed_band_runoff=True)
    assert config.exposed_band_runoff is True


class Model:
    def __init__(self, lakes, reconstruction, marnage):
        self.inputs = make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            lakes=lakes,
        )
        self._lake_bed_reconstruction = reconstruction
        self._marnage_lake_ids = marnage
        self._exposed_band_runoff_specs = None

    def required_runner(self) -> str:
        """The dispatch MODFLOW 6 declares, as the real model declares it."""
        return "api" if self._exposed_band_runoff_specs else "subprocess"


def marnage_lake(*, exposed_band: bool) -> Model:
    config = BathymetryReconstructionConfig(dynamic_area=True, exposed_band_runoff=exposed_band)
    payload = {
        "bed_reconstruction": config,
        "runoff_rate": {"kind": "values", "values": [2.0e-7, 2.0e-7]},
        "runoff": None,  # SFR-routed, so no direct lake runoff volume
    }
    reconstruction = {
        "lac0": {
            "bed_by_cell": {0: 10.0, 1: 20.0, 2: 30.0},
            "area_by_cell": {0: 1.0e4, 1: 1.0e4, 2: 1.0e4},
        }
    }
    return Model({"lac0": payload}, reconstruction, {"lac0"})


def test_specs_of_a_marnage_lake() -> None:
    (spec,) = build_exposed_band_runoff_specs(marnage_lake(exposed_band=True))

    assert spec.lake_index == 0
    assert spec.pkg == "LAK"
    assert tuple(spec.rate_per_period) == (2.0e-7, 2.0e-7)
    assert tuple(spec.base_runoff_per_period) == ()  # the band is the only runoff
    # Drawn down to stage 25 m, only the 30 m bed is exposed: one cell.
    assert spec.runoff_at(25.0, 0) == pytest.approx(2.0e-7 * 1.0e4)


def test_no_specs_without_the_flag() -> None:
    assert build_exposed_band_runoff_specs(marnage_lake(exposed_band=False)) == []


def test_specs_force_the_api_runner() -> None:
    model = marnage_lake(exposed_band=True)
    model._exposed_band_runoff_specs = build_exposed_band_runoff_specs(model)

    assert resolve_modflow_runner(model) == "api"

    class Bare:
        """A backend that declares no dispatch, as MODFLOW-NWT does."""

    assert resolve_modflow_runner(Bare()) == "subprocess"
