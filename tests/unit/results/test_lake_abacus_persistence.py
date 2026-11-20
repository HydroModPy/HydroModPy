"""Lake abacus persistence: volume (m3) and surface area (m2) against stage (m).

The builder writes a sidecar, the extractor reads it and the run keeps the curves in its Zarr.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow6.builders.lake import _write_lake_abacus_meta
from hydromodpy.solver.modflow6.extractors.lake import read_lake_abacus

_STAGE = [20.0, 30.0, 40.0, 50.0, 60.0]
_REAL_VOL = [0.0, 12500.0, 50000.0, 112500.0, 200000.0]
_REAL_SAREA = [0.0, 2500.0, 5000.0, 7500.0, 10000.0]


def test_zarr_roundtrip(tmp_path: Path) -> None:
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


def test_sidecar_roundtrip(tmp_path: Path) -> None:
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


def test_no_sidecar_without_reconstruction(tmp_path: Path) -> None:
    model = _Model(tmp_path, {})
    _write_lake_abacus_meta(model)
    assert not (tmp_path / "mymodel.lake_abacus.json").exists()


def test_curves_of_different_lengths(tmp_path: Path) -> None:
    # Five arrays share the stage_level axis of one Zarr group and must agree on its size.
    # Refusing at the write names the lake and the lengths, where a store would not open.
    sz = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=4, n_layers=1)
    try:
        with pytest.raises(ValueError, match="different lengths"):
            sz.write_lake_abacus(
                "lac0",
                stage=_STAGE,
                real_volume=_REAL_VOL,
                real_sarea=_REAL_SAREA,
                sim_volume=_REAL_VOL[:3],
                sim_sarea=_REAL_SAREA[:3],
            )
        assert "lake_abacus" not in sz.root
    finally:
        sz.close()
