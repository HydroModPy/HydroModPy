"""Tests for CLI dispatch of the enriched [calibration] schema.

Covers Phase 7 of the calibration integration: ``hmp run`` routes a TOML
with a rich ``[calibration]`` block (parameters + outputs + objective
blocks) through the standard workflow dispatch without raising and the
resolved workflow is ``"calibration"``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.workflow.dispatch import (
    KNOWN_WORKFLOWS,
    extract_workflow_field,
    load_raw_toml,
    resolve_workflow,
)


def _write_rich_calibration_toml(path: Path) -> Path:
    content = """
[workflow]
mode = "calibration"

[calibration]
method = "grid"
max_iter = 20
seed = 42
objective = "rmse"
variable = "head"

[calibration.parameters.K_aquifer]
bounds = [1e-6, 1e-3]
transform = "log"
target = "flow.param.K.field.value"
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
        assert cfg.method == "grid"
        assert "K_aquifer" in cfg.parameters
        assert cfg.parameters["K_aquifer"].target == "flow.param.K.field.value"
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
        from hydromodpy.workflow.dispatch import WorkflowMissingError

        with pytest.raises(WorkflowMissingError):
            resolve_workflow(path, cli_workflow=None, require_toml_field=True)


def _write_analytic_bowl_toml(path: Path) -> Path:
    """A calibration TOML that runs no HydroModPy model.

    ``evaluator = "analytic_bowl"`` keeps ``run_calibration_cli`` off the
    prepared-model path, so the test reaches the ``objective=`` check in
    milliseconds and needs no simulation config at all.
    """
    content = """
[calibration]
method = "grid"
max_iter = 2
evaluator = "analytic_bowl"
use_cache = false

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
"""
    path.write_text(content, encoding="utf-8")
    return path


class TestObjectiveEntryPointIsNotAMetricName:
    """``objective=`` is a ``module.path:fn`` entry point, never a metric name.

    D230 refuses a call that renames a metric extractor's route by naming
    both the built and the requested pair. The same principle applies here:
    a call that writes ``objective="kge"`` believing it selects a metric
    must be refused, naming the value it wrote, rather than silently
    calibrating on whatever ``[calibration] objective`` already declares.
    """

    def test_a_bare_metric_name_is_refused(self, tmp_path: Path):
        # The value is deliberately one no fixed part of the message could
        # contain. Matching on "kge" would pass on a refusal that never echoes
        # what it was handed, as long as the static text happened to list the
        # known metric names -- and the property this class exists for is that
        # the refusal NAMES the value.
        toml = _write_analytic_bowl_toml(tmp_path / "calib.toml")

        with pytest.raises(CalibrationError) as excinfo:
            run_calibration_cli(toml, objective="nse_seasonal_v2")

        message = str(excinfo.value)
        assert "objective='nse_seasonal_v2'" in message
        assert "module.path:callable" in message
        assert "[calibration]" in message
        assert "objective_blocks" in message

    def test_the_refusal_comes_before_the_model_is_prepared(self, tmp_path: Path, monkeypatch):
        """A refused call pays nothing and leaves nothing behind.

        The check reads one argument. Placed where the value is consumed it
        sat behind ``prepare_trials`` and behind the catalog being opened, so
        a refused call ran the whole geographic, mesh and data prefix first and
        left a catalog, a lock and a WAL in a workspace where no calibration
        ever ran.
        """
        from hydromodpy.calibration.runners import cli_runner

        def _never(*args, **kwargs):
            raise AssertionError("prepare_trials must not run for a refused objective")

        monkeypatch.setattr(cli_runner, "prepare_trials", _never)
        toml = _write_analytic_bowl_toml(tmp_path / "calib.toml")

        with pytest.raises(CalibrationError):
            run_calibration_cli(toml, objective="nse_seasonal_v2")

        assert not (tmp_path / ".hmp").exists()

    def test_a_staged_run_that_reuses_every_phase_still_refuses(self, tmp_path: Path):
        """The reuse branch returns before the search, so the guard cannot live there.

        With ``reuse_completed_phases`` and a resume id, a staged run can hand
        back a full report without ever reaching the search the check used to
        sit in -- and the value reaches the reuse fingerprint regardless.
        """
        from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

        content = _write_analytic_bowl_toml(tmp_path / "staged.toml").read_text(encoding="utf-8")
        content += """
reuse_completed_phases = true

[[calibration.phases]]
name = "one"
method = "grid"
max_iter = 2
parameters = ["K"]
variable = "discharge"
objective = "nse"
"""
        toml = tmp_path / "staged.toml"
        toml.write_text(content, encoding="utf-8")

        with pytest.raises(CalibrationError) as excinfo:
            run_staged_calibration(toml, objective="nse_seasonal_v2", resume_root_session_id="r")

        assert "objective='nse_seasonal_v2'" in str(excinfo.value)

    def test_a_well_formed_entry_point_is_not_refused(self, tmp_path: Path, monkeypatch):
        """A genuine ``module.path:fn`` spec must still resolve, not be caught by the guard."""
        import sys
        import types

        def _metric(ctx, *, objective, variable):
            return 0.5, {}

        mod = types.ModuleType("test_cli_dispatch_metric_mod")
        mod.my_metric = _metric
        monkeypatch.setitem(sys.modules, "test_cli_dispatch_metric_mod", mod)

        toml = _write_analytic_bowl_toml(tmp_path / "calib.toml")

        summary = run_calibration_cli(toml, objective="test_cli_dispatch_metric_mod:my_metric")
        assert summary["n_iterations"] > 0
