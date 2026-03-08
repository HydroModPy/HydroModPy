"""Unit tests for recharge chronicle parsing helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.simulation.forcing import build_recharge_chronicle_payload
from hydromodpy.simulation.time import ResolvedSimulationTimeWindow


def test_recharge_chronicle_payload_none_when_section_missing(tmp_path: Path) -> None:
    payload = build_recharge_chronicle_payload(
        {},
        config_path=tmp_path / "launcher.toml",
        default_observed_path=tmp_path / "default.csv",
        default_sim_state="transient",
    )

    assert payload is None


def test_recharge_chronicle_payload_builds_synthetic_generated_series(tmp_path: Path) -> None:
    raw_toml = {
        "recharge_chronicle": {
            "mode": "synthetic_generated",
            "synthetic_generated": {
                "start_date": "2003-01-01",
                "freq": "D",
                "periods": 2,
                "values": [1.0, 2.0],
                "units": "mm/day",
                "runoff_ratio": 0.5,
            },
        }
    }

    payload = build_recharge_chronicle_payload(
        raw_toml,
        config_path=tmp_path / "launcher.toml",
        default_observed_path=tmp_path / "default.csv",
        default_sim_state="transient",
    )

    assert payload is not None
    assert payload.mode == "synthetic_generated"
    assert payload.recharge is not None
    assert payload.runoff is not None
    assert np.allclose(payload.recharge.values, [0.001, 0.002])
    assert np.allclose(payload.runoff.values, [0.0005, 0.0010])


def test_recharge_chronicle_payload_rejects_legacy_values_mm_day_key(tmp_path: Path) -> None:
    raw_toml = {
        "recharge_chronicle": {
            "mode": "synthetic_generated",
            "synthetic_generated": {
                "start_date": "2003-01-01",
                "freq": "D",
                "periods": 2,
                "values_mm_day": [1.0, 2.0],
                "units": "mm/day",
            },
        }
    }

    with pytest.raises(
        ValueError,
        match="recharge_chronicle.synthetic_generated.values must be",
    ):
        build_recharge_chronicle_payload(
            raw_toml,
            config_path=tmp_path / "launcher.toml",
            default_observed_path=tmp_path / "default.csv",
            default_sim_state="transient",
        )


def test_recharge_chronicle_payload_builds_observed_request(tmp_path: Path) -> None:
    raw_toml = {
        "recharge_chronicle": {
            "mode": "observed_csv",
            "observed_csv": {
                "path_file": "inputs/reanalysis.csv",
                "clim_mod": "REA",
                "clim_sce": "historic",
                "first_year": 2001,
                "last_year": 2002,
                "time_step": "ME",
            },
        }
    }

    payload = build_recharge_chronicle_payload(
        raw_toml,
        config_path=tmp_path / "launcher.toml",
        default_observed_path=tmp_path / "default.csv",
        default_sim_state="transient",
    )

    assert payload is not None
    assert payload.mode == "observed_csv"
    assert payload.observed is not None
    assert payload.observed.path_file == (tmp_path / "inputs" / "reanalysis.csv").resolve()
    assert payload.observed.first_year == 2001
    assert payload.observed.last_year == 2002
    assert payload.observed.sim_state == "transient"


def test_recharge_chronicle_payload_rejects_invalid_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="recharge_chronicle.mode must be one of"):
        build_recharge_chronicle_payload(
            {"recharge_chronicle": {"mode": "unknown_mode"}},
            config_path=tmp_path / "launcher.toml",
            default_observed_path=tmp_path / "default.csv",
            default_sim_state="transient",
        )


def test_recharge_chronicle_synthetic_generated_aligns_with_simulation_window(
    tmp_path: Path,
) -> None:
    raw_toml = {
        "recharge_chronicle": {
            "mode": "synthetic_generated",
            "synthetic_generated": {
                "start_date": "2000-01-01",
                "freq": "ME",
                "periods": 99,
                "values": [1.0, 2.0, 3.0],
                "units": "mm/day",
                "runoff_ratio": 0.2,
            },
        }
    }
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2020-01-01 00:00:00"),
        end=pd.Timestamp("2020-01-30 00:00:00"),
        step_value=10,
        step_unit="day",
        coverage_policy="error",
    )

    payload = build_recharge_chronicle_payload(
        raw_toml,
        config_path=tmp_path / "launcher.toml",
        default_observed_path=tmp_path / "default.csv",
        default_sim_state="transient",
        simulation_window=window,
    )

    assert payload is not None
    assert payload.recharge is not None
    assert payload.runoff is not None
    assert payload.recharge.index.tolist() == [
        pd.Timestamp("2020-01-01 00:00:00"),
        pd.Timestamp("2020-01-11 00:00:00"),
        pd.Timestamp("2020-01-21 00:00:00"),
    ]
    assert np.allclose(payload.recharge.values, [0.001, 0.002, 0.003])
    assert np.allclose(payload.runoff.values, [0.0002, 0.0004, 0.0006])


def test_recharge_chronicle_observed_request_uses_simulation_window_time_grid(
    tmp_path: Path,
) -> None:
    raw_toml = {
        "recharge_chronicle": {
            "mode": "observed_csv",
            "observed_csv": {
                "path_file": "inputs/reanalysis.csv",
                "first_year": 1980,
                "last_year": 1985,
                "time_step": "ME",
            },
        }
    }
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2020-01-01 00:00:00"),
        end=pd.Timestamp("2020-01-30 00:00:00"),
        step_value=10,
        step_unit="day",
        coverage_policy="error",
    )

    payload = build_recharge_chronicle_payload(
        raw_toml,
        config_path=tmp_path / "launcher.toml",
        default_observed_path=tmp_path / "default.csv",
        default_sim_state="transient",
        simulation_window=window,
    )

    assert payload is not None
    assert payload.observed is not None
    assert payload.observed.first_year == 2020
    assert payload.observed.last_year == 2020
    assert payload.observed.time_step == "10D"
