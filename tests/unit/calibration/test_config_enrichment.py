"""Tests for the enriched [calibration] TOML schema.

Covers the Phase 1 additions to :mod:`hydromodpy.calibration.config`:

- CalibParameterDecl gains target / mode.
- CalibOutputDecl and CalibObjectiveBlockDecl are new Pydantic models.
- CalibrationConfig grows outputs, objective_blocks, persist_* and
  materialize_* fields.
- An implicit objective block is synthesised when none is declared.
"""

from __future__ import annotations

import tomllib

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibOutputDecl,
    CalibParameterDecl,
    CalibrationConfig,
)

# ---------------------------------------------------------------------------
# CalibParameterDecl extended
# ---------------------------------------------------------------------------


class TestCalibParameterDeclExtensions:
    def test_target_is_optional_and_defaults_to_none(self):
        decl = CalibParameterDecl.model_validate({})
        assert decl.target is None
        assert decl.mode == "replace"

    def test_target_alias_wins_over_path(self):
        decl = CalibParameterDecl.model_validate(
            {
                "path": "flow.properties.k_aquifer",
                "target": "flow.param.K.field_homogeneous.value",
            }
        )
        assert decl.resolve_target() == "flow.param.K.field_homogeneous.value"

    def test_path_used_when_target_absent(self):
        decl = CalibParameterDecl.model_validate({"path": "flow.properties.k_aquifer"})
        assert decl.resolve_target() == "flow.properties.k_aquifer"

    @pytest.mark.parametrize("mode", ["replace", "scale"])
    def test_accepts_supported_modes(self, mode: str):
        decl = CalibParameterDecl.model_validate({"mode": mode})
        assert decl.mode == mode

    @pytest.mark.parametrize("mode", ["override", "multiply", "", "REPLACE"])
    def test_rejects_unsupported_modes(self, mode: str):
        with pytest.raises(ValidationError, match="mode"):
            CalibParameterDecl.model_validate({"mode": mode})


# ---------------------------------------------------------------------------
# CalibOutputDecl
# ---------------------------------------------------------------------------


class TestCalibOutputDecl:
    def test_minimal_declaration_defaults(self):
        decl = CalibOutputDecl.model_validate(
            {"variable": "head", "support": "cell", "row": 0, "col": 0}
        )
        assert decl.variable == "head"
        assert decl.support == "cell"
        assert decl.time == "all"
        assert decl.reducer == "none"
        assert decl.observed_values is None

    def test_observed_values_round_trip(self):
        decl = CalibOutputDecl.model_validate(
            {
                "variable": "head",
                "support": "point",
                "x": 150.0,
                "y": 0.0,
                "observed_values": [42.1, 41.8, 41.5],
            }
        )
        assert decl.observed_values == [42.1, 41.8, 41.5]
        assert decl.x.to("m").magnitude == 150.0

    def test_x_accepts_pint_string(self):
        decl = CalibOutputDecl.model_validate(
            {
                "variable": "head",
                "support": "point",
                "x": "100 m",
                "y": "0 m",
            }
        )
        assert decl.x.to("m").magnitude == 100.0

    def test_time_accepts_list_of_timestamps(self):
        decl = CalibOutputDecl.model_validate(
            {
                "variable": "head",
                "support": "cell",
                "row": 0,
                "col": 0,
                "time": ["2020-01-01", "2020-06-01"],
            }
        )
        assert decl.time == ["2020-01-01", "2020-06-01"]

    @pytest.mark.parametrize(
        "support, extra",
        [
            ("point", {"x": 0.0, "y": 0.0}),
            ("boundary", {"boundary_id": "outlet"}),
            ("cell", {"row": 0, "col": 0}),
        ],
    )
    def test_support_literal(self, support: str, extra: dict):
        decl = CalibOutputDecl.model_validate({"variable": "head", "support": support, **extra})
        assert decl.support == support

    def test_rejects_unknown_support(self):
        with pytest.raises(ValidationError, match="support"):
            CalibOutputDecl.model_validate({"variable": "head", "support": "area"})

    def test_rejects_extra_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibOutputDecl.model_validate(
                {
                    "variable": "head",
                    "support": "cell",
                    "row": 0,
                    "col": 0,
                    "legacy_hint": True,
                }
            )

    def test_point_support_requires_xy(self):
        with pytest.raises(ValidationError, match="support='point' requires"):
            CalibOutputDecl.model_validate({"variable": "head", "support": "point"})
        with pytest.raises(ValidationError, match="support='point' requires"):
            CalibOutputDecl.model_validate({"variable": "head", "support": "point", "x": 1.0})

    def test_boundary_support_requires_boundary_id(self):
        with pytest.raises(ValidationError, match="support='boundary' requires"):
            CalibOutputDecl.model_validate({"variable": "head", "support": "boundary"})


# ---------------------------------------------------------------------------
# CalibObjectiveBlockDecl
# ---------------------------------------------------------------------------


class TestCalibObjectiveBlockDecl:
    def test_minimal_block(self):
        decl = CalibObjectiveBlockDecl.model_validate(
            {
                "name": "head_block",
                "uses_outputs": ["head_A"],
            }
        )
        assert decl.metric == "rmse"
        assert decl.weight == 1.0
        assert decl.normalize_cost is False
        assert decl.transform == "identity"

    def test_weight_must_be_positive(self):
        with pytest.raises(ValidationError, match="weight"):
            CalibObjectiveBlockDecl.model_validate(
                {"name": "b", "weight": 0.0, "uses_outputs": ["x"]}
            )

    @pytest.mark.parametrize("transform", ["identity", "log", "inverse"])
    def test_accepts_supported_transforms(self, transform: str):
        decl = CalibObjectiveBlockDecl.model_validate(
            {"name": "b", "uses_outputs": ["x"], "transform": transform}
        )
        assert decl.transform == transform

    def test_rejects_unsupported_transform(self):
        with pytest.raises(ValidationError, match="transform"):
            CalibObjectiveBlockDecl.model_validate(
                {"name": "b", "uses_outputs": ["x"], "transform": "power"}
            )

    def test_rejects_extra_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibObjectiveBlockDecl.model_validate(
                {"name": "b", "uses_outputs": ["x"], "legacy_toggle": True}
            )


# ---------------------------------------------------------------------------
# CalibrationConfig: outputs + objective_blocks + implicit block
# ---------------------------------------------------------------------------


class TestCalibrationConfigEnriched:
    def test_outputs_and_objective_blocks_round_trip(self):
        cfg = CalibrationConfig.model_validate(
            {
                "method": "cma_es",
                "max_iter": 80,
                "objective": "rmse",
                "variable": "head",
                "outputs": {
                    "head_A": {
                        "variable": "head",
                        "support": "point",
                        "x": 100.0,
                        "y": 0.0,
                        "observed_values": [42.1, 41.8, 41.5],
                    }
                },
                "objective_blocks": [
                    {
                        "name": "head_block",
                        "metric": "rmse",
                        "weight": 1.0,
                        "uses_outputs": ["head_A"],
                    }
                ],
            }
        )
        assert cfg.method == "cma_es"
        assert "head_A" in cfg.outputs
        assert cfg.outputs["head_A"].observed_values == [42.1, 41.8, 41.5]
        assert len(cfg.objective_blocks) == 1
        assert cfg.objective_blocks[0].name == "head_block"

    def test_persist_knobs_round_trip(self):
        cfg = CalibrationConfig.model_validate(
            {
                "persist_iteration_detail": "full",
                "persist_model_distribution": True,
                "rerun_best_with_outputs": True,
                "materialize_candidates": True,
                "candidates_root": "/tmp/candidates",
            }
        )
        assert cfg.persist_iteration_detail == "full"
        assert cfg.persist_model_distribution is True
        assert cfg.rerun_best_with_outputs is True
        assert cfg.materialize_candidates is True
        assert str(cfg.candidates_root) == "/tmp/candidates"

    def test_resume_session_field_is_rejected(self):
        with pytest.raises(ValidationError):
            CalibrationConfig.model_validate({"resume_session": "abcdef01"})

    def test_implicit_objective_block_built_from_objective_variable(self):
        cfg = CalibrationConfig.model_validate(
            {
                "objective": "nse",
                "variable": "discharge",
                "outputs": {
                    "discharge": {
                        "variable": "discharge",
                        "support": "boundary",
                        "boundary_id": "outlet",
                    }
                },
            }
        )
        assert len(cfg.objective_blocks) == 1
        block = cfg.objective_blocks[0]
        assert block.metric == "nse"
        assert block.uses_outputs == ["discharge"]

    def test_no_implicit_block_when_no_matching_output(self):
        cfg = CalibrationConfig.model_validate(
            {
                "objective": "nse",
                "variable": "head",
            }
        )
        assert cfg.objective_blocks == []

    def test_explicit_blocks_preserved_over_implicit(self):
        cfg = CalibrationConfig.model_validate(
            {
                "objective": "nse",
                "variable": "head",
                "outputs": {
                    "head": {"variable": "head", "support": "cell", "row": 0, "col": 0},
                },
                "objective_blocks": [
                    {
                        "name": "custom",
                        "metric": "rmse",
                        "uses_outputs": ["head"],
                    }
                ],
            }
        )
        assert len(cfg.objective_blocks) == 1
        assert cfg.objective_blocks[0].name == "custom"


# ---------------------------------------------------------------------------
# TOML round-trip with the enriched schema
# ---------------------------------------------------------------------------


class TestEnrichedTomlRoundTrip:
    def test_full_twin_benchmark_like_toml(self):
        toml_src = """
        [calibration]
        method   = "cma_es"
        max_iter = 80
        seed     = 42
        objective = "rmse"
        variable = "head"
        persist_iteration_detail = "full"
        materialize_candidates = true
        candidates_root = "/tmp/cand"

        [calibration.parameters.K_aquifer]
        bounds = [1e-6, 1e-3]
        transform = "log"
        target = "flow.param.K.field_homogeneous.value"
        mode   = "replace"

        [calibration.parameters.K_mult]
        bounds = [0.1, 10.0]
        target = "flow.param.K.field_homogeneous.value"
        mode   = "scale"

        [calibration.outputs.head_A]
        variable = "head"
        support  = "point"
        x        = 100.0
        y        = 0.0
        observed_values = [42.1, 41.8, 41.5]

        [calibration.outputs.outlet]
        variable    = "outlet_discharge"
        support     = "boundary"
        boundary_id = "outlet_drain"
        observed_values = [1.2, 1.1, 1.0]

        [[calibration.objective_blocks]]
        name   = "head_block"
        metric = "rmse"
        weight = 2.0
        uses_outputs = ["head_A"]
        normalize_cost = true

        [[calibration.objective_blocks]]
        name   = "discharge_block"
        metric = "nse"
        weight = 1.0
        uses_outputs = ["outlet"]
        """
        data = tomllib.loads(toml_src)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "cma_es"
        assert cfg.persist_iteration_detail == "full"
        assert cfg.materialize_candidates is True
        assert cfg.parameters["K_aquifer"].mode == "replace"
        assert cfg.parameters["K_aquifer"].target == "flow.param.K.field_homogeneous.value"
        assert cfg.parameters["K_mult"].mode == "scale"
        assert cfg.outputs["head_A"].x.to("m").magnitude == 100.0
        assert cfg.outputs["outlet"].boundary_id == "outlet_drain"
        assert len(cfg.objective_blocks) == 2
        assert cfg.objective_blocks[0].normalize_cost is True
        assert cfg.objective_blocks[1].metric == "nse"

    def test_extra_field_still_rejected_in_enriched_schema(self):
        payload = {
            "outputs": {
                "head_A": {
                    "variable": "head",
                    "unknown_key": 1.0,
                }
            }
        }
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibrationConfig.model_validate(payload)


# ---------------------------------------------------------------------------
# Tightening validators (Phase 3)
# ---------------------------------------------------------------------------


class TestParameterDeclTightenings:
    def test_bounds_must_be_pair(self):
        with pytest.raises(ValidationError, match="bounds"):
            CalibParameterDecl.model_validate({"bounds": [1.0]})
        with pytest.raises(ValidationError, match="bounds"):
            CalibParameterDecl.model_validate({"bounds": [1.0, 2.0, 3.0]})

    def test_bounds_pair_accepted(self):
        decl = CalibParameterDecl.model_validate({"bounds": [1.0, 2.0]})
        assert decl.bounds == [1.0, 2.0]


class TestObjectiveBlockTightenings:
    @pytest.mark.parametrize("metric", ["rmse", "nse", "kge", "mae"])
    def test_metric_accepts_known_values(self, metric: str):
        decl = CalibObjectiveBlockDecl.model_validate(
            {"name": "b", "uses_outputs": ["x"], "metric": metric}
        )
        assert decl.metric == metric

    def test_metric_must_be_literal(self):
        with pytest.raises(ValidationError, match="metric"):
            CalibObjectiveBlockDecl.model_validate(
                {"name": "b", "uses_outputs": ["x"], "metric": "rsme"}
            )

    def test_uses_outputs_must_not_be_empty(self):
        with pytest.raises(ValidationError, match="uses_outputs"):
            CalibObjectiveBlockDecl.model_validate({"name": "b", "uses_outputs": []})


class TestCalibrationConfigCrossFieldValidators:
    def test_uses_outputs_must_reference_declared_output(self):
        with pytest.raises(ValidationError, match="uses_outputs"):
            CalibrationConfig.model_validate(
                {
                    "outputs": {
                        "head_A": {
                            "variable": "head",
                            "support": "point",
                            "x": 0.0,
                            "y": 0.0,
                        }
                    },
                    "objective_blocks": [
                        {
                            "name": "b",
                            "metric": "rmse",
                            "uses_outputs": ["unknown"],
                        }
                    ],
                }
            )

    def test_candidates_root_required_when_materialize_true(self):
        with pytest.raises(ValidationError, match="candidates_root"):
            CalibrationConfig.model_validate({"materialize_candidates": True})

    def test_candidates_root_satisfies_materialize_flag(self):
        cfg = CalibrationConfig.model_validate(
            {
                "materialize_candidates": True,
                "candidates_root": "/tmp/cand",
            }
        )
        assert cfg.materialize_candidates is True
        assert str(cfg.candidates_root) == "/tmp/cand"
