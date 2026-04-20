"""Unit tests for pydantic schemas used in calibration2 configuration."""

from __future__ import annotations

import pytest

pytest.skip(
    "legacy analysis/calibration superseded by P09 hydromodpy/calibration",
    allow_module_level=True,
)


from pathlib import Path
import textwrap

import pytest

from hydromodpy.analysis.calibration.core.engine_config import validate_calibration_config_data
from hydromodpy.analysis.calibration.cases.recession_brutsaert.case_config import (
    validate_brutsaert_chronicle_config,
)
from hydromodpy.analysis.calibration.cases.groundwater_1d.case_config import (
    validate_groundwater_1d_chronicle_config,
)
from hydromodpy.analysis.calibration.cases.reservoir.case_config import (
    validate_reservoir_chronicle_config,
)
from hydromodpy.analysis.calibration.core.methods_config import validate_method_kwargs
from hydromodpy.analysis.calibration.core.engine_config import load_calibration_toml


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


def test_validate_calibration_config_data_rejects_unknown_output_key():
    config = _base_config()
    config["output"] = {"show_plot": True, "legacy_output_key": 1}
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_calibration_config_data(config)


def test_validate_calibration_config_data_accepts_objective_transform_section():
    config = _base_config()
    config["objective"] = {
        "transform": "log",
        "transform_params": {"epsilon": 1.0e-8},
    }
    validated = validate_calibration_config_data(config)
    assert validated["objective"]["transform"] == "log"
    assert validated["objective"]["transform_params"]["epsilon"] == pytest.approx(1.0e-8)


def test_validate_calibration_config_data_rejects_unknown_objective_key():
    config = _base_config()
    config["objective"] = {
        "transform": "log",
        "legacy_objective_key": True,
    }
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_calibration_config_data(config)


def test_validate_calibration_config_data_rejects_invalid_objective_transform():
    config = _base_config()
    config["objective"] = {"transform": "legacy_log"}
    with pytest.raises(ValueError, match="Unsupported objective transform"):
        validate_calibration_config_data(config)


def test_validate_calibration_config_data_rejects_invalid_transform_params_for_transform():
    config = _base_config()
    config["objective"] = {
        "transform": "sqrt",
        "transform_params": {"epsilon": 1.0e-6},
    }
    with pytest.raises(ValueError, match="Unsupported transform_params"):
        validate_calibration_config_data(config)


def test_validate_calibration_config_data_rejects_non_positive_log_epsilon():
    config = _base_config()
    config["objective"] = {
        "transform": "log",
        "transform_params": {"epsilon": 0.0},
    }
    with pytest.raises(ValueError, match="transform_params.epsilon must be > 0"):
        validate_calibration_config_data(config)


def test_output_objective_surface_auto_disabled_for_3plus_parameters():
    config = _base_config()
    config["bounds"] = {
        "K": [1.0e-5, 1.0e-3],
        "Sy": [0.2, 0.35],
        "a": [0.1, 0.9],
    }
    config["output"] = {
        "show_plot": False,
        "show_objective_surface": True,
        "objective_surface_n_evaluations": 200,
    }
    with pytest.warns(
        UserWarning,
        match="objective surface plotting is supported only for 1D/2D",
    ):
        validated = validate_calibration_config_data(config)
    assert validated["output"]["show_objective_surface"] is False


def test_output_objective_surface_n_evaluations_must_be_positive():
    config = _base_config()
    config["output"] = {
        "show_objective_surface": True,
        "objective_surface_n_evaluations": 0,
    }
    with pytest.raises(ValueError, match="objective_surface_n_evaluations must be > 0"):
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


def test_validate_groundwater_chronicle_config_rejects_invalid_interface():
    with pytest.raises(ValueError, match="xi_true_m must satisfy 0 < xi_true_m < L_m"):
        validate_groundwater_1d_chronicle_config(
            {
                "n_days": 10,
                "dt_days": 1.0,
                "L_m": 100.0,
                "xi_true_m": 100.0,
                "nx": 21,
                "formulation_true": "boussinesq",
                "H_linearized_m": 10.0,
                "Kam_true_m_per_day": 2.0,
                "Kav_true_m_per_day": 1.0,
                "Syam_true": 0.2,
                "Syav_true": 0.1,
            }
        )


def test_validate_groundwater_chronicle_config_rejects_unknown_key():
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validate_groundwater_1d_chronicle_config(
            {
                "n_days": 10,
                "dt_days": 1.0,
                "L_m": 100.0,
                "xi_true_m": 40.0,
                "nx": 21,
                "formulation_true": "linearized",
                "H_linearized_m": 10.0,
                "Kam_true_m_per_day": 2.0,
                "Kav_true_m_per_day": 1.0,
                "Syam_true": 0.2,
                "Syav_true": 0.1,
                "legacy_key": 1,
            }
        )


def test_validate_groundwater_chronicle_config_rejects_invalid_recharge_mode():
    with pytest.raises(ValueError, match="recharge_mode must be one of"):
        validate_groundwater_1d_chronicle_config(
            {
                "n_days": 10,
                "dt_days": 1.0,
                "L_m": 100.0,
                "xi_true_m": 40.0,
                "nx": 21,
                "formulation_true": "linearized",
                "H_linearized_m": 10.0,
                "Kam_true_m_per_day": 2.0,
                "Kav_true_m_per_day": 1.0,
                "Syam_true": 0.2,
                "Syav_true": 0.1,
                "recharge_mode": "sinusoidal",
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

