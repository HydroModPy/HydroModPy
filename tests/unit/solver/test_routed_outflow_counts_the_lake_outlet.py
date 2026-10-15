"""The routed outflow is one definition: reach ext-outflow plus lake ext-outflow.

A network whose reaches end in a lake has no ext-outflow of its own: the water
leaves through the lake outlet. A series of zeros must never pass for a flow.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.solver.modflow6.extractors.sfr import routed_outflow_series

TIMES = [86400.0, 172800.0, 259200.0]


def _write_run(root: Path, *, reach_out: list[float], lake_out: list[float] | None) -> None:
    """Write the SFR (and optional LAK) sidecars and obs CSVs of a tiny run."""
    sfr_meta = {
        "obs_csv": "m.sfr.obs.csv",
        "network_id": "n",
        "reach_count": 1,
        "entries": [
            {"obsname": "R1_EXT", "network_id": "n", "reach": 1, "quantity": "ext_outflow"}
        ],
        "reaches": [],
    }
    (root / "m.sfr.meta.json").write_text(json.dumps(sfr_meta), encoding="utf-8")
    lines = ["time,R1_EXT"] + [f"{t},{-v}" for t, v in zip(TIMES, reach_out, strict=True)]
    (root / "m.sfr.obs.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if lake_out is None:
        return
    lak_meta = {
        "obs_csv": "m.lak.obs.csv",
        "entries": [{"obsname": "L1_EXT_1", "lake_id": "l1", "quantity": "ext_outflow"}],
    }
    (root / "m.lak.meta.json").write_text(json.dumps(lak_meta), encoding="utf-8")
    lines = ["time,L1_EXT_1"] + [f"{t},{-v}" for t, v in zip(TIMES, lake_out, strict=True)]
    (root / "m.lak.obs.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_reaches_ending_in_a_lake_count_the_lake_outlet(tmp_path: Path) -> None:
    _write_run(tmp_path, reach_out=[0.0, 0.0, 0.0], lake_out=[0.042, 0.045, 0.047])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    assert series is not None
    np.testing.assert_allclose(series, [0.042, 0.045, 0.047])


def test_reach_and_lake_outflows_add_up(tmp_path: Path) -> None:
    _write_run(tmp_path, reach_out=[0.5, 0.5, 0.5], lake_out=[0.1, 0.2, 0.3])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    np.testing.assert_allclose(series, [0.6, 0.7, 0.8])


def test_a_series_of_zeros_is_refused(tmp_path: Path) -> None:
    _write_run(tmp_path, reach_out=[0.0, 0.0, 0.0], lake_out=None)
    with pytest.raises(ObservableNotAvailableError, match="zero"):
        routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
