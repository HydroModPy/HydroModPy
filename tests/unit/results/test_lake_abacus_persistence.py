"""Lake abacus comparison persistence: build sidecar -> extractor -> per-sim Zarr."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow6.build import _write_lake_abacus_meta
from hydromodpy.solver.modflow6.extractors.lake import read_lake_abacus

_STAGE = [20.0, 30.0, 40.0, 50.0, 60.0]
_REAL_VOL = [0.0, 12500.0, 50000.0, 112500.0, 200000.0]
_REAL_SAREA = [0.0, 2500.0, 5000.0, 7500.0, 10000.0]


def test_lake_abacus_zarr_roundtrip(tmp_path: Path) -> None:
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    sz.write_lake_abacus(
        "lac0",
        stage=_STAGE,
        real_volume=_REAL_VOL,
        real_sarea=_REAL_SAREA,
        sim_volume=_REAL_VOL,
        sim_sarea=_REAL_SAREA,
    )
    sz.close()

    reopened = SimulationZarr(tmp_path / "sim.zarr")
    try:
        assert reopened.lake_abacus_lakes() == ["lac0"]
        ab = reopened.read_lake_abacus("lac0")
        assert np.allclose(ab["stage"], _STAGE)
        assert np.allclose(ab["real_volume"], _REAL_VOL)
        assert np.allclose(ab["sim_sarea"], _REAL_SAREA)
        assert ab["volume_unit"] == "m3"
    finally:
        reopened.close()


class _Model:
    def __init__(self, full_path: Path, reconstruction: dict):
        self.full_path = str(full_path)
        self.model_output_name = "mymodel"
        self._lake_bed_reconstruction = reconstruction


def test_lake_abacus_sidecar_roundtrip(tmp_path: Path) -> None:
    reconstruction = {
        "lac0": {
            "abacus_stage": _STAGE,
            "abacus_volume": _REAL_VOL,
            "abacus_sarea": _REAL_SAREA,
            "sim_volume": _REAL_VOL,
            "sim_sarea": _REAL_SAREA,
        },
        # A lake without a simulated abacus (no reconcile) is skipped.
        "lac1": {"abacus_stage": None, "sim_volume": None, "abacus_volume": None},
    }
    model = _Model(tmp_path, reconstruction)
    _write_lake_abacus_meta(model)

    spec = read_lake_abacus(tmp_path / "mymodel.lake_abacus.json")
    assert spec is not None
    assert [e.lake_id for e in spec.entries] == ["lac0"]
    entry = spec.entries[0]
    assert entry.stage == _STAGE
    assert entry.sim_volume == _REAL_VOL


def test_lake_abacus_sidecar_absent_is_none(tmp_path: Path) -> None:
    assert read_lake_abacus(tmp_path / "missing.lake_abacus.json") is None


def test_lake_abacus_meta_noop_without_reconstruction(tmp_path: Path) -> None:
    model = _Model(tmp_path, {})
    _write_lake_abacus_meta(model)
    assert not (tmp_path / "mymodel.lake_abacus.json").exists()
