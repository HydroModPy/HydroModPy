"""The SFR obs-CSV extractor stores each reach quantity with one sign and one unit.

MF6 writes flows in m3 per TDIS unit, negative when they leave the reach. The extractor stores
m3/s. The routed outflow is reach ext-outflow plus lake ext-outflow, and the routed flow of a
reach is read back for the gauge that sits on its cell.
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
    reach_flow_by_cell,
    routed_outflow_series,
    sfr_station_id,
)

SECONDS_PER_DAY = 86400.0
TIMES = [86400.0, 172800.0, 259200.0]


def entry(reach: int, quantity: str) -> dict:
    return {
        "obsname": f"r{reach}_{quantity}",
        "network_id": "net0",
        "reach": reach,
        "quantity": quantity,
    }


SPEC_PAYLOAD = {
    "obs_csv": "m.sfr.obs.csv",
    "network_id": "net0",
    "reach_count": 2,
    "entries": [
        entry(0, "stage"),
        entry(0, "downstream_flow"),
        entry(0, "gw_exchange"),
        entry(1, "ext_outflow"),
        entry(1, "from_mvr"),
        entry(1, "gw_exchange"),
    ],
}

COLUMNS_HEADER = (
    "time,R0_STAGE,R0_DOWNSTREAM_FLOW,R0_GW_EXCHANGE,R1_EXT_OUTFLOW,R1_FROM_MVR,R1_GW_EXCHANGE\n"
)
ROW_DAY_1 = "86400.0,95.25,-4320.0,864.0,-3456.0,1728.0,-432.0\n"
ROW_DAY_2 = "172800.0,95.50,-8640.0,1728.0,-6912.0,3456.0,-864.0\n"


def columns_from(tmp_path: Path, rows: str, **kwargs):
    """Write the obs CSV of the two-reach spec and extract its columns."""
    obs_path = tmp_path / "m.sfr.obs.csv"
    obs_path.write_text(COLUMNS_HEADER + rows, encoding="utf-8")
    return build_sfr_columns(
        SfrObsSpec.from_mapping(SPEC_PAYLOAD), obs_path, seconds_per_time_unit=86400.0, **kwargs
    )


def by_key(columns: dict[str, np.ndarray]) -> dict[tuple[str, str, int], dict]:
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


def write_obs_run(
    root: Path, *, reach_out: list[float], lake_out: list[float] | None, network: bool = True
) -> None:
    """Write the SFR and optional LAK sidecars and obs CSVs of a tiny run."""
    if network:
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


def test_columns_signs_units_and_stations(tmp_path: Path) -> None:
    # TDIS in days, so rates are m3/day in the CSV and land in m3/s.
    columns, budgets = columns_from(tmp_path, ROW_DAY_1, times=[86400.0])
    values = by_key(columns)

    stage = values[(sfr_station_id("net0", 0), "stage", 0)]
    assert stage["value"] == pytest.approx(95.25)  # state, never scaled
    assert stage["unit"] == "m"

    dsflow = values[(sfr_station_id("net0", 0), "downstream_flow", 0)]
    assert dsflow["value"] == pytest.approx(4320.0 / 86400.0)  # negated outflow
    assert dsflow["unit"] == "m3 s-1"

    # The sfr obs is positive when the stream loses water, the stored value is stream point of
    # view and so negative.
    exchange = values[(sfr_station_id("net0", 0), "gw_exchange", 0)]
    assert exchange["value"] == pytest.approx(-864.0 / 86400.0)

    outflow = values[(sfr_station_id("net0", 1), "ext_outflow", 0)]
    assert outflow["value"] == pytest.approx(3456.0 / 86400.0)

    from_mvr = values[(sfr_station_id("net0", 1), "from_mvr", 0)]
    assert from_mvr["value"] == pytest.approx(1728.0 / 86400.0)  # incoming, unchanged

    # One budget row per timestep sums the exchange over the network.
    assert len(budgets) == 1
    budget = budgets[0]
    assert budget["zone_id"] == "sfr:net0"
    assert budget["component"] == "sfr_gwf"
    assert budget["flux_out"] == pytest.approx(abs((-864.0 + 432.0) / 86400.0))
    assert budget["flux_in"] == pytest.approx(0.0)
    assert budget["unit"] == "m3 s-1"


def test_columns_over_two_steps_with_calendar(tmp_path: Path) -> None:
    calendar = np.array(["2020-01-02T00:00:00", "2020-01-03T00:00:00"], dtype="datetime64[ms]")
    columns, budgets = columns_from(
        tmp_path, ROW_DAY_1 + ROW_DAY_2, times=[86400.0, 172800.0], calendar_times=calendar
    )
    assert len(columns["value"]) == 12  # 6 entries x 2 steps
    values = by_key(columns)
    stage1 = values[(sfr_station_id("net0", 0), "stage", 1)]
    assert stage1["value"] == pytest.approx(95.50)
    assert stage1["time"] == calendar[1]
    dsflow1 = values[(sfr_station_id("net0", 0), "downstream_flow", 1)]
    assert dsflow1["value"] == pytest.approx(8640.0 / 86400.0)
    assert len(budgets) == 2
    assert budgets[1]["timestep"] == 1
    assert budgets[1]["flux_out"] == pytest.approx((1728.0 - 864.0) / 86400.0)


def test_truncated_last_row_is_padded(tmp_path: Path) -> None:
    # The second row stops after R0_GW_EXCHANGE, as after a killed run.
    truncated = "172800.0,95.50,-8640.0,1728.0\n"
    columns, budgets = columns_from(tmp_path, ROW_DAY_1 + truncated, times=[86400.0, 172800.0])
    values = by_key(columns)
    assert (sfr_station_id("net0", 0), "stage", 1) in values
    assert (sfr_station_id("net0", 1), "ext_outflow", 1) not in values
    # The network exchange of step 1 only sees the reach the truncated row still covers.
    assert budgets[1]["flux_out"] == pytest.approx(1728.0 / 86400.0)


# The routed outflow is one definition, reach ext-outflow plus lake ext-outflow. A network whose
# reaches end in a lake has no ext-outflow of its own, the water leaves through the lake outlet.
ROUTED_OUTFLOWS = [
    pytest.param(
        [0.0] * 3, [0.042, 0.045, 0.047], True, [0.042, 0.045, 0.047], id="reaches end in a lake"
    ),
    pytest.param([0.5] * 3, [0.1, 0.2, 0.3], True, [0.6, 0.7, 0.8], id="reach and lake add up"),
    pytest.param([0.0] * 3, [0.1, 0.2, 0.3], False, [0.1, 0.2, 0.3], id="lake without network"),
    pytest.param([0.0] * 3, [0.0] * 3, False, [0.0] * 3, id="lake outlet dry"),
]


@pytest.mark.parametrize(("reach_out", "lake_out", "network", "expected"), ROUTED_OUTFLOWS)
def test_routed_outflow(tmp_path: Path, reach_out, lake_out, network, expected) -> None:
    write_obs_run(tmp_path, reach_out=reach_out, lake_out=lake_out, network=network)
    series = routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
    assert series is not None
    np.testing.assert_allclose(series, expected)


def test_no_network_nor_lake_has_no_routed_series(tmp_path: Path) -> None:
    assert routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0) is None


# Under SFR nothing is accumulated, MODFLOW routed the water movers included. The reach under the
# station already carries the flow to compare.

FLOW_PAYLOAD = {
    "obs_csv": "m.sfr.obs.csv",
    "network_id": "net0",
    "reach_count": 3,
    "entries": [
        entry(0, "downstream_flow"),
        entry(1, "downstream_flow"),
        entry(2, "downstream_flow"),
        entry(0, "stage"),
    ],
}
FLOW_CSV = (
    "time,R0_DOWNSTREAM_FLOW,R1_DOWNSTREAM_FLOW,R2_DOWNSTREAM_FLOW,R0_STAGE\n"
    "86400.0,-864.0,-1728.0,-2592.0,95.25\n"
    "172800.0,-1728.0,-3456.0,-5184.0,95.30\n"
)


def sfr_reach(ifno: int, cell2d: int | None) -> dict:
    return {
        "ifno": ifno,
        "downstream": [],
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


def write_flow_run(root: Path, cells: list[int | None], *, meta: bool = True, csv: bool = True):
    if meta:
        payload = FLOW_PAYLOAD | {"reaches": [sfr_reach(i, c) for i, c in enumerate(cells)]}
        (root / "m.sfr.meta.json").write_text(json.dumps(payload), encoding="utf-8")
    if csv:
        (root / "m.sfr.obs.csv").write_text(FLOW_CSV, encoding="utf-8")


def flow_by_cell(root: Path) -> dict[int, np.ndarray] | None:
    return reach_flow_by_cell(
        root, "m", times=[86400.0, 172800.0], seconds_per_time_unit=SECONDS_PER_DAY
    )


# -864 m3/d reported negative by MF6 is +0.01 m3/s leaving the reach. A gauge on a shared cell
# measures what leaves it, which is the flow of the most downstream reach.
FLOWS_BY_CELL = [
    pytest.param(
        [4, 5, 6],
        {4: [0.01, 0.02], 5: [0.02, 0.04], 6: [0.03, 0.06]},
        id="each cell carries its reach",
    ),
    pytest.param([4, 4, 6], {4: [0.02, 0.04], 6: [0.03, 0.06]}, id="downstream reach wins a cell"),
]


@pytest.mark.parametrize(("cells", "expected"), FLOWS_BY_CELL)
def test_flow_by_cell(tmp_path: Path, cells: list[int], expected: dict) -> None:
    write_flow_run(tmp_path, cells)
    by_cell = flow_by_cell(tmp_path)
    assert by_cell is not None
    assert set(by_cell) == set(expected)
    for cell, flow in expected.items():
        assert by_cell[cell] == pytest.approx(flow)


# None tells the caller to route the release itself.
NO_FLOW_BY_CELL = [
    pytest.param([], False, False, id="no sidecar"),
    pytest.param([4], True, False, id="sidecar without obs csv"),
    pytest.param([None], True, True, id="reaches touch no cell"),
]


@pytest.mark.parametrize(("cells", "meta", "csv"), NO_FLOW_BY_CELL)
def test_no_flow_by_cell(tmp_path: Path, cells, meta, csv) -> None:
    write_flow_run(tmp_path, cells, meta=meta, csv=csv)
    assert flow_by_cell(tmp_path) is None


def test_refusals(tmp_path: Path) -> None:
    obs_path = tmp_path / "m.sfr.obs.csv"
    obs_path.write_text(COLUMNS_HEADER + ROW_DAY_1, encoding="utf-8")
    spec = SfrObsSpec.from_mapping(SPEC_PAYLOAD)
    with pytest.raises(ValueError, match="misaligned"):
        build_sfr_columns(spec, obs_path, times=[3600.0], seconds_per_time_unit=1.0)

    write_obs_run(tmp_path, reach_out=[0.0, 0.0, 0.0], lake_out=None)
    with pytest.raises(ObservableNotAvailableError, match="zero"):
        routed_outflow_series(tmp_path, "m", times=TIMES, seconds_per_time_unit=1.0)
