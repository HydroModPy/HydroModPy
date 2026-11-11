"""The SFR extractor stores each reach quantity with one sign and one unit.

MODFLOW 6 reports the flow that leaves a reach negative and the exchange positive when the stream
loses water to the aquifer. The extractor stores a positive stream flow, and a ``gw_exchange`` that
is positive when the reach gains baseflow. A rate is divided by the seconds in one TDIS unit to reach
m3/s and a state (stage, depth) is kept in meters. The convention of ``core/budget/flux.py`` is read
from the aquifer: a flux is positive when it enters, so a gaining reach is an outflow of the aquifer.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors.sfr import (
    SfrObsSpec,
    build_sfr_columns,
    reach_flow_by_cell,
)

_SPT = 86400.0
_STAMP = 86400.0


def _spec(quantity: str) -> SfrObsSpec:
    return SfrObsSpec.from_mapping(
        {
            "obs_csv": "m.sfr.obs.csv",
            "network_id": "net0",
            "reach_count": 1,
            "entries": [
                {
                    "obsname": f"r0_{quantity}",
                    "network_id": "net0",
                    "reach": 0,
                    "quantity": quantity,
                }
            ],
        }
    )


def _extract(tmp_path: Path, quantity: str, value: float):
    obs = tmp_path / "m.sfr.obs.csv"
    obs.write_text(f"time,R0_{quantity.upper()}\n{_STAMP},{value}\n", encoding="utf-8")
    return build_sfr_columns(_spec(quantity), obs, times=[_STAMP], seconds_per_time_unit=_SPT)


# One row per quantity: the value MODFLOW 6 writes for a period of one day, the value stored and
# its unit. A rate of 864 m3/day is 0.01 m3/s.
_QUANTITIES = [
    pytest.param("downstream_flow", -864.0, 0.01, "m3 s-1", id="downstream_flow_negated"),
    pytest.param("ext_outflow", -864.0, 0.01, "m3 s-1", id="ext_outflow_negated"),
    pytest.param("to_mvr", -864.0, 0.01, "m3 s-1", id="to_mvr_negated"),
    pytest.param("gw_exchange", 864.0, -0.01, "m3 s-1", id="a_losing_reach_is_negative"),
    pytest.param("gw_exchange", -864.0, 0.01, "m3 s-1", id="a_gaining_reach_is_positive"),
    pytest.param("ext_inflow", 864.0, 0.01, "m3 s-1", id="ext_inflow_kept"),
    pytest.param("from_mvr", 864.0, 0.01, "m3 s-1", id="from_mvr_kept"),
    pytest.param("runoff", 864.0, 0.01, "m3 s-1", id="runoff_kept"),
    pytest.param("stage", 95.25, 95.25, "m", id="stage_is_a_state_in_meters"),
    pytest.param("depth", 0.4, 0.4, "m", id="depth_is_a_state_in_meters"),
    pytest.param("downstream_flow", 0.0, 0.0, "m3 s-1", id="zero_stays_zero"),
]


@pytest.mark.parametrize(("quantity", "written", "stored", "unit"), _QUANTITIES)
def test_a_reach_quantity_is_stored_with_its_sign_and_unit(
    tmp_path, quantity, written, stored, unit
) -> None:
    columns, _ = _extract(tmp_path, quantity, written)

    assert columns["variable"].tolist() == [quantity]
    assert columns["value"].tolist() == pytest.approx([stored], abs=1e-15)
    assert columns["unit"].tolist() == [unit]
    assert columns["station_id"].tolist() == ["net0:1"]


# One row per reach-aquifer exchange written by MODFLOW 6 (positive when the stream loses water):
# the stream-side budget row, with inflow when the reach gains and outflow when it loses. The aquifer
# sees the opposite, and the aquifer outflow of a signed flux s is max(-s, 0), the inflow of the reach.
_EXCHANGE_BUDGET = [
    pytest.param(-864.0, 0.01, 0.0, id="a_gaining_reach_brings_water_in"),
    pytest.param(864.0, 0.0, 0.01, id="a_losing_reach_sends_water_out"),
    pytest.param(0.0, 0.0, 0.0, id="no_exchange"),
    pytest.param(-0.0, 0.0, 0.0, id="negative_zero_is_no_exchange"),
]


@pytest.mark.parametrize(("written", "flux_in", "flux_out"), _EXCHANGE_BUDGET)
def test_the_exchange_budget_row_splits_into_in_and_out(tmp_path, written, flux_in, flux_out):
    _, budgets = _extract(tmp_path, "gw_exchange", written)

    assert len(budgets) == 1
    row = budgets[0]
    assert row["component"] == "sfr_gwf"
    assert row["zone_id"] == "sfr:net0"
    assert row["flux_in"] == pytest.approx(flux_in, abs=1e-15)
    assert row["flux_out"] == pytest.approx(flux_out, abs=1e-15)
    assert row["flux_in"] >= 0.0 and row["flux_out"] >= 0.0


def _write_run(tmp_path: Path, csv: str, cells: dict[int, int | None]) -> Path:
    reaches = [
        {
            "ifno": ifno,
            "downstream": [],
            "layer": 0,
            "cell2d": cell,
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
        for ifno, cell in cells.items()
    ]
    entries = [
        {
            "obsname": f"r{ifno}_downstream_flow",
            "network_id": "net0",
            "reach": ifno,
            "quantity": "downstream_flow",
        }
        for ifno in cells
    ]
    payload = {
        "obs_csv": "m.sfr.obs.csv",
        "network_id": "net0",
        "reach_count": len(cells),
        "entries": entries,
        "reaches": reaches,
    }
    (tmp_path / "m.sfr.meta.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "m.sfr.obs.csv").write_text(csv, encoding="utf-8")
    return tmp_path


# One row per run: the cells of the reaches, the downstream flows written (negative, m3/day) and the
# flow kept per cell in m3/s (positive). When reaches share a cell, the largest flow wins.
_CELLS = [
    pytest.param({0: 5}, [-864.0], {5: 0.01}, id="one_reach"),
    pytest.param({0: 5, 1: 6}, [-864.0, -1728.0], {5: 0.01, 6: 0.02}, id="two_cells"),
    pytest.param({0: 5, 1: 5}, [-864.0, -1728.0], {5: 0.02}, id="the_largest_flow_of_a_cell_wins"),
    pytest.param(
        {0: 5, 1: None}, [-864.0, -1728.0], {5: 0.01}, id="a_reach_with_no_cell_is_skipped"
    ),
]


@pytest.mark.parametrize(("cells", "written", "expected"), _CELLS)
def test_the_flow_by_cell_is_the_positive_downstream_flow(tmp_path, cells, written, expected):
    header = ",".join(f"R{ifno}_DOWNSTREAM_FLOW" for ifno in cells)
    csv = f"time,{header}\n{_STAMP},{','.join(str(v) for v in written)}\n"
    _write_run(tmp_path, csv, cells)

    by_cell = reach_flow_by_cell(tmp_path, "m", times=[_STAMP], seconds_per_time_unit=_SPT)

    assert by_cell is not None
    assert set(by_cell) == set(expected)
    for cell, flow in expected.items():
        assert by_cell[cell].tolist() == pytest.approx([flow])
        assert (np.asarray(by_cell[cell]) >= 0.0).all()
