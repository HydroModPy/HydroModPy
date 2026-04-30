"""Unit tests for ``hydromodpy.calibration.config`` schemas.

Ports the behavioural intent of the old ``test_schemas.py`` to the new
:class:`CalibrationConfig`/``CalibParameterDecl`` pair. The old schema
validated ``chronicle``/``bounds``/``calibration_method`` sections (all
flattened at the top level); the new schema is a single ``[calibration]``
block with structured parameter declarations. Tests below cover the
equivalent ground:

- a minimal valid payload validates cleanly,
- unknown top-level and per-parameter keys are rejected (``extra="forbid"``),
- ``method``/``save_runs``/``transform``/``prior`` literal constraints,
- invalid ``max_iter`` / ``save_best_n`` values are rejected,
- a small embedded TOML round-trips through ``tomllib.loads`` +
  ``model_validate``.

Case-specific chronicle configs (``brutsaert``/``groundwater_1d``/
``reservoir``) that existed in the old suite have been dropped: the new
architecture does not ship their validators here, so porting those
checks would require inventing API.
"""

from __future__ import annotations

import tomllib

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibParameterDecl,
    CalibrationConfig,
)


def _minimal_payload() -> dict:
    return {
        "method": "grid",
        "max_iter": 20,
        "save_runs": "none",
        "parameters": {
            "K": {"bounds": [1.0e-6, 1.0e-3], "transform": "log"},
            "Sy": {"bounds": [0.02, 0.30]},
        },
    }


# ---------------------------------------------------------------------------
# CalibrationConfig top-level
# ---------------------------------------------------------------------------


class TestCalibrationConfigMinimalPayload:
    def test_empty_dict_yields_sensible_defaults(self):
        """An empty payload uses the declared defaults end-to-end."""
        cfg = CalibrationConfig.model_validate({})
        assert cfg.method == "optuna"
        assert cfg.max_iter == 100
        assert cfg.save_runs == "none"
        assert cfg.save_best_n == 10
        assert cfg.use_cache is True
        assert cfg.objective == "nse"
        assert cfg.variable == "head"
        assert cfg.parameters == {}

    def test_accepts_minimal_valid_payload(self):
        cfg = CalibrationConfig.model_validate(_minimal_payload())
        assert cfg.method == "grid"
        assert cfg.max_iter == 20
        assert set(cfg.parameters) == {"K", "Sy"}
        assert cfg.parameters["K"].transform == "log"
        assert cfg.parameters["Sy"].transform == "identity"  # default

    def test_parameters_typed_as_calib_parameter_decl(self):
        cfg = CalibrationConfig.model_validate(_minimal_payload())
        for decl in cfg.parameters.values():
            assert isinstance(decl, CalibParameterDecl)


class TestCalibrationConfigExtraForbidden:
    def test_unknown_top_level_key_is_rejected(self):
        payload = _minimal_payload()
        payload["legacy_section"] = {"K": 1.0e-4}
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibrationConfig.model_validate(payload)

    def test_unknown_per_parameter_key_is_rejected(self):
        payload = _minimal_payload()
        payload["parameters"]["K"]["legacy_alias"] = True
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibrationConfig.model_validate(payload)


# ---------------------------------------------------------------------------
# Literal field constraints
# ---------------------------------------------------------------------------


class TestCalibrationConfigMethodLiteral:
    @pytest.mark.parametrize(
        "method",
        [
            "optuna",
            "scipy_de",
            "scipy_nelder_mead",
            "grid",
            "random_search",
            "cma_es",
            "gp_mapping",
            "da_mh_gp",
        ],
    )
    def test_accepts_all_supported_methods(self, method: str):
        cfg = CalibrationConfig.model_validate({"method": method})
        assert cfg.method == method

    @pytest.mark.parametrize("method", ["bayesian", "genetic", "", "GRID"])
    def test_rejects_unsupported_method(self, method: str):
        with pytest.raises(ValidationError, match="method"):
            CalibrationConfig.model_validate({"method": method})


class TestCalibrationConfigSaveRunsLiteral:
    @pytest.mark.parametrize("mode", ["none", "best_n", "all"])
    def test_accepts_supported_modes(self, mode: str):
        cfg = CalibrationConfig.model_validate({"save_runs": mode})
        assert cfg.save_runs == mode

    @pytest.mark.parametrize("mode", ["top_n", "best", "", "ALL"])
    def test_rejects_unsupported_mode(self, mode: str):
        with pytest.raises(ValidationError, match="save_runs"):
            CalibrationConfig.model_validate({"save_runs": mode})


class TestCalibrationConfigNumericBounds:
    def test_max_iter_must_be_at_least_one(self):
        with pytest.raises(ValidationError, match="max_iter"):
            CalibrationConfig.model_validate({"max_iter": 0})

    def test_max_iter_rejects_negative(self):
        with pytest.raises(ValidationError, match="max_iter"):
            CalibrationConfig.model_validate({"max_iter": -3})

    def test_save_best_n_cannot_be_negative(self):
        with pytest.raises(ValidationError, match="save_best_n"):
            CalibrationConfig.model_validate({"save_best_n": -1})

    def test_batch_size_must_be_at_least_one(self):
        with pytest.raises(ValidationError, match="batch_size"):
            CalibrationConfig.model_validate({"batch_size": 0})


# ---------------------------------------------------------------------------
# CalibParameterDecl
# ---------------------------------------------------------------------------


class TestCalibParameterDeclTransform:
    @pytest.mark.parametrize("transform", ["identity", "log", "logit"])
    def test_accepts_supported_transform(self, transform: str):
        decl = CalibParameterDecl.model_validate({"transform": transform})
        assert decl.transform == transform

    @pytest.mark.parametrize("transform", ["sqrt", "inverse", "power", ""])
    def test_rejects_unknown_transform(self, transform: str):
        with pytest.raises(ValidationError, match="transform"):
            CalibParameterDecl.model_validate({"transform": transform})


class TestCalibParameterDeclPrior:
    @pytest.mark.parametrize("prior", ["uniform", "log_uniform", "normal"])
    def test_accepts_supported_prior(self, prior: str):
        decl = CalibParameterDecl.model_validate({"prior": prior})
        assert decl.prior == prior

    @pytest.mark.parametrize("prior", ["jeffreys", "beta", ""])
    def test_rejects_unsupported_prior(self, prior: str):
        with pytest.raises(ValidationError, match="prior"):
            CalibParameterDecl.model_validate({"prior": prior})


class TestCalibParameterDeclDefaults:
    def test_empty_declaration_inherits_defaults(self):
        decl = CalibParameterDecl.model_validate({})
        assert decl.bounds is None
        assert decl.transform == "identity"
        assert decl.prior == "uniform"
        assert decl.path is None
        assert decl.units is None

    def test_rejects_unknown_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibParameterDecl.model_validate({"legacy_hint": 1.0})


# ---------------------------------------------------------------------------
# TOML round-trip (the old test exercised load_calibration_toml; the new
# architecture uses plain tomllib + model_validate directly)
# ---------------------------------------------------------------------------


class TestTomlRoundTrip:
    def test_full_section_roundtrip(self):
        toml_src = """
        [calibration]
        method = "grid"
        max_iter = 50
        save_runs = "best_n"
        save_best_n = 5
        seed = 42
        objective = "kge"
        variable = "head"

        [calibration.parameters.K_aquifer]
        bounds = [1e-6, 1e-3]
        transform = "log"
        prior = "log_uniform"
        path = "flow.properties.k_aquifer"

        [calibration.parameters.Sy]
        bounds = [0.02, 0.30]
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "grid"
        assert cfg.max_iter == 50
        assert cfg.save_runs == "best_n"
        assert cfg.save_best_n == 5
        assert cfg.seed == 42
        assert cfg.objective == "kge"
        assert set(cfg.parameters) == {"K_aquifer", "Sy"}
        assert cfg.parameters["K_aquifer"].transform == "log"
        assert cfg.parameters["K_aquifer"].prior == "log_uniform"
        assert cfg.parameters["K_aquifer"].path == "flow.properties.k_aquifer"
        assert cfg.parameters["Sy"].transform == "identity"

    def test_minimal_section_roundtrip(self):
        toml_src = """
        [calibration]
        method = "optuna"
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "optuna"
        assert cfg.parameters == {}

    def test_toml_unknown_section_key_rejected(self):
        toml_src = """
        [calibration]
        method = "grid"
        legacy_toggle = true
        """
        data = tomllib.loads(toml_src)
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibrationConfig.model_validate(data["calibration"])
