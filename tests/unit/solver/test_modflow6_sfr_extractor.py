"""Unit tests for the SFR obs-CSV extractor (signs, units, re-keying)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.solver.modflow6.extractors.sfr import (
    SfrObsSpec,
    build_sfr_records,
    read_sfr_meta,
    sfr_station_id,
)

_SPEC_PAYLOAD = {
    "obs_csv": "m.sfr.obs.csv",
    "budgetcsv": "m.sfr.budget.csv",
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


def test_build_sfr_records_signs_units_and_stations(tmp_path: Path) -> None:
    spec = SfrObsSpec.from_mapping(_SPEC_PAYLOAD)
    obs_path = tmp_path / "m.sfr.obs.csv"
    _write_csv(obs_path)

    # TDIS in days: rates are m3/day in the CSV and must land in m3/s.
    timeseries, budgets = build_sfr_records(
        spec, obs_path, times=[86400.0], seconds_per_time_unit=86400.0
    )
    by_key = {(rec["station_id"], rec["variable"]): rec for rec in timeseries}

    stage = by_key[(sfr_station_id("net0", 0), "stage")]
    assert stage["value"] == pytest.approx(95.25)  # state, never scaled
    assert stage["unit"] == "m"

    dsflow = by_key[(sfr_station_id("net0", 0), "downstream_flow")]
    assert dsflow["value"] == pytest.approx(4320.0 / 86400.0)  # negated outflow
    assert dsflow["unit"] == "m3/s"

    # 'sfr' obs positive = stream losing; stored stream-POV = negative.
    exchange = by_key[(sfr_station_id("net0", 0), "gw_exchange")]
    assert exchange["value"] == pytest.approx(-864.0 / 86400.0)

    outflow = by_key[(sfr_station_id("net0", 1), "ext_outflow")]
    assert outflow["value"] == pytest.approx(3456.0 / 86400.0)

    from_mvr = by_key[(sfr_station_id("net0", 1), "from_mvr")]
    assert from_mvr["value"] == pytest.approx(1728.0 / 86400.0)  # incoming, unchanged

    # One budget row per timestep sums the stream-POV exchange over the network.
    assert len(budgets) == 1
    budget = budgets[0]
    assert budget["zone_id"] == "sfr:net0"
    assert budget["component"] == "sfr_gwf"
    total = (-864.0 + 432.0) / 86400.0
    assert budget["flux_out"] == pytest.approx(abs(total))
    assert budget["flux_in"] == pytest.approx(0.0)
    assert budget["unit"] == "m3/s"


def test_build_sfr_records_rejects_misaligned_times(tmp_path: Path) -> None:
    spec = SfrObsSpec.from_mapping(_SPEC_PAYLOAD)
    obs_path = tmp_path / "m.sfr.obs.csv"
    _write_csv(obs_path)
    with pytest.raises(ValueError, match="misaligned"):
        build_sfr_records(spec, obs_path, times=[3600.0], seconds_per_time_unit=1.0)


def test_read_sfr_meta_roundtrip(tmp_path: Path) -> None:
    meta_path = tmp_path / "m.sfr.meta.json"
    meta_path.write_text(json.dumps(_SPEC_PAYLOAD), encoding="utf-8")
    spec = read_sfr_meta(meta_path)
    assert spec is not None
    assert spec.network_id == "net0"
    assert spec.reach_count == 2
    assert len(spec.entries) == 6
    assert read_sfr_meta(tmp_path / "missing.json") is None
