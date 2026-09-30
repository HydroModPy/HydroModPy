"""Recharge keeps its RCHA name and header when EVTA gains the same machinery.

``externalize_recharge_spd`` grew a ``package`` parameter for the soil ETP
(EVTA); called without it (every non-soil model, and every model built before
this change) it must still name files ``*.rcha.<k>.bin`` / ``rcha_<digest>.<k>.bin``
and write the ``RECHARGE`` header, byte for byte.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from hydromodpy.solver.modflow6.builders.recharge import (
    RECHARGE_BINARY_MIN_PERIODS,
    externalize_recharge_spd,
)

_NCPL = 4
_NPER = RECHARGE_BINARY_MIN_PERIODS + 2


def _stack() -> dict[int, np.ndarray]:
    return {kper: np.full(_NCPL, 1.0e-8 * (kper + 1)) for kper in range(_NPER)}


def test_the_default_package_names_local_files_rcha() -> None:
    payload = externalize_recharge_spd(_stack(), basename="m")

    for kper, record in payload.items():
        assert record["filename"] == f"m.rcha.{kper}.bin"


def test_the_default_package_names_shared_files_rcha_and_writes_the_recharge_header(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "_shared_recharge"
    payload = externalize_recharge_spd(_stack(), basename="m", shared_dir=str(shared))

    for kper, record in payload.items():
        target = Path(record["filename"])
        assert target.name.startswith("rcha_")
        assert target.name.endswith(f".{kper}.bin")
        header_text = target.read_bytes()[24:40].decode("ascii")
        assert header_text.strip() == "RECHARGE"
