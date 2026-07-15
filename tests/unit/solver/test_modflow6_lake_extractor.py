"""The LAK extractor re-keys the obs CSV by (lake_id, totim) with the right
unit convention.

Per-lake stage / volume / surface-area come from the LAK observation CSV and are
states: stage (m), volume (m3), surface-area (m2) must NOT be divided by
``seconds_per_time_unit``. Every RATE term (lake-aquifer exchange, spillway,
storage, the rest of the water balance) is divided to reach m3/s. The
lake-aquifer exchange is the sum of the per-connection ``lak`` observations,
negated to the lake's point of view so a draining lake reads negative; the
under-dam leakage is the VERTICAL-connection subset. The test guards that the
undivided rate is NOT produced (a per-time-unit value would be 86400x too large
under a DAYS-equivalent clock).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.modflow6.builders import build_lake_obs_spec
from hydromodpy.solver.modflow6.extractors.lake import (
    LakeObsSpec,
    build_lake_records,
    lake_station_id,
)

# One time step on a DAYS-equivalent clock: totim is 86400 seconds, so a rate of
# 86400 (length^3 per time unit) must extract to exactly 1.0 m3/s.
_SECONDS_PER_STEP = 86400.0


def _single_lake_spec() -> tuple[LakeObsSpec, dict[str, list]]:
    # lac0: three VERTICAL connections (all under-dam) so the exchange is the
    # negated sum of the three lak obs and the under-dam series equals the total.
    info = [{"lake_index": 0, "lake_id": "lac0", "n_conn": 3, "vertical_iconns": [0, 1, 2]}]
    outlets = [[0, 0, -1, "WEIR", 99.0, 5.0, 0.0, 0.0]]
    obs_continuous, meta = build_lake_obs_spec(stem="m", lake_conn_info=info, outlets=outlets)
    return LakeObsSpec.from_mapping(meta), obs_continuous


def _write_obs_csv(path: Path, obs_continuous: dict, values: dict[str, float]) -> None:
    csv_file = next(iter(obs_continuous))
    header = ["TIME"] + [obs[0].upper() for obs in obs_continuous[csv_file]]
    row = [_SECONDS_PER_STEP] + [values.get(name, 0.0) for name in header[1:]]
    path.write_text(",".join(map(str, header)) + "\n" + ",".join(map(str, row)) + "\n")


def test_lake_extractor_states_not_scaled_rates_to_m3_s(tmp_path: Path) -> None:
    spec, obs_continuous = _single_lake_spec()
    obs_path = tmp_path / spec.obs_csv
    # Lake loses water to the aquifer: every per-connection lak obs is positive
    # (aquifer's point of view), so the lake-side exchange must come out negative.
    _write_obs_csv(
        obs_path,
        obs_continuous,
        {
            "LAC0_STAGE": 90.0,
            "LAC0_VOLUME": 450.0,
            "LAC0_SURFACE_AREA": 90.0,
            # ext-outflow is keyed by the outlet number (here outlet 0). MF6
            # reports outflow negative; the extractor stores it positive.
            "LAC0_EXT_OUTFLOW_0": -_SECONDS_PER_STEP,  # -86400 length^3/unit -> +1.0 m3/s
            "LAC0_LAK_0": 0.001,
            "LAC0_LAK_1": 0.002,
            "LAC0_LAK_2": 0.0005,
        },
    )

    timeseries, budgets = build_lake_records(
        spec,
        obs_path,
        times=[_SECONDS_PER_STEP],
        seconds_per_time_unit=_SECONDS_PER_STEP,
    )

    rec = {(r["station_id"], r["variable"]): r for r in timeseries}
    station = lake_station_id("lac0")

    # States keep their native units (not divided by seconds).
    assert rec[(station, "stage")]["value"] == pytest.approx(90.0)
    assert rec[(station, "stage")]["unit"] == "m"
    assert rec[(station, "volume")]["value"] == pytest.approx(450.0)
    assert rec[(station, "volume")]["unit"] == "m3"
    assert rec[(station, "surface_area")]["value"] == pytest.approx(90.0)
    assert rec[(station, "surface_area")]["unit"] == "m2"

    # The spillway is a RATE: -86400 length^3/unit divides to -1.0 m3/s and is
    # negated to the positive-outflow convention (+1.0). The undivided magnitude
    # (86400) must NOT be produced.
    assert rec[(station, "ext_outflow")]["value"] == pytest.approx(1.0)
    assert abs(rec[(station, "ext_outflow")]["value"]) != pytest.approx(_SECONDS_PER_STEP)
    assert rec[(station, "ext_outflow")]["unit"] == "m3/s"

    # Lake-aquifer exchange = -(sum of per-connection lak) / seconds. Lake loses
    # water, so the lake-side flux is strictly negative.
    expected_exchange = -(0.001 + 0.002 + 0.0005) / _SECONDS_PER_STEP
    assert rec[(station, "gwf_exchange")]["value"] == pytest.approx(expected_exchange)
    assert rec[(station, "gwf_exchange")]["value"] < 0.0
    # Wrong (undivided, wrong sign) value must not appear.
    assert rec[(station, "gwf_exchange")]["value"] != pytest.approx(0.0035)

    # All three connections are VERTICAL, so under-dam leakage == total exchange.
    assert rec[(station, "seepage_under_dam")]["value"] == pytest.approx(expected_exchange)

    # The exchange total also lands in the budget table, keyed by the lake station.
    assert len(budgets) == 1
    budget = budgets[0]
    assert budget["zone_id"] == station
    assert budget["component"] == "lak_gwf"
    assert budget["flux_out"] == pytest.approx(abs(expected_exchange))
    assert budget["flux_in"] == pytest.approx(0.0)


def test_lake_extractor_treats_dnodata_sentinel_as_zero(tmp_path: Path) -> None:
    # MF6 writes 3e30 (no-data) for ext-outflow on an outlet that is a mover or routes
    # to another lake (it has no external outflow). The extractor must read that as 0,
    # not sum the sentinel into a poisoned budget term.
    spec, obs_continuous = _single_lake_spec()
    obs_path = tmp_path / spec.obs_csv
    _write_obs_csv(
        obs_path,
        obs_continuous,
        {
            "LAC0_STAGE": 90.0,
            "LAC0_VOLUME": 450.0,
            "LAC0_SURFACE_AREA": 90.0,
            "LAC0_EXT_OUTFLOW_0": 3.0e30,  # MF6 no-data sentinel
            "LAC0_LAK_0": 0.0,
            "LAC0_LAK_1": 0.0,
            "LAC0_LAK_2": 0.0,
        },
    )
    timeseries, _ = build_lake_records(
        spec, obs_path, times=[_SECONDS_PER_STEP], seconds_per_time_unit=_SECONDS_PER_STEP
    )
    rec = {(r["station_id"], r["variable"]): r for r in timeseries}
    assert rec[(lake_station_id("lac0"), "ext_outflow")]["value"] == pytest.approx(0.0)


def test_lake_extractor_keys_each_lake_and_timestep(tmp_path: Path) -> None:
    # Two lakes, two time steps: every record must carry the right (lake_id,
    # totim) key, and per-lake stage must not bleed across lakes.
    info = [
        {"lake_index": 0, "lake_id": "lacA", "n_conn": 1, "vertical_iconns": [0]},
        {"lake_index": 1, "lake_id": "lacB", "n_conn": 1, "vertical_iconns": [0]},
    ]
    obs_continuous, meta = build_lake_obs_spec(stem="m", lake_conn_info=info, outlets=[])
    spec = LakeObsSpec.from_mapping(meta)
    csv_file = next(iter(obs_continuous))
    header = ["TIME"] + [obs[0].upper() for obs in obs_continuous[csv_file]]

    rows = [
        {"TIME": 86400.0, "LACA_STAGE": 90.0, "LACB_STAGE": 70.0},
        {"TIME": 172800.0, "LACA_STAGE": 88.0, "LACB_STAGE": 69.0},
    ]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(row.get(name, 0.0)) for name in header))
    obs_path = tmp_path / spec.obs_csv
    obs_path.write_text("\n".join(lines) + "\n")

    timeseries, _ = build_lake_records(
        spec,
        obs_path,
        times=[86400.0, 172800.0],
        seconds_per_time_unit=86400.0,
    )

    stage = {
        (r["station_id"], r["timestep"]): r["value"] for r in timeseries if r["variable"] == "stage"
    }
    assert stage[(lake_station_id("lacA"), 0)] == pytest.approx(90.0)
    assert stage[(lake_station_id("lacA"), 1)] == pytest.approx(88.0)
    assert stage[(lake_station_id("lacB"), 0)] == pytest.approx(70.0)
    assert stage[(lake_station_id("lacB"), 1)] == pytest.approx(69.0)
