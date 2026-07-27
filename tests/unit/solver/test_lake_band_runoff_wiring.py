"""Auto-activation wiring of the exposed-band (marnage) runoff coupling."""

from __future__ import annotations

import pytest

from hydromodpy.physics.flow.sinks_sources.lake import BathymetryReconstructionConfig
from hydromodpy.solver.modflow6.builders import build_exposed_band_runoff_specs
from hydromodpy.solver.modflow_common.flow_adapter_helpers import resolve_modflow_runner


def test_exposed_band_runoff_requires_dynamic_area():
    with pytest.raises(ValueError, match="dynamic_area"):
        BathymetryReconstructionConfig(exposed_band_runoff=True)
    # With dynamic_area it validates.
    cfg = BathymetryReconstructionConfig(dynamic_area=True, exposed_band_runoff=True)
    assert cfg.exposed_band_runoff is True


class _Flow:
    def __init__(self, lakes):
        self.active_bc = ["lake"]
        self.sinks_sources = {"lakes": lakes}


class _Model:
    def __init__(self, lakes, reconstruction, marnage):
        self.flow = _Flow(lakes)
        self._lake_bed_reconstruction = reconstruction
        self._marnage_lake_ids = marnage


def _marnage_lake(*, exposed_band: bool):
    cfg = BathymetryReconstructionConfig(dynamic_area=True, exposed_band_runoff=exposed_band)
    payload = {
        "bed_reconstruction": cfg,
        "runoff_rate": {"kind": "values", "values": [2.0e-7, 2.0e-7]},
        "runoff": None,  # SFR-routed: no direct lake runoff volume
    }
    reconstruction = {
        "lac0": {
            "bed_by_cell": {0: 10.0, 1: 20.0, 2: 30.0},
            "area_by_cell": {0: 1.0e4, 1: 1.0e4, 2: 1.0e4},
        }
    }
    return _Model({"lac0": payload}, reconstruction, {"lac0"})


def test_build_specs_for_marnage_lake():
    model = _marnage_lake(exposed_band=True)
    specs = build_exposed_band_runoff_specs(model)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.lake_index == 0
    assert spec.pkg == "LAK"
    assert tuple(spec.rate_per_period) == (2.0e-7, 2.0e-7)
    assert tuple(spec.base_runoff_per_period) == ()  # SFR-routed: band is the only runoff
    # Drawn down to stage 25: beds 30 only exposed -> 1 cell.
    assert spec.runoff_at(25.0, 0) == pytest.approx(2.0e-7 * 1.0e4)


def test_build_specs_empty_without_flag():
    model = _marnage_lake(exposed_band=False)
    assert build_exposed_band_runoff_specs(model) == []


def test_resolve_runner_forces_api_with_specs():
    model = _marnage_lake(exposed_band=True)
    model._exposed_band_runoff_specs = build_exposed_band_runoff_specs(model)
    assert resolve_modflow_runner(model) == "api"

    class _Bare:
        pass

    assert resolve_modflow_runner(_Bare()) == "subprocess"
