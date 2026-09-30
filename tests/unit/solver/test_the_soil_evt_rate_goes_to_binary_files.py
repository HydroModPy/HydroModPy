"""A long soil-ETP chronicle is externalized to binary EVTA files, like RCHA.

Above the binary threshold FloPy would format every value of every period by
hand; ``build_soil_evta_payload`` routes the rate through
``externalize_recharge_spd(..., package="evta")`` instead, same as recharge does
for RCHA.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.builders.recharge import (
    RECHARGE_BINARY_MIN_PERIODS,
    build_soil_evta_payload,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_NCPL = 4
_NPER = RECHARGE_BINARY_MIN_PERIODS + 6


def _mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    botm = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float)
    return SolverMesh.from_structured_arrays(nrow=2, ncol=2, top=top, botm=np.stack([botm]))


def _model() -> SimpleNamespace:
    rng = np.random.default_rng(0)
    rate = {kper: rng.uniform(1.0e-9, 1.0e-8, size=_NCPL) for kper in range(_NPER)}
    return SimpleNamespace(
        ncpl=_NCPL,
        nper=_NPER,
        model_name_mf6="m",
        drain_band_depth_m=0.0,
        _soil_etp_rate=rate,
        _soil_evt_surface_offset_m=0.0,
        _soil_evt_extinction_depth_m=1.0,
    )


def _build(model: SimpleNamespace, *, shared_dir: str | None):
    return build_soil_evta_payload(
        model,
        _mesh(),
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=shared_dir,
    )


def test_per_model_files_are_named_after_the_evta_package() -> None:
    payload = _build(_model(), shared_dir=None)

    assert payload is not None
    rate, _, _ = payload
    assert set(rate) == set(range(_NPER))
    for kper, record in rate.items():
        assert record["filename"] == f"m.evta.{kper}.bin"
        assert "data" in record


def test_shared_files_are_content_hashed_and_carry_the_rate_header(tmp_path: Path) -> None:
    shared = tmp_path / "_shared_recharge"
    payload = _build(_model(), shared_dir=str(shared))

    assert payload is not None
    rate, _, _ = payload
    for kper, record in rate.items():
        target = Path(record["filename"])
        assert target.name.startswith("evta_")
        assert target.name.endswith(f".{kper}.bin")
        assert "data" not in record
        # MF6 head-file header: KSTP, KPER, PERTIM, TOTIM (4+4+8+8 B), then a
        # 16-byte TEXT field it ignores on read but a human can (MF6 6.7.0,
        # tests/integration/test_shared_recharge_equivalence.py:97-99).
        header_text = target.read_bytes()[24:40].decode("ascii")
        assert header_text.strip() == "RATE"
