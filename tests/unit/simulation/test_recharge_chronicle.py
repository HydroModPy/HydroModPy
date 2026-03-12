"""Unit tests for recharge chronicle parsing helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.simulation.forcing import build_recharge_chronicle_payload
from hydromodpy.simulation.time import ResolvedSimulationTimeWindow


MM_DAY_TO_M_S = 1.0e-3 / 86400.0


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
    assert np.allclose(payload.recharge.values, [1.0 * MM_DAY_TO_M_S, 2.0 * MM_DAY_TO_M_S])
    assert np.allclose(payload.runoff.values, [0.5 * MM_DAY_TO_M_S, 1.0 * MM_DAY_TO_M_S])


def test_recharge_chronicle_payload_builds_one_scalar_steady_series_without_window(
    tmp_path: Path,
) -> None:
    raw_toml = {
        "recharge_chronicle": {
            "mode": "synthetic_generated",
            "synthetic_generated": {
                "values": "3.0 mm/day",
                "units": "mm/day",
                "runoff_ratio": 0.0,
            },
        }
    }

    payload = build_recharge_chronicle_payload(
        raw_toml,
        config_path=tmp_path / "launcher.toml",
        default_observed_path=tmp_path / "default.csv",
        default_sim_state="steady",
    )

    assert payload is not None
    assert payload.mode == "synthetic_generated"
    assert payload.recharge is not None
    assert payload.runoff is not None
    assert len(payload.recharge) == 1
    assert len(payload.runoff) == 1
    assert np.allclose(payload.recharge.values, [3.0 * MM_DAY_TO_M_S])
    assert np.allclose(payload.runoff.values, [0.0])


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
    assert np.allclose(
        payload.recharge.values,
        [1.0 * MM_DAY_TO_M_S, 2.0 * MM_DAY_TO_M_S, 3.0 * MM_DAY_TO_M_S],
    )
    assert np.allclose(
        payload.runoff.values,
        [0.2 * MM_DAY_TO_M_S, 0.4 * MM_DAY_TO_M_S, 0.6 * MM_DAY_TO_M_S],
    )


def test_recharge_chronicle_synthetic_generated_builds_generator_based_series(
    tmp_path: Path,
) -> None:
    raw_toml = {
        "recharge_chronicle": {
            "mode": "synthetic_generated",
            "synthetic_generated": {
                "generator": "seasonal_step",
                "generation_step": "1 day",
                "units": "mm/day",
                "runoff_ratio": 0.1,
                "seasonal_step": {
                    "wet_months": [1, 2],
                    "wet_value": "0.002 m/day",
                    "dry_value": "0.0 m/day",
                },
            },
        }
    }
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01 00:00:00"),
        end=pd.Timestamp("2003-03-31 00:00:00"),
        step_value=30,
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
        pd.Timestamp("2003-01-01 00:00:00"),
        pd.Timestamp("2003-01-31 00:00:00"),
        pd.Timestamp("2003-03-02 00:00:00"),
    ]
    expected_recharge_mm_day = [2.0, (29.0 * 2.0) / 30.0, 0.0]
    assert np.allclose(
        payload.recharge.values,
        np.asarray(expected_recharge_mm_day) * MM_DAY_TO_M_S,
        rtol=1.0e-12,
        atol=1.0e-15,
    )
    assert np.allclose(
        payload.runoff.values,
        np.asarray(expected_recharge_mm_day) * 0.1 * MM_DAY_TO_M_S,
        rtol=1.0e-12,
        atol=1.0e-15,
    )


def test_hydromodpy_config_loads_recharge_chronicle_inline_units(tmp_path: Path) -> None:
    dem_path = tmp_path / "dem.tif"
    dem_path.touch()

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[workspace]",
                'catch_name = "demo"',
                'out_dir_path = "out"',
                'data_path = "data"',
                "",
                "[geographic]",
                'catch_def = "dem"',
                'dem_init_path = "dem.tif"',
                "",
                "[recharge_chronicle]",
                'mode = "synthetic_generated"',
                "",
                "[recharge_chronicle.synthetic_generated]",
                'generator = "seasonal_step"',
                'generation_step = "30 day"',
                'units = "mm/day"',
                "",
                "[recharge_chronicle.synthetic_generated.seasonal_step]",
                "wet_months = [1, 2]",
                'wet_value = "0.005 m/day"',
                'dry_value = "0.0 m/day"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = HydroModPyConfig.from_toml(toml_path)

    assert cfg.recharge_chronicle is not None
    assert cfg.recharge_chronicle.synthetic_generated is not None
    assert cfg.recharge_chronicle.synthetic_generated.units == "mm/day"
    assert cfg.recharge_chronicle.synthetic_generated.seasonal_step is not None
    assert cfg.recharge_chronicle.synthetic_generated.seasonal_step.wet_value == pytest.approx(
        5.0
    )
    assert cfg.recharge_chronicle.synthetic_generated.seasonal_step.dry_value == pytest.approx(
        0.0
    )


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
