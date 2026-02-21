"""Unit tests for pydantic schemas used in calibration2 configuration."""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from hydromodpy.calibration2.core.engine_config import validate_calibration_config_data
from hydromodpy.calibration2.cases.recession_brutsaert.case_config import (
    validate_brutsaert_chronicle_config,
)
from hydromodpy.calibration2.cases.reservoir.case_config import (
    validate_reservoir_chronicle_config,
)
from hydromodpy.calibration2.core.methods_config import validate_method_kwargs
from hydromodpy.calibration2.core.engine_config import load_calibration_toml


def _base_config():
    return {
        "chronicle": {"Q0": 0.35, "K": 2.0e-4, "Sy": 0.28},
        "calibration": {"objective_metric": "kge", "global_method": "random_search"},
        "bounds": {"K": [1.0e-5, 1.0e-3], "Sy": [0.2, 0.35]},
        "calibration_method": {"random_search": {"n_samples": 80, "seed": 7}},
    }


def test_validate_calibration_config_data_accepts_valid_payload():
    config = validate_calibration_config_data(_base_config())
    assert set(config) >= {"chronicle", "calibration", "bounds", "calibration_method"}
    assert config["calibration"]["global_method"] == "random_search"


def test_validate_calibration_config_data_rejects_invalid_bounds():
    config = _base_config()
    config["bounds"] = {"K": [1.0e-3, 1.0e-5], "Sy": [0.2, 0.35]}
    with pytest.raises(ValueError, match="Invalid bounds for 'K'"):
        validate_calibration_config_data(config)


def test_validate_calibration_config_data_rejects_invalid_method_kwargs():
    config = _base_config()
    config["calibration_method"] = {"simplex": {"max_iter": 10, "xtol": -1.0e-6}}
    with pytest.raises(ValueError, match="xtol/ftol must be > 0"):
        validate_calibration_config_data(config)


def test_validate_calibration_config_data_rejects_unknown_top_level_section():
    config = _base_config()
    config["legacy_section"] = {"K": 1.0e-4}
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_calibration_config_data(config)


def test_validate_calibration_config_data_rejects_unknown_calibration_key():
    config = _base_config()
    config["calibration"]["legacy_key"] = 1
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_calibration_config_data(config)


def test_validate_method_kwargs_rejects_legacy_alias():
    with pytest.raises(ValueError, match="Unsupported calibration method"):
        validate_method_kwargs(
            "delayed_acceptance_gp_mh",
            {"n_samples": 10, "thin": 1, "sigma_noise": 0.2},
        )


def test_validate_calibration_config_data_rejects_legacy_global_method_alias():
    config = _base_config()
    config["calibration"]["global_method"] = "delayed_acceptance_gp_mh"
    with pytest.raises(ValueError, match="Unsupported global_method"):
        validate_calibration_config_data(config)


def test_validate_reservoir_chronicle_config_rejects_out_of_range_month():
    with pytest.raises(ValueError, match="losses_months values must be between 1 and 12"):
        validate_reservoir_chronicle_config(
            {
                "n_days": 10,
                "target_annual_precip_mm": 100.0,
                "runoff_coeff": 0.2,
                "losses_months": [0, 7],
            }
        )


def test_validate_reservoir_chronicle_config_rejects_unknown_key():
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_reservoir_chronicle_config(
            {
                "n_days": 10,
                "target_annual_precip_mm": 100.0,
                "runoff_coeff": 0.2,
                "losses_months": [4, 7],
                "unknown_key": 1,
            }
        )


def test_validate_brutsaert_chronicle_config_rejects_invalid_ag():
    with pytest.raises(ValueError, match="ag must be in \\[0, 1\\]"):
        validate_brutsaert_chronicle_config(
            {
                "Q0": 0.35,
                "K": 2.0e-4,
                "Sy": 0.28,
                "ag": 1.5,
            }
        )


def test_validate_brutsaert_chronicle_config_rejects_unknown_key():
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_brutsaert_chronicle_config(
            {
                "Q0": 0.35,
                "K": 2.0e-4,
                "Sy": 0.28,
                "unknown_key": 1,
            }
        )


def test_load_calibration_toml_applies_schema_validation(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        textwrap.dedent(
            """
            [chronicle]
            Q0 = 0.35
            K = 2.0e-4
            Sy = 0.28

            [calibration]
            objective_metric = "kge"
            global_method = "simplex"

            [bounds]
            K = [1.0e-5, 1.0e-3]
            Sy = [0.2, 0.35]

            [calibration_method.simplex]
            max_iter = 20
            xtol = -1.0e-6
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid calibration configuration"):
        load_calibration_toml(config_path)
