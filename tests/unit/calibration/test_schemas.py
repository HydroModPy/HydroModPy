"""Unit tests for ``hydromodpy.calibration.config`` schemas.

Ports the behavioural intent of the old ``test_schemas.py`` to the new
:class:`CalibrationConfig`/``CalibParameterDecl`` pair. The old schema
validated ``chronicle``/``bounds``/``calibration_method`` sections (all
flattened at the top level); the new schema is a single ``[calibration]``
block with structured parameter declarations. Tests below cover the
equivalent ground:

- a minimal valid payload validates cleanly,
- unknown top-level and per-parameter keys are rejected (``extra="forbid"``),
- ``method``/``save_runs``/``search_space``/``sampling`` literal constraints,
- invalid ``max_trials`` / ``save_best_n`` values are rejected,
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
    validate_calib_output,
)


def _minimal_payload() -> dict:
    return {
        "method": "grid",
        "max_trials": 20,
        "save_runs": "none",
        "parameters": {
            "K": {"bounds": [1.0e-6, 1.0e-3], "search_space": "log"},
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
        # Unwritten, the method follows from the criteria when the run starts.
        assert cfg.method is None
        assert cfg.max_trials == "auto"
        assert cfg.save_runs == "best_n"
        assert cfg.save_best_n == 1
        assert cfg.use_cache is True
        assert cfg.objective == "nse"
        assert cfg.variable == "head"
        assert cfg.parameters == {}

    def test_accepts_minimal_valid_payload(self):
        cfg = CalibrationConfig.model_validate(_minimal_payload())
        assert cfg.method == "grid"
        assert cfg.max_trials == 20
        assert set(cfg.parameters) == {"K", "Sy"}
        assert cfg.parameters["K"].search_space == "log"
        assert cfg.parameters["Sy"].search_space == "identity"  # default

    def test_parameters_typed_as_calib_parameter_decl(self):
        cfg = CalibrationConfig.model_validate(_minimal_payload())
        for decl in cfg.parameters.values():
            assert isinstance(decl, CalibParameterDecl)


class TestCalibrationConfigExtraForbidden:
    def test_unknown_top_level_key_is_rejected(self):
        payload = _minimal_payload()
        payload["legacy_section"] = {"K": 1.0e-4}
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibrationConfig.model_validate(payload)

    def test_unknown_per_parameter_key_is_rejected(self):
        payload = _minimal_payload()
        payload["parameters"]["K"]["legacy_alias"] = True
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibrationConfig.model_validate(payload)


# ---------------------------------------------------------------------------
# Literal field constraints
# ---------------------------------------------------------------------------


class TestCalibrationConfigMethodLiteral:
    @pytest.mark.parametrize("method", ["grid", "random_search", "optuna"])
    def test_accepts_all_supported_methods(self, method: str):
        cfg = CalibrationConfig.model_validate({"method": method})
        assert cfg.method == method

    @pytest.mark.parametrize("method", ["bayesian", "genetic", "", "GRID"])
    def test_rejects_unsupported_method(self, method: str):
        if method == "":
            with pytest.raises(ValidationError, match="method"):
                CalibrationConfig.model_validate({"method": method})
            return
        cfg = CalibrationConfig.model_validate({"method": method})
        with pytest.raises(ValueError, match="Unknown calibration method"):
            cfg.validate_registry()


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
    def test_max_trials_must_be_at_least_one(self):
        with pytest.raises(ValidationError, match="max_trials"):
            CalibrationConfig.model_validate({"max_trials": 0})

    def test_max_trials_rejects_negative(self):
        with pytest.raises(ValidationError, match="max_trials"):
            CalibrationConfig.model_validate({"max_trials": -3})

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
    @pytest.mark.parametrize("search_space", ["identity", "log", "logit"])
    def test_accepts_supported_search_space(self, search_space: str):
        decl = CalibParameterDecl.model_validate({"search_space": search_space})
        assert decl.search_space == search_space

    @pytest.mark.parametrize("search_space", ["sqrt", "inverse", "power", ""])
    def test_rejects_unknown_search_space(self, search_space: str):
        with pytest.raises(ValidationError, match="search_space"):
            CalibParameterDecl.model_validate({"search_space": search_space})


class TestCalibParameterDeclPrior:
    @pytest.mark.parametrize("sampling", ["uniform", "log_uniform", "normal"])
    def test_accepts_supported_sampling(self, sampling: str):
        decl = CalibParameterDecl.model_validate({"sampling": sampling})
        assert decl.sampling == sampling

    @pytest.mark.parametrize("sampling", ["jeffreys", "beta", ""])
    def test_rejects_unsupported_sampling(self, sampling: str):
        with pytest.raises(ValidationError, match="sampling"):
            CalibParameterDecl.model_validate({"sampling": sampling})


class TestCalibParameterDeclDefaults:
    def test_empty_declaration_inherits_defaults(self):
        decl = CalibParameterDecl.model_validate({})
        assert decl.bounds is None
        assert decl.search_space == "identity"
        assert decl.sampling == "uniform"
        assert decl.path is None
        assert decl.units is None

    def test_rejects_unknown_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibParameterDecl.model_validate({"legacy_hint": 1.0})


class TestCalibOutputDeclSelectors:
    def test_output_support_tag_is_required(self):
        with pytest.raises(ValidationError, match="support"):
            validate_calib_output({"variable": "head", "x": 10.0, "y": 20.0})

    def test_point_accepts_geojson_geometry(self):
        decl = validate_calib_output(
            {
                "variable": "head",
                "support": "point",
                "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
            }
        )
        assert decl.geometry["type"] == "Point"

    def test_cell_requires_structural_selector(self):
        with pytest.raises(ValidationError, match="row"):
            validate_calib_output({"variable": "head", "support": "cell"})

    def test_cell_accepts_row_col(self):
        decl = validate_calib_output({"variable": "head", "support": "cell", "row": 2, "col": 3})
        assert decl.row == 2
        assert decl.col == 3

    def test_cell_refuses_cell_id(self):
        with pytest.raises(ValidationError, match="'cell_id' is not accepted any more"):
            validate_calib_output({"variable": "head", "support": "cell", "cell_id": 42})


# ---------------------------------------------------------------------------
# TOML round-trip (the old test exercised load_calibration_toml; the new
# architecture uses plain tomllib + model_validate directly)
# ---------------------------------------------------------------------------


class TestTomlRoundTrip:
    def test_full_section_roundtrip(self):
        toml_src = """
        [calibration]
        method = "grid"
        max_trials = 50
        save_runs = "best_n"
        save_best_n = 5
        seed = 42
        objective = "kge"
        variable = "head"

        [calibration.parameters.K_aquifer]
        bounds = [1e-6, 1e-3]
        search_space = "log"
        sampling = "log_uniform"
        path = "flow.properties.k_aquifer"

        [calibration.parameters.Sy]
        bounds = [0.02, 0.30]
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "grid"
        assert cfg.max_trials == 50
        assert cfg.save_runs == "best_n"
        assert cfg.save_best_n == 5
        assert cfg.seed == 42
        assert cfg.objective == "kge"
        assert set(cfg.parameters) == {"K_aquifer", "Sy"}
        assert cfg.parameters["K_aquifer"].search_space == "log"
        assert cfg.parameters["K_aquifer"].sampling == "log_uniform"
        assert cfg.parameters["K_aquifer"].path == "flow.properties.k_aquifer"
        assert cfg.parameters["Sy"].search_space == "identity"

    def test_minimal_section_roundtrip(self):
        toml_src = """
        [calibration]
        method = "grid"
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "grid"
        assert cfg.parameters == {}

    def test_toml_unknown_section_key_rejected(self):
        toml_src = """
        [calibration]
        method = "grid"
        legacy_toggle = true
        """
        data = tomllib.loads(toml_src)
        with pytest.raises(ValidationError, match="Extra inputs"):
            CalibrationConfig.model_validate(data["calibration"])
