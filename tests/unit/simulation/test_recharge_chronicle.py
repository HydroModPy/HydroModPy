"""Unit tests for recharge chronicle parsing helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.simulation.forcing import build_recharge_chronicle_payload


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
                "values_mm_day": [1.0, 2.0],
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

