"""Unit tests for the SFR obs-CSV extractor (signs, units, re-keying).

The routed outflow is one definition: reach ext-outflow plus lake ext-outflow.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.solver.modflow6.extractors.sfr import (
    SfrObsSpec,
    build_sfr_columns,
    routed_outflow_series,
    sfr_station_id,
)

_SPEC_PAYLOAD = {
    "obs_csv": "m.sfr.obs.csv",
    "network_id": "net0",
    "reach_count": 2,
    "entries": [
        {"obsname": "r0_stage", "network_id": "net0", "reach": 0, "quantity": "stage"},
        {
            "obsname": "r0_downstream_flow",
            "network_id": "net0",
            "reach": 0,
            "quantity": "downstream_flow",
        },
        {
            "obsname": "r0_gw_exchange",
            "network_id": "net0",
            "reach": 0,
            "quantity": "gw_exchange",
        },
        {
            "obsname": "r1_ext_outflow",
            "network_id": "net0",
            "reach": 1,
            "quantity": "ext_outflow",
        },
        {"obsname": "r1_from_mvr", "network_id": "net0", "reach": 1, "quantity": "from_mvr"},
        {
            "obsname": "r1_gw_exchange",
            "network_id": "net0",
            "reach": 1,
            "quantity": "gw_exchange",
        },
    ],
}


def _write_csv(path: Path) -> None:
    path.write_text(
        "time,R0_STAGE,R0_DOWNSTREAM_FLOW,R0_GW_EXCHANGE,R1_EXT_OUTFLOW,R1_FROM_MVR,"
        "R1_GW_EXCHANGE\n"
        "86400.0,95.25,-4320.0,864.0,-3456.0,1728.0,-432.0\n",
        encoding="utf-8",
    )


def _by_key(columns: dict[str, np.ndarray]) -> dict[tuple[str, str, int], dict]:
    out: dict[tuple[str, str, int], dict] = {}
    times = columns.get("time")
    for row in range(len(columns["value"])):
        key = (
            str(columns["station_id"][row]),
            str(columns["variable"][row]),
            int(columns["timestep"][row]),
        )
        out[key] = {
            "value": float(columns["value"][row]),
            "unit": str(columns["unit"][row]),
            "time": None if times is None else times[row],
        }
    return out


def test_build_sfr_columns_signs_units_and_stations(tmp_path: Path) -> None:
    spec = SfrObsSpec.from_mapping(_SPEC_PAYLOAD)
    obs_path = tmp_path / "m.sfr.obs.csv"
    _write_csv(obs_path)

    # TDIS in days: rates are m3/day in the CSV and must land in m3/s.
    columns, budgets = build_sfr_columns(
        spec, obs_path, times=[86400.0], seconds_per_time_unit=86400.0
    )
    by_key = _by_key(columns)

    stage = by_key[(sfr_station_id("net0", 0), "stage", 0)]
    assert stage["value"] == pytest.approx(95.25)  # state, never scaled
    assert stage["unit"] == "m"

    dsflow = by_key[(sfr_station_id("net0", 0), "downstream_flow", 0)]
    assert dsflow["value"] == pytest.approx(4320.0 / 86400.0)  # negated outflow
    assert dsflow["unit"] == "m3 s-1"

    # 'sfr' obs positive = stream losing; stored stream-POV = negative.
    exchange = by_key[(sfr_station_id("net0", 0), "gw_exchange", 0)]
    assert exchange["value"] == pytest.approx(-864.0 / 86400.0)

    outflow = by_key[(sfr_station_id("net0", 1), "ext_outflow", 0)]
    assert outflow["value"] == pytest.approx(3456.0 / 86400.0)

    from_mvr = by_key[(sfr_station_id("net0", 1), "from_mvr", 0)]
    assert from_mvr["value"] == pytest.approx(1728.0 / 86400.0)  # incoming, unchanged

    # One budget row per timestep sums the stream-POV exchange over the network.
    assert len(budgets) == 1
    budget = budgets[0]
    assert budget["zone_id"] == "sfr:net0"
    assert budget["component"] == "sfr_gwf"
    total = (-864.0 + 432.0) / 86400.0
    assert budget["flux_out"] == pytest.approx(abs(total))
    assert budget["flux_in"] == pytest.approx(0.0)
    assert budget["unit"] == "m3 s-1"


def test_build_sfr_columns_multi_step_with_calendar(tmp_path: Path) -> None:
    spec = SfrObsSpec.from_mapping(_SPEC_PAYLOAD)
    obs_path = tmp_path / "m.sfr.obs.csv"
    obs_path.write_text(
        "time,R0_STAGE,R0_DOWNSTREAM_FLOW,R0_GW_EXCHANGE,R1_EXT_OUTFLOW,R1_FROM_MVR,"
        "R1_GW_EXCHANGE\n"
        "86400.0,95.25,-4320.0,864.0,-3456.0,1728.0,-432.0\n"
        "172800.0,95.50,-8640.0,1728.0,-6912.0,3456.0,-864.0\n",
        encoding="utf-8",
    )
    calendar = np.array(["2020-01-02T00:00:00", "2020-01-03T00:00:00"], dtype="datetime64[ms]")
    columns, budgets = build_sfr_columns(
        spec,
        obs_path,
        times=[86400.0, 172800.0],
        seconds_per_time_unit=86400.0,
        calendar_times=calendar,
    )
    # 6 entries x 2 steps.
    assert len(columns["value"]) == 12
    by_key = _by_key(columns)
    stage1 = by_key[(sfr_station_id("net0", 0), "stage", 1)]
    assert stage1["value"] == pytest.approx(95.50)
    assert stage1["time"] == calendar[1]
    dsflow1 = by_key[(sfr_station_id("net0", 0), "downstream_flow", 1)]
    assert dsflow1["value"] == pytest.approx(8640.0 / 86400.0)
    assert len(budgets) == 2
    assert budgets[1]["timestep"] == 1
    assert budgets[1]["flux_out"] == pytest.approx((1728.0 - 864.0) / 86400.0)


def test_build_sfr_columns_pads_truncated_final_row(tmp_path: Path) -> None:
    spec = SfrObsSpec.from_mapping(_SPEC_PAYLOAD)
    obs_path = tmp_path / "m.sfr.obs.csv"
    # Second row is truncated after R0_GW_EXCHANGE (killed run).
    obs_path.write_text(
        "time,R0_STAGE,R0_DOWNSTREAM_FLOW,R0_GW_EXCHANGE,R1_EXT_OUTFLOW,R1_FROM_MVR,"
        "R1_GW_EXCHANGE\n"
        "86400.0,95.25,-4320.0,864.0,-3456.0,1728.0,-432.0\n"
        "172800.0,95.50,-8640.0,1728.0\n",
        encoding="utf-8",
    )
    columns, budgets = build_sfr_columns(
        spec, obs_path, times=[86400.0, 172800.0], seconds_per_time_unit=86400.0
    )
    by_key = _by_key(columns)
    assert (sfr_station_id("net0", 0), "stage", 1) in by_key
    assert (sfr_station_id("net0", 1), "ext_outflow", 1) not in by_key
    # t1 network exchange only sees the reach the truncated row still covers.
    assert budgets[1]["flux_out"] == pytest.approx(1728.0 / 86400.0)


def test_build_sfr_columns_rejects_misaligned_times(tmp_path: Path) -> None:
    spec = SfrObsSpec.from_mapping(_SPEC_PAYLOAD)
    obs_path = tmp_path / "m.sfr.obs.csv"
    _write_csv(obs_path)
    with pytest.raises(ValueError, match="misaligned"):
        build_sfr_columns(spec, obs_path, times=[3600.0], seconds_per_time_unit=1.0)


# The routed outflow is one definition: reach ext-outflow plus lake ext-outflow.
#
# A network whose reaches end in a lake has no ext-outflow of its own: the water
# leaves through the lake outlet. A series of zeros must never pass for a flow.

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


def _lake_alone(root: Path, lake_out: list[float]) -> None:
    """Write the sidecars of a lake with an outlet and no network."""
    _write_run(root, reach_out=[0.0, 0.0, 0.0], lake_out=lake_out)
    (root / "m.sfr.meta.json").unlink()
    (root / "m.sfr.obs.csv").unlink()


def test_a_lake_without_a_network_serves_its_outlet(tmp_path: Path) -> None:
    _lake_alone(tmp_path, [0.1, 0.2, 0.3])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    np.testing.assert_allclose(series, [0.1, 0.2, 0.3])


def test_a_lake_whose_outlet_stays_dry_is_a_routed_zero_the_drains_add_to(tmp_path: Path) -> None:
    _lake_alone(tmp_path, [0.0, 0.0, 0.0])
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    np.testing.assert_allclose(series, [0.0, 0.0, 0.0])


def test_a_run_without_network_nor_lake_has_no_routed_series(tmp_path: Path) -> None:
    assert routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0) is None


def test_a_series_of_zeros_is_refused(tmp_path: Path) -> None:
    _write_run(tmp_path, reach_out=[0.0, 0.0, 0.0], lake_out=None)
    with pytest.raises(ObservableNotAvailableError, match="zero"):
        routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
