"""Tests for CLI dispatch of the enriched [calibration] schema.

Covers Phase 7 of the calibration integration: ``hmp run`` routes a TOML
with a rich ``[calibration]`` block (parameters + outputs + objective
blocks) through the standard workflow dispatch without raising and the
resolved workflow is ``"calibration"``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy._cli.workflows import (
    KNOWN_WORKFLOWS,
    extract_workflow_field,
    load_raw_toml,
    resolve_workflow,
)
from hydromodpy.calibration.config import CalibrationConfig


def _write_rich_calibration_toml(path: Path) -> Path:
    content = """
workflow = "calibration"

[calibration]
method = "cma_es"
max_iter = 20
seed = 42
objective = "rmse"
variable = "head"

[calibration.parameters.K_aquifer]
bounds = [1e-6, 1e-3]
transform = "log"
target = "flow.param.K.value"
mode = "replace"

[calibration.outputs.head_A]
variable = "head"
support = "point"
x = 100.0
y = 0.0
observed_values = [42.1, 41.8, 41.5]

[[calibration.objective_blocks]]
name = "head_block"
metric = "rmse"
weight = 1.0
uses_outputs = ["head_A"]
"""
    path.write_text(content, encoding="utf-8")
    return path


class TestDispatchCalibrationEnriched:
    def test_calibration_is_a_known_workflow(self):
        assert "calibration" in KNOWN_WORKFLOWS

    def test_rich_toml_resolves_to_calibration(self, tmp_path: Path):
        path = _write_rich_calibration_toml(tmp_path / "calib.toml")
        resolved = resolve_workflow(path, cli_workflow=None, require_toml_field=True)
        assert resolved == "calibration"

    def test_rich_calibration_section_parses_through_pydantic(self, tmp_path: Path):
        path = _write_rich_calibration_toml(tmp_path / "calib.toml")
        data = load_raw_toml(path)
        cfg = CalibrationConfig.model_validate(data["calibration"])
        assert cfg.method == "cma_es"
        assert "K_aquifer" in cfg.parameters
        assert cfg.parameters["K_aquifer"].target == "flow.param.K.value"
        assert cfg.parameters["K_aquifer"].mode == "replace"
        assert "head_A" in cfg.outputs
        assert cfg.outputs["head_A"].observed_values == [42.1, 41.8, 41.5]
        assert len(cfg.objective_blocks) == 1
        assert cfg.objective_blocks[0].metric == "rmse"

    def test_workflow_field_extraction(self, tmp_path: Path):
        path = _write_rich_calibration_toml(tmp_path / "calib.toml")
        data = load_raw_toml(path)
        assert extract_workflow_field(data) == "calibration"

    def test_toml_without_workflow_field_requires_it(self, tmp_path: Path):
        path = tmp_path / "no_workflow.toml"
        path.write_text("[calibration]\nmethod = 'grid'\n", encoding="utf-8")
        from hydromodpy._cli.workflows import WorkflowMissingError

        with pytest.raises(WorkflowMissingError):
            resolve_workflow(path, cli_workflow=None, require_toml_field=True)
