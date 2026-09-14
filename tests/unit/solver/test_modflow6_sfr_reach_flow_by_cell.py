"""Read the routed streamflow of the reach a gauge sits on.

Under SFR nothing is accumulated: MODFLOW routed the water, movers included, so
the reach under the station already carries the flow to compare.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors.sfr import reach_flow_by_cell

_SECONDS_PER_DAY = 86400.0

_PAYLOAD = {
    "obs_csv": "m.sfr.obs.csv",
    "network_id": "net0",
    "reach_count": 3,
    "entries": [
        {
            "obsname": "r0_downstream_flow",
            "network_id": "net0",
            "reach": 0,
            "quantity": "downstream_flow",
        },
        {
            "obsname": "r1_downstream_flow",
            "network_id": "net0",
            "reach": 1,
            "quantity": "downstream_flow",
        },
        {
            "obsname": "r2_downstream_flow",
            "network_id": "net0",
            "reach": 2,
            "quantity": "downstream_flow",
        },
        {"obsname": "r0_stage", "network_id": "net0", "reach": 0, "quantity": "stage"},
    ],
}


def _reach(ifno: int, cell2d: int | None) -> dict:
    return {
        "ifno": ifno,
        "layer": 0,
        "cell2d": cell2d,
        "rlen": 100.0,
        "rwid": 2.0,
        "rgrd": 0.001,
        "rtp": 10.0,
        "rbth": 0.5,
        "rhk": 1e-5,
        "manning": 0.03,
        "strahler": 1,
        "ustrf": 1.0,
    }


def _write_run(tmp_path: Path, *, reaches: list[dict], csv: str) -> Path:
    payload = dict(_PAYLOAD, reaches=reaches)
    (tmp_path / "m.sfr.meta.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "m.sfr.obs.csv").write_text(csv, encoding="utf-8")
    return tmp_path


_CSV = (
    "time,R0_DOWNSTREAM_FLOW,R1_DOWNSTREAM_FLOW,R2_DOWNSTREAM_FLOW,R0_STAGE\n"
    "86400.0,-864.0,-1728.0,-2592.0,95.25\n"
    "172800.0,-1728.0,-3456.0,-5184.0,95.30\n"
)


def _call(output_dir: Path) -> dict[int, np.ndarray] | None:
    return reach_flow_by_cell(
        output_dir,
        "m",
        times=[86400.0, 172800.0],
        seconds_per_time_unit=_SECONDS_PER_DAY,
    )


def _flows(output_dir: Path) -> dict[int, np.ndarray]:
    """The reader returns None to say 'no network'; these tests expect one."""
    by_cell = _call(output_dir)
    assert by_cell is not None
    return by_cell


def test_each_reach_cell_carries_its_own_routed_flow(tmp_path):
    run = _write_run(
        tmp_path,
        reaches=[_reach(0, 4), _reach(1, 5), _reach(2, 6)],
        csv=_CSV,
    )

    by_cell = _flows(run)

    assert set(by_cell) == {4, 5, 6}
    # -864 m3/d reported negative by MF6 -> +0.01 m3/s leaving the reach.
    assert by_cell[4] == pytest.approx([0.01, 0.02])
    assert by_cell[5] == pytest.approx([0.02, 0.04])
    assert by_cell[6] == pytest.approx([0.03, 0.06])


def test_a_reach_that_exchanges_with_no_cell_is_skipped(tmp_path):
    """cell2d is None for a reach carrying flow without touching the aquifer."""
    run = _write_run(
        tmp_path,
        reaches=[_reach(0, 4), _reach(1, None), _reach(2, 6)],
        csv=_CSV,
    )

    by_cell = _flows(run)

    assert set(by_cell) == {4, 6}


def test_the_most_downstream_reach_wins_a_shared_cell(tmp_path):
    """A gauge on a cell measures what leaves it, which is the larger flow."""
    run = _write_run(
        tmp_path,
        reaches=[_reach(0, 4), _reach(1, 4), _reach(2, 6)],
        csv=_CSV,
    )

    by_cell = _flows(run)

    assert by_cell[4] == pytest.approx([0.02, 0.04])


def test_a_run_without_an_sfr_sidecar_returns_nothing(tmp_path):
    """None is how the caller learns to route the release itself instead."""
    assert _call(tmp_path) is None


def test_a_sidecar_without_an_obs_csv_returns_nothing(tmp_path):
    (tmp_path / "m.sfr.meta.json").write_text(
        json.dumps(dict(_PAYLOAD, reaches=[_reach(0, 4)])), encoding="utf-8"
    )

    assert _call(tmp_path) is None


def test_a_network_whose_reaches_touch_no_cell_returns_nothing(tmp_path):
    run = _write_run(tmp_path, reaches=[_reach(0, None)], csv=_CSV)

    assert _call(run) is None


def test_the_series_is_truncated_to_the_solver_timesteps(tmp_path):
    run = _write_run(tmp_path, reaches=[_reach(0, 4)], csv=_CSV)

    by_cell = reach_flow_by_cell(run, "m", times=[86400.0], seconds_per_time_unit=_SECONDS_PER_DAY)

    assert np.asarray(by_cell[4]).size == 1
