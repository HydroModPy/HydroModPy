"""Tests for the enriched [calibration] TOML schema.

Covers the Phase 1 additions to :mod:`hydromodpy.calibration.config`:

- CalibParameterDecl gains target / mode / parameterization / property / lithology_key.
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
    CalibrationConfig,
)

# ---------------------------------------------------------------------------
# CalibOutputDecl
# ---------------------------------------------------------------------------


class TestCalibOutputDecl:
    def test_minimal_declaration_defaults(self):
        decl = CalibOutputDecl.model_validate({"variable": "head"})
        assert decl.variable == "head"
        assert decl.support == "point"
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
        assert decl.x == 150.0

    def test_time_accepts_list_of_timestamps(self):
        decl = CalibOutputDecl.model_validate(
            {
                "variable": "head",
                "time": ["2020-01-01", "2020-06-01"],
            }
        )
        assert decl.time == ["2020-01-01", "2020-06-01"]

    @pytest.mark.parametrize("support", ["point", "boundary", "cell"])
    def test_support_literal(self, support: str):
        decl = CalibOutputDecl.model_validate({"variable": "head", "support": support})
        assert decl.support == support

    def test_rejects_unknown_support(self):
        with pytest.raises(ValidationError, match="support"):
            CalibOutputDecl.model_validate({"variable": "head", "support": "area"})

    def test_rejects_extra_keys(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            CalibOutputDecl.model_validate({"variable": "head", "legacy_hint": True})


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
                "resume_session": "abcdef01",
                "rerun_best_with_outputs": True,
                "materialize_candidates": True,
                "candidates_root": "/tmp/candidates",
            }
        )
        assert cfg.persist_iteration_detail == "full"
        assert cfg.persist_model_distribution is True
        assert cfg.resume_session == "abcdef01"
        assert cfg.rerun_best_with_outputs is True
        assert cfg.materialize_candidates is True
        assert str(cfg.candidates_root) == "/tmp/candidates"

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
                    "head": {"variable": "head"},
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
        path = "flow.param.K.field_homogeneous.value"

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
        assert cfg.parameters["K_aquifer"].path == "flow.param.K.field_homogeneous.value"
        assert cfg.outputs["head_A"].x == 100.0
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
