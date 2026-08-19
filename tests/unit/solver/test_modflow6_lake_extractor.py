"""The LAK extractor re-keys the obs CSV by (lake_id, totim) with the right
unit convention.

Per-lake stage / volume / surface-area come from the LAK observation CSV and are
states: stage (m), volume (m3), surface-area (m2) must NOT be divided by
``seconds_per_time_unit``. Every RATE term (spillway, storage, the rest of the
water balance) is divided to reach m3/s. The test guards that the undivided rate
is NOT produced (a per-time-unit value would be 86400x too large under a
DAYS-equivalent clock).

The lake-aquifer exchange is the exception: it comes from the applied flux in the
LAK binary budget, never from the per-connection ``lak`` observations, which MF6
does not keep equal to the applied flux on a connection with no wetted area. The
tests pin that the obs sum is not used, and that a missing budget drops the
exchange series instead of publishing a wrong one.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hydromodpy.solver.modflow6.builders import build_lake_obs_spec
from hydromodpy.solver.modflow6.extractors import lake as lake_extractor
from hydromodpy.solver.modflow6.extractors.lake import (
    AppliedExchange,
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


def _stub_applied_exchange(
    monkeypatch: pytest.MonkeyPatch, exchange: dict[str, AppliedExchange]
) -> None:
    """Serve a known applied flux, standing in for the LAK binary budget."""
    monkeypatch.setattr(
        lake_extractor, "read_applied_exchange", lambda spec, obs_path, *, n_steps: exchange
    )


def test_lake_extractor_states_not_scaled_rates_to_m3_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec, obs_continuous = _single_lake_spec()
    obs_path = tmp_path / spec.obs_csv
    # The applied flux is what gets published. It is deliberately NOT the sum of the
    # lak obs below (-0.0035), so a regression back to summing the obs fails here.
    applied = -0.006
    _stub_applied_exchange(
        monkeypatch, {"lac0": AppliedExchange(total=[applied], under_dam=[applied])}
    )
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

    # Lake-aquifer exchange = the applied flux / seconds. Lake loses water, so the
    # lake-side flux is strictly negative.
    expected_exchange = applied / _SECONDS_PER_STEP
    assert rec[(station, "gwf_exchange")]["value"] == pytest.approx(expected_exchange)
    assert rec[(station, "gwf_exchange")]["value"] < 0.0
    # Neither the obs sum nor the undivided rate may appear.
    obs_sum = -(0.001 + 0.002 + 0.0005) / _SECONDS_PER_STEP
    assert rec[(station, "gwf_exchange")]["value"] != pytest.approx(obs_sum)
    assert rec[(station, "gwf_exchange")]["value"] != pytest.approx(applied)

    # All three connections are VERTICAL, so under-dam leakage == total exchange.
    assert rec[(station, "seepage_under_dam")]["value"] == pytest.approx(expected_exchange)

    # The exchange total also lands in the budget table, keyed by the lake station.
    assert len(budgets) == 1
    budget = budgets[0]
    assert budget["zone_id"] == station
    assert budget["component"] == "lak_gwf"
    assert budget["flux_out"] == pytest.approx(abs(expected_exchange))
    assert budget["flux_in"] == pytest.approx(0.0)


def test_lake_extractor_drops_exchange_when_budget_is_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # No LAK binary budget next to the obs CSV: the exchange cannot be recovered from
    # the obs, so it must be absent and said out loud, never silently substituted.
    spec, obs_continuous = _single_lake_spec()
    assert spec.budget_bin == "m.lak.cbc"
    obs_path = tmp_path / spec.obs_csv
    _write_obs_csv(
        obs_path,
        obs_continuous,
        {"LAC0_STAGE": 90.0, "LAC0_LAK_0": 0.001, "LAC0_LAK_1": 0.002, "LAC0_LAK_2": 0.0005},
    )
    with caplog.at_level(logging.WARNING):
        timeseries, budgets = build_lake_records(
            spec, obs_path, times=[_SECONDS_PER_STEP], seconds_per_time_unit=_SECONDS_PER_STEP
        )
    variables = {r["variable"] for r in timeseries}
    assert "stage" in variables
    assert "gwf_exchange" not in variables
    assert "seepage_under_dam" not in variables
    assert not [b for b in budgets if b["component"] == "lak_gwf"]
    assert "m.lak.cbc" in caplog.text


def test_lake_obs_spec_names_the_binary_budget() -> None:
    # The sidecar must carry the binary budget name: it is the only source of the
    # applied lake-aquifer flux, and an older sidecar without it loses the series.
    _, meta = build_lake_obs_spec(
        stem="run",
        lake_conn_info=[{"lake_index": 0, "lake_id": "lac0", "n_conn": 1, "vertical_iconns": [0]}],
        outlets=[],
    )
    assert meta["budget_bin"] == "run.lak.cbc"
    assert meta["budgetcsv"] == "run.lak.budget.csv"
    assert LakeObsSpec.from_mapping(meta).budget_bin == "run.lak.cbc"
    # An older sidecar simply has no budget name; the spec must not invent one.
    legacy = {k: v for k, v in meta.items() if k != "budget_bin"}
    assert LakeObsSpec.from_mapping(legacy).budget_bin is None


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
