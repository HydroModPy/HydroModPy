"""Tests of `runners.cli_runner`."""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import logging
import math
import os
import shutil
import socket
import sys
import textwrap
import time
from contextlib import nullcontext
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn
from unittest.mock import Mock, patch

import numpy as np
import pytest
from pydantic import ValidationError

import hydromodpy.calibration.runners.state as state
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.config_outputs import validate_calib_output
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.metrics.solver_extract import _scoring_options
from hydromodpy.calibration.optim import engine as engine_mod
from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.cache import ParamsHashCache, context_fingerprints
from hydromodpy.calibration.optim.cache import params_hash as params_hash__resumed_session
from hydromodpy.calibration.optim.cost_margin import IntervalWidth, ParameterInterval
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import DEFAULT_PHASE, CalibrationPersistence, PhaseContext
from hydromodpy.calibration.preflight_report import comparison_lines
from hydromodpy.calibration.protocols.registry import get_protocol, protocol_record
from hydromodpy.calibration.report import CalibrationReport, promotion_failures
from hydromodpy.calibration.runners import (
    cli_runner,
    document,
    search,
    search_record,
    session_scope,
    staged_runner,
    trial,
)
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.calibration.runners.document import (
    describe_dry_run,
    load_toml_calibration,
    session_cost_name,
)
from hydromodpy.calibration.runners.failure_watch import EveryTrialFailedError
from hydromodpy.calibration.runners.kept_solves import KeptSolve, TrialSolveRetention
from hydromodpy.calibration.runners.restarts import RestartSpread
from hydromodpy.calibration.runners.search import (
    _engine_kwargs,
    _first_trial_pairing,
    attach_a_linearized_width,
    parameter_widths,
    run_calibration_core,
    run_one_search,
)
from hydromodpy.calibration.runners.search_record import (
    log_parameter_interval,
    margin_intervals_or_none,
    network_ratios_extra,
    r_optim_verdict_extra,
)
from hydromodpy.calibration.runners.session import freeze_session_config, search_windows
from hydromodpy.calibration.runners.session_scope import (
    abort_session,
    promote_and_close,
    refuse_a_phase_another_cost_scored,
)
from hydromodpy.calibration.runners.staged_report import phase_summaries
from hydromodpy.calibration.runners.staged_runner import _phase_config, run_staged_calibration
from hydromodpy.calibration.runners.state import build_cache_context, space_from_config
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.code_fingerprint import (
    clear_fingerprint_cache,
    code_fingerprint,
    fingerprint_tree,
)
from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning
from hydromodpy.core.config_kit.field_param.sections import FieldHomogeneousSection
from hydromodpy.core.exceptions import CalibrationError, ConfigError, ObjectiveError
from hydromodpy.core.runtime.interrupts import StopRequested, TerminationRequested
from hydromodpy.core.scoring.stream_defaults import VALIDITY_PROVENANCE_CODE
from hydromodpy.core.state import host as host_module
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.project.facade import Project
from hydromodpy.results.heartbeat import read_heartbeat
from hydromodpy.results.metric_rule import MetricsConfig, PeriodWindow
from hydromodpy.results.outcome import effective_status, outcome_path, read_outcome, write_outcome
from hydromodpy.results.session.descriptor import (
    ParameterWidth,
    RestartRange,
    list_session_dirs,
    read_session,
    write_session,
)
from hydromodpy.results.session.journal import read_trials, trials_path
from hydromodpy.results.session.phase import FrozenValue, read_phase
from hydromodpy.results.storage.attempt import request_stop
from hydromodpy.solver.base.simulation_config import SimulationTimeConfig
from hydromodpy.workflow.dispatch import (
    KNOWN_WORKFLOWS,
    WorkflowUnknownError,
    extract_workflow_field,
    load_raw_toml,
    resolve_workflow,
)
from tests._helpers.persisting_simulation import SimulationStub
from tests._helpers.session_documents import calibration_window, session_opening
from tests.unit.calibration._factories_config import (
    PROCESS,
    PROJECT_BASE,
    messages,
    preflight_of,
    toml_doc,
)
from tests.unit.calibration._factories_runners import (
    STAGED_HEAD,
    TWO_PHASES,
    FakePipeline,
    FakeRunner,
    bare_trial_ctx,
    journal_trial,
    make_config,
    make_report,
    make_session,
    write_document,
)
from tests.unit.calibration._factories_search import result_of

# Every search here runs real trials, so the module asks for the trial pipeline
# the way a session would: filled once by the project package, before the first
# trial forks.
pytestmark = pytest.mark.usefixtures("ensure_bootstrap")

# From test_a_calibration_file_takes_the_user_migration.py
# A calibration file goes through the migration of user files when it is read: a table
# the register moves is read under its new name and warns, a key only a pre-release wrote
# is refused.


_TOML = """\
[calibration]
method = "grid"
objective = "nse"

[calibration.parameters.K]
bounds = [1e-8, 1e-2]
search_space = "log"

[modflow6]
sgrid = {}
"""


def test_a_user_file_keeps_the_user_migration(tmp_path: Path) -> None:
    user = tmp_path / "calibration.toml"
    user.write_text(_TOML, encoding="utf-8")

    with pytest.warns(ConfigKeyRenamedWarning, match="hmp doctor --fix-config"):
        cfg, raw = load_toml_calibration(user)

    assert cfg.method == "grid"
    assert "modflow6" not in raw
    assert raw["solver"]["modflow6"] == {"sgrid": {}}


def test_a_user_file_with_a_key_of_a_pre_release_is_refused(tmp_path: Path) -> None:
    user = tmp_path / "calibration.toml"
    user.write_text(
        _TOML.replace("[modflow6]\nsgrid = {}", "[simulation.results.budget]\nx = 1"),
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigError, match=r"holds simulation\.results\.budget, written by a pre-release"
    ):
        load_toml_calibration(user)


# From test_a_calibration_that_names_no_method.py
# A calibration that names no method gets the one its criteria call for.
#
# A phase, or a calibration run in one stage, that does not write ``method`` runs
# ``bisection`` when it moves one parameter in log space and every one of its
# blocks is signed: the answer is then a zero to find. Every other search runs
# ``scipy_nelder_mead``, a cost to minimize. A written method is kept as written.
#
# No solver runs. The choice is read off the configuration, the listing off the
# CLI, and the one run goes through the closed-form ``analytic_bowl`` evaluator.


STAGED = """
[calibration]
max_trials = 5

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
search_space = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.001, 0.3]
target = "flow.param.Sy.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0, 3.0]

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["q"]

[[calibration.phases]]
name = "k_gap"
parameters = ["K"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "k_sy_gap"
parameters = ["K", "Sy"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "k_nse_log"
parameters = ["K"]
objective_blocks = ["hydrograph"]

[[calibration.phases]]
name = "sy_gap"
parameters = ["Sy"]
objective_blocks = ["network"]

[[calibration.phases]]
name = "k_mixed"
parameters = ["K"]
objective_blocks = { network = 1, hydrograph = 1 }

[[calibration.phases]]
name = "k_written"
method = "grid"
parameters = ["K"]
objective_blocks = ["network"]
"""

EXPECTED = {
    "k_gap": ("bisection", "one log parameter, signed criterion"),
    "k_sy_gap": ("scipy_nelder_mead", "signed criterion on 2 parameters, cost to minimise"),
    "k_nse_log": ("scipy_nelder_mead", "cost to minimise"),
    "sy_gap": ("scipy_nelder_mead", "signed criterion, Sy not in log space, cost to minimise"),
    "k_mixed": ("scipy_nelder_mead", "cost to minimise"),
    "k_written": ("grid", None),
}


@pytest.fixture
def staged(tmp_path: Path) -> CalibrationConfig:
    cfg, _raw = load_toml_calibration(write_document(tmp_path, STAGED))
    return cfg


@pytest.mark.fast
@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_phase_gets_the_method_its_criteria_call_for(staged, name) -> None:
    phase = next(decl for decl in staged.phases if decl.name == name)

    assert staged.method_for(phase) == EXPECTED[name]
    # The phase runs under that name: the session, the params hash and the
    # report all read it off this configuration.
    assert _phase_config(staged, phase).method == EXPECTED[name][0]


@pytest.mark.fast
def test_the_listing_gives_the_reason_only_for_a_chosen_method(staged) -> None:
    rows = {row["name"]: row for row in phase_summaries(staged)}

    for name, (method, reason) in EXPECTED.items():
        assert rows[name]["method"] == method
        assert rows[name].get("method_reason") == reason
    assert "method_reason" not in rows["k_written"]


@pytest.mark.fast
def test_list_phases_names_the_reason(tmp_path, capsys) -> None:
    path = write_document(tmp_path, STAGED)
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )

    # Each phase's own line starts with its index; a block it compares prints
    # an indented line under it, so filter those out to keep one entry per
    # phase, the way the file's own dict-based check already reads them.
    lines = [line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")]
    assert lines[0].split("\t") == [
        "0",
        "k_gap",
        "bisection (one log parameter, signed criterion)",
        "",
        "width one mesh cell (default, measured on the mesh when the phase runs)",
        "takes from [calibration]: max_trials 5",
    ]
    assert lines[2].split("\t")[2] == "scipy_nelder_mead (cost to minimise)"
    # k_written moves K again, which a column after the width says.
    assert lines[5].split("\t")[:4] == ["5", "k_written", "grid", ""]


@pytest.mark.fast
def test_list_phases_names_the_method_of_a_file_without_phases(tmp_path, capsys) -> None:
    """A file without phases still runs one search, so the listing names its method."""

    path = write_document(tmp_path, SINGLE_STAGE)
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )

    out = capsys.readouterr().out.splitlines()
    assert out[0].split("\t") == ["[calibration]", "scipy_nelder_mead (cost to minimise)"]


@pytest.mark.fast
def test_method_options_without_a_method_are_refused() -> None:
    with pytest.raises(ValidationError, match="phase 'p' gives method_options and no method"):
        CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3]}},
                "phases": [
                    {"name": "p", "parameters": ["K"], "method_options": {"sweep_points": 3}}
                ],
            }
        )
    with pytest.raises(ValidationError, match=r"\[calibration\] gives method_options"):
        CalibrationConfig.model_validate({"method_options": {"points_per_dim": 3}})


@pytest.mark.fast
def test_method_options_beside_a_method_are_kept() -> None:
    phase = CalibPhaseDecl.model_validate(
        {
            "name": "p",
            "method": "bisection",
            "parameters": ["K"],
            "method_options": {"sweep_points": 3},
        }
    )

    assert phase.method_options == {"sweep_points": 3}


@pytest.mark.fast
def test_the_default_is_no_longer_grid() -> None:
    assert CalibrationConfig.model_validate({}).method is None
    assert CalibPhaseDecl.model_validate({"name": "p", "parameters": ["K"]}).method is None


SINGLE_STAGE = """
[calibration]
max_trials = 6
evaluator = "analytic_bowl"
use_cache = false

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"
"""


@pytest.mark.fast
def test_a_single_stage_calibration_with_no_method_runs_the_chosen_one(tmp_path) -> None:
    """One log parameter scored on ``objective`` (nse), which is not signed: a minimiser."""
    path = write_document(tmp_path, SINGLE_STAGE)

    report = run_calibration_cli(path, workspace=tmp_path)

    assert report.method == "scipy_nelder_mead"
    assert report.n_trials >= 1
    journals = list(tmp_path.rglob("session.json"))
    assert len(journals) == 1
    session = json.loads(journals[0].read_text(encoding="utf-8"))
    assert session["method"] == "scipy_nelder_mead"


PROJECT = """
[workspace]

[workflow]
mode = "calibration"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[geographic]
source_mode = "synthetic"

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5
"""

BARE_K_ON_THE_GAP = toml_doc(
    """
    base_config = "project.toml"
    @KB
    @NET
    @GAP
    """
)


@pytest.mark.fast
def test_python_mode_resolves_a_bare_name_and_chooses_as_the_toml_does(tmp_path) -> None:
    """A bare ``K`` is searched in the log space its field declares, from Python too.

    Left unresolved, it would search a linear space and get a minimiser where the
    same intent written in a file gets a root search.
    """

    project_toml = write_document(
        tmp_path, PROJECT.format(root=tmp_path.as_posix()), "project.toml"
    )
    toml_cfg, _raw = load_toml_calibration(write_document(tmp_path, BARE_K_ON_THE_GAP))
    # The launch preflight looks for the geometry where the run would.
    (tmp_path / "streams.gpkg").write_bytes(b"")

    class _Project:
        _cfg = HydroModPyConfig.from_toml(project_toml)
        _config_path = project_toml
        _ctx = None

    with patch(
        "hydromodpy.calibration.runners.programmatic_runner.run_calibration_programmatic",
        return_value=None,
    ) as mocked:
        Project.calibrate(
            _Project(),
            parameters={"K": {"bounds": [1e-7, 1e-3]}},
            outputs={"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
            objective_blocks=[
                {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        )
    python_cfg = mocked.call_args.args[0]

    assert python_cfg.parameters["K"].search_space == "log"
    assert python_cfg.parameters["K"].path == toml_cfg.parameters["K"].path
    assert python_cfg.method_for() == toml_cfg.method_for()
    assert python_cfg.method_for() == ("bisection", "one log parameter, signed criterion")


# From test_a_failed_perturbed_run_leaves_no_width.py
# A perturbed run that fails leaves the answer without a linearized width.
#
# ``linearized`` takes one run per parameter around the answer, then the answer
# itself. A run that fails, or that a water-budget rejection marks failed, used
# to leave the vector of the run before it in place: the Jacobian took a stale
# column, or the first failure raised a bare ``KeyError`` that lost the search
# already paid for. The width is now withheld, with the reason, and the
# calibrated values stand.


ANSWER = {"K": 2.0, "Sy": 0.5}
CFG = SimpleNamespace(
    outputs={},
    objective_blocks=[],
    window=None,
    phases=[],
    validation_window=None,
    validation_scored_by=lambda phase: False,
    aggregate=SimpleNamespace(min_samples=1),
    objective="nse",
    variable="discharge",
    reject_water_budget_above=1.0,
    parallel=1,
)


ENDED = {"primary_metric": 0.0, "duration_s": 0.0}


def _capture(*args, **kwargs):
    captured: dict = {}

    def metric_fn(trial_ctx, *, objective=None, variable=None):
        values = trial_ctx
        captured["simulated"] = np.array([values["K"], values["K"] + values["Sy"]])
        captured["observed"] = np.array([2.1, 2.4])
        return 0.0, {}

    return metric_fn, captured


def _runs(fail_when, *, scores_before_failing: bool):
    def run_trial_light(trial_ctx, values, *, metric_fn, **kwargs):
        if fail_when(values):
            if scores_before_failing:
                metric_fn(values)
            return SimpleNamespace(**ENDED, status="failed", error="water budget 3.2 %")
        metric_fn(values)
        return SimpleNamespace(**ENDED, status="completed", error=None)

    return run_trial_light


@pytest.mark.parametrize(
    ("fail_when", "scores_before_failing"),
    [
        (lambda values: values["Sy"] != ANSWER["Sy"], False),
        (lambda values: values["Sy"] != ANSWER["Sy"], True),
        (lambda values: True, False),
    ],
    ids=["failed_run", "failed_after_scoring", "first_run_failing_keeps_the_search"],
)
def test_a_failed_perturbed_run_leaves_the_answer_without_width(
    monkeypatch, caplog, fail_when, scores_before_failing
) -> None:
    monkeypatch.setattr(composite, "build_paired_vector_capture", _capture)
    monkeypatch.setattr(
        trial, "run_trial_light", _runs(fail_when, scores_before_failing=scores_before_failing)
    )
    report = SimpleNamespace(best_parameters=dict(ANSWER), parameter_uncertainty=None)

    with caplog.at_level(logging.WARNING):
        kept = attach_a_linearized_width(
            report,
            cfg=CFG,
            trial_ctx=bare_trial_ctx(),
            space=SimpleNamespace(names=("K", "Sy")),
            perturbation=0.01,
        )

    assert kept is report
    assert kept.parameter_uncertainty is None
    assert "No width is reported" in caplog.text
    assert "ended failed: water budget 3.2 %" in caplog.text


@pytest.mark.parametrize(
    ("method", "parallel", "width"),
    [("scipy_de", 3, 3), ("optuna", 2, 2), ("scipy_nelder_mead", 3, None)],
)
def test_the_width_reaches_the_engines_that_take_it(method, parallel, width) -> None:
    cfg = make_config(method=method, parallel=parallel)

    kwargs = _engine_kwargs(cfg, space_from_config(cfg), start_at=None)

    assert kwargs.get("width") == width


@pytest.mark.parametrize(
    ("restarts", "indices"), [(None, [0]), (3, [0, 1, 2])], ids=["one_search", "three_restarts"]
)
def test_restarts_run_on_one_pool_that_the_search_closes(monkeypatch, restarts, indices) -> None:
    pools: list = []
    seen: list = []

    class Pool:
        def __init__(self, evaluator_class, options, *, width):
            self.width, self.closed = width, False
            pools.append(self)

        def close(self):
            self.closed = True

    def core(cfg, trial_ctx, *, pool_for, phase, **_):
        pool = pool_for(object, {}, width=cfg.parallel)
        seen.append((phase.restart, pool))
        return make_report(best_cost=1.0 + phase.restart, best_parameters={"K": 1e-5})

    monkeypatch.setattr(search, "TrialWorkerPool", Pool)
    monkeypatch.setattr(search, "run_calibration_core", core)
    uncertainty = (
        {"uncertainty": {"method": "multistart", "restarts": restarts}} if restarts else {}
    )
    cfg = make_config(method="scipy_nelder_mead", parallel=2, **uncertainty)
    recorded: list[tuple[str, dict]] = []
    persistence = SimpleNamespace(
        record_optimizer=lambda phase, **fields: recorded.append((phase, fields))
    )

    run_one_search(
        cfg,
        bare_trial_ctx(),
        persistence=persistence,
        space=space_from_config(cfg),
        project_root=Path("."),
        cfg_path=Path("."),
        metric_fn=None,
        objective=None,
        phase=PhaseContext(),
    )

    assert sorted(restart for restart, _ in seen) == indices
    [pool] = pools
    assert (pool.width, pool.closed) == (2, True)
    assert all(shared is pool for _, shared in seen)
    assert recorded == [(PhaseContext().name, {"seed": cfg.seed})]


# From test_a_patch_release_keeps_the_cache.py
# A release that touches no computing code keeps ``--resume`` and the trial cache.
#
# The key of a trial reads the code itself, one digest per layer, and never the
# release number. So a new version string, or an edit of a docstring, moves nothing,
# and an edit of the code that computes is refused by name.


DOCUMENT = """
[simulation]
name = "patch"

[calibration]
evaluator = "analytic_bowl"
method = "grid"
max_trials = 4
seed = 7
save_runs = "none"
method_options = { points_per_dim = 4 }

[calibration.parameters.a]
bounds = [1e-6, 1e-2]
search_space = "log"
path = "flow.param.K.field.value"
"""


def _search(root: Path, *, resume: bool = False) -> CalibrationPersistence:
    path = root / "patch.toml"
    path.write_text(DOCUMENT, encoding="utf-8")
    run_calibration_cli(path, workspace=root, resume=resume)
    return CalibrationPersistence(root / "sessions" / "patch")


def _edited_layer(tmp_path: Path, layer: str, edit: tuple[str, str]) -> dict[str, str]:
    """Return the fingerprint of a copy of the package with one edit in one file of *layer*."""
    package = Path(state.__file__).resolve().parents[2]
    copy = tmp_path / "package"
    shutil.copytree(
        package / layer, copy / layer, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    target = copy / layer / "report.py"
    source = target.read_text(encoding="utf-8")
    assert edit[0] in source
    target.write_text(source.replace(edit[0], edit[1], 1), encoding="utf-8")
    clear_fingerprint_cache()
    edited = fingerprint_tree(copy, [layer])
    clear_fingerprint_cache()
    return {**code_fingerprint(), **edited}


def _copy_as_shipped(tmp_path: Path, layer: str) -> dict[str, str]:
    """Return the fingerprint of an untouched copy: the path of a file enters by its name."""
    return _edited_layer(tmp_path / "plain", layer, ("Calibration", "Calibration"))


@pytest.mark.fast
def test_a_new_release_number_reads_every_trial_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _search(tmp_path)
    solved = [line.only_case.params_hash for line in first.trials()]
    monkeypatch.setattr("hydromodpy.core.version.__version__", "2.0.1")

    again = _search(tmp_path, resume=True)

    lines = again.trials()
    assert [line.only_case.params_hash for line in lines[len(solved) :]] == solved
    assert all(line.only_case.from_cache for line in lines[len(solved) :])
    assert again.descriptor.status == "completed"


@pytest.mark.fast
def test_an_edited_docstring_moves_no_digest_and_an_edited_statement_does(tmp_path: Path) -> None:
    plain = _copy_as_shipped(tmp_path, "calibration")
    docstring = _edited_layer(
        tmp_path / "doc",
        "calibration",
        ('"""What a calibration returns', '"""A reworded calibration'),
    )
    statement = _edited_layer(
        tmp_path / "code", "calibration", ("logger = get_logger(__name__)", "logger = None")
    )
    assert docstring["calibration"] == plain["calibration"]
    assert statement["calibration"] != plain["calibration"]


@pytest.mark.fast
def test_a_resume_after_a_docstring_edit_keeps_its_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _search(tmp_path)
    n_solved = len(first.trials())
    shipped = code_fingerprint()
    monkeypatch.setattr(state, "code_fingerprint", lambda: dict(shipped))

    again = _search(tmp_path, resume=True)

    assert all(line.only_case.from_cache for line in again.trials()[n_solved:])


@pytest.mark.fast
def test_a_resume_after_a_change_of_the_computing_code_names_the_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _search(tmp_path)
    moved = {**code_fingerprint(), "solver": "another digest"}
    monkeypatch.setattr(state, "code_fingerprint", lambda: moved)

    with pytest.raises(CalibrationError, match=r"code\.solver changed since they ran"):
        _search(tmp_path, resume=True)


@pytest.mark.fast
def test_the_session_keeps_the_fingerprint_of_each_member_of_the_key(tmp_path: Path) -> None:
    case = _search(tmp_path).descriptor.cases["patch"]
    members = case.context["main"]
    assert members["schema"] == "hydromodpy.calibration.params_hash.v4"
    assert {f"code.{layer}" for layer in code_fingerprint()} <= set(members)
    assert "code_version" not in members
    assert len(members["calibration"]) == 16


def _section(extra: str = "") -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": {"a": {"bounds": [1e-6, 1e-2], "path": "flow.param.K.field.value"}},
            "method": "grid",
            **({"objective": extra} if extra else {}),
        }
    )


def _key(cfg: CalibrationConfig) -> dict[str, object]:
    space = ParameterSpace.from_toml_mapping(
        {name: decl.model_dump(exclude_none=True) for name, decl in cfg.parameters.items()}
    )
    return build_cache_context(
        cfg=cfg, trial_ctx=None, space=space, override_paths={}, objective_entrypoint=None
    )


@pytest.mark.fast
def test_a_key_written_at_its_default_is_another_key() -> None:
    default = CalibrationConfig.model_fields["objective"].default
    assert _key(_section())["calibration"] != _key(_section(str(default)))["calibration"]


_DATES = {"start_datetime": "2000-01-01", "end_datetime": "2000-12-31"}


@pytest.mark.fast
@pytest.mark.parametrize(
    ("model", "first", "second"),
    [
        (
            SimulationTimeConfig,
            {**_DATES, "step_value": "1 month"},
            {**_DATES, "step_value": "1 day"},
        ),
        (FieldHomogeneousSection, {"value": "1e-5 m/s"}, {"value": "1e-5 cm/s"}),
    ],
)
def test_a_unit_written_inside_a_value_stays_in_what_the_file_wrote(
    model: type, first: dict[str, str], second: dict[str, str]
) -> None:
    dumps = [
        model.model_validate(doc).model_dump(mode="json", exclude_unset=True)
        for doc in (first, second)
    ]
    assert dumps[0] != dumps[1]


@pytest.mark.fast
def test_a_cached_trial_reads_the_numbers_and_never_the_run_of_another_session(
    tmp_path: Path,
) -> None:
    first = _search(tmp_path)
    number = first.trials()[0].trial
    first.link_trial(number, sim_id="another-session-run", rel_dir="runs/patch")

    path = tmp_path / "patch.toml"
    run_calibration_cli(path, workspace=tmp_path)
    second = CalibrationPersistence(tmp_path / "sessions" / "patch.v2")

    cases = [line.only_case for line in second.trials()]
    assert all(case.from_cache and case.sim_id is None and not case.detail for case in cases)
    assert cases[0].components == first.trials()[0].only_case.components


@pytest.mark.fast
def test_a_live_session_pulses_and_reads_running_whatever_its_outcome_says(
    tmp_path: Path,
) -> None:

    persistence = CalibrationPersistence(tmp_path)
    persistence.start_session(**session_opening())
    persistence.start_pulse()
    try:
        beat = read_heartbeat(tmp_path)
        assert beat is not None
        assert beat.attempt_id == read_outcome(tmp_path).attempt_id
        long_ago = beat.at.timestamp() - 3600
        os.utime(outcome_path(tmp_path), (long_ago, long_ago))
        assert effective_status(tmp_path, now=beat.at + timedelta(seconds=10)) == "running"
    finally:
        persistence.stop_pulse()
    assert effective_status(tmp_path, now=beat.at + timedelta(hours=1)) == "stale"


# From test_a_resumed_session_keeps_one_cost.py
# A reopened session adds trials only under the cost that scored its journal.
#
# ``--resume`` and ``--phase`` reopen ``sessions/<case>`` and keep its trials, and
# the best trial of a phase is chosen over every line of it. A document changed
# in what moves a cost would let a trial scored the old way win under the new
# one, so the search refuses to start. A session that another live process of
# this host still writes is refused too, since both would number their trials
# alike.


PHASE = PhaseContext(name="steady_k")
SCORED_BEFORE = {"schema": "test", "calibration": "2001-2002"}
SCORED_NOW = {"schema": "test", "calibration": "2001-2003"}


def _journal(
    persistence: CalibrationPersistence, k: float, *, context: dict | None, phase=PHASE
) -> None:
    metadata: dict[str, Any] = {"parameters": {"K": {"value": k}}}
    if context is not None:
        metadata["params_hash"] = params_hash__resumed_session({"K": k}, context=context)
    journal_trial(persistence, 1, k=k, phase=phase, metadata=metadata)


class TestTheCostOfAReopenedPhase:
    def test_trials_scored_by_the_same_cost_let_the_search_go_on(self, tmp_path) -> None:
        persistence = make_session(tmp_path)
        _journal(persistence, 1e-5, context=SCORED_BEFORE)

        refuse_a_phase_another_cost_scored(persistence, PHASE.name, SCORED_BEFORE)

    @pytest.mark.parametrize(
        ("recorded", "changed"),
        [(True, "calibration changed since"), (False, "calibration, schema changed since")],
    )
    def test_trials_another_cost_scored_stop_the_search(
        self, tmp_path, recorded: bool, changed: str
    ) -> None:
        persistence = make_session(tmp_path)
        _journal(persistence, 1e-5, context=SCORED_BEFORE)
        if recorded:
            persistence.record_context(PHASE.name, context_fingerprints(SCORED_BEFORE))

        with pytest.raises(CalibrationError, match="does not score the same way") as caught:
            refuse_a_phase_another_cost_scored(persistence, PHASE.name, SCORED_NOW)

        assert changed in str(caught.value)

    def test_another_phase_is_not_read(self, tmp_path) -> None:
        persistence = make_session(tmp_path)
        _journal(persistence, 1e-5, context=SCORED_BEFORE)

        refuse_a_phase_another_cost_scored(persistence, "transient_sy", SCORED_NOW)

    def test_a_trial_without_fingerprint_is_reported_not_refused(self, tmp_path, caplog) -> None:
        persistence = make_session(tmp_path)
        _journal(persistence, 1e-5, context=None)

        with caplog.at_level(logging.WARNING):
            refuse_a_phase_another_cost_scored(persistence, PHASE.name, SCORED_NOW)

        assert "recorded no fingerprint" in caplog.text


class TestAWriterStillAlive:
    def _claimed_by(self, persistence: CalibrationPersistence, pid: int) -> None:
        outcome = read_outcome(persistence.directory)
        assert outcome is not None
        write_outcome(
            persistence.directory,
            outcome.model_copy(update={"pid": pid, "host": socket.gethostname()}),
        )

    def test_a_session_another_live_process_writes_is_not_resumed(self, tmp_path) -> None:
        persistence = make_session(tmp_path)
        self._claimed_by(persistence, os.getppid())

        with pytest.raises(CalibrationError, match="still written by process"):
            CalibrationPersistence(persistence.directory).resume_session()

    def test_a_session_whose_writer_is_gone_is_resumed(self, tmp_path, monkeypatch) -> None:
        persistence = make_session(tmp_path)
        self._claimed_by(persistence, os.getppid())
        monkeypatch.setattr(host_module, "process_is_alive", lambda pid: False)

        descriptor = CalibrationPersistence(persistence.directory).resume_session()

        assert descriptor.status == "running"

    def test_this_process_resumes_its_own_session(self, tmp_path) -> None:
        persistence = make_session(tmp_path)

        descriptor = CalibrationPersistence(persistence.directory).resume_session()

        assert descriptor.status == "running"


class TestARefusalWritesNothing:
    def test_a_refused_resume_leaves_the_session_files_as_they_were(
        self, tmp_path, monkeypatch
    ) -> None:

        persistence = make_session(tmp_path)
        _journal(persistence, 1e-5, context=SCORED_BEFORE, phase=PhaseContext(name=DEFAULT_PHASE))
        persistence.finalize_session(status="completed", best=None)
        files = [persistence.directory / "session.json", persistence.directory / "outcome.json"]
        before = [path.read_bytes() for path in files]
        monkeypatch.setattr(session_scope, "build_cache_context", lambda **_: SCORED_NOW)
        monkeypatch.setattr(session_scope, "resolve_override_paths", lambda _cfg: {})

        with pytest.raises(CalibrationError, match="does not score the same way"):
            session_scope.open_calibration_session(
                tmp_path,
                "calage",
                resume=True,
                raw={},
                cfg=SimpleNamespace(),
                space=None,
                trial_ctx=None,
                project=None,
            )

        assert [path.read_bytes() for path in files] == before


# From test_a_session_freezes_what_its_search_read.py
# The frozen document of a session reads the files its search read, and names its window.
#
# ``sessions/<case>/config.toml`` is the base of a promotion after the fact,
# which has to hash the model the search hashed. A geometry path is anchored to
# the file that declares it; read from two folders deeper, a bare filename found
# nothing, stayed relative, and moved the hash of every trial. The window the
# session scored its cost on closes an open bound with the declared period
# and reads the last phase of a staged calibration.


CASE = """\
[site]
name = "nancon"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"

[calibration]
method = "grid"
max_trials = 3

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
target = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "net.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def _case(tmp_path: Path, text: str = CASE) -> Path:
    project = tmp_path / "workspace" / "projects" / "nancon"
    project.mkdir(parents=True)
    hydrography = tmp_path / "workspace" / "data" / "hydrography"
    hydrography.mkdir(parents=True)
    (hydrography / "net.gpkg").write_bytes(b"gpkg")
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    path = project / "calage.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_frozen_document_finds_the_map_the_search_read(tmp_path) -> None:
    path = _case(tmp_path)
    cfg, raw = load_toml_calibration(path)
    session_dir = path.parent / "sessions" / "calage"
    session_dir.mkdir(parents=True)

    frozen = freeze_session_config(session_dir, raw, cfg)
    again, _ = load_toml_calibration(frozen)

    read = str(cfg.outputs["net"].map.complete)
    assert read == str((tmp_path / "workspace" / "data" / "hydrography" / "net.gpkg").resolve())
    assert str(again.outputs["net"].map.complete) == read
    assert str(tmp_path) not in frozen.read_text(encoding="utf-8")


def test_an_open_end_is_the_end_of_the_declared_period(tmp_path) -> None:
    path = _case(
        tmp_path,
        CASE.replace("max_trials = 3\n", 'max_trials = 3\nwindow = { start = "2001-01-01" }\n'),
    )
    cfg, raw = load_toml_calibration(path)

    assert search_windows(cfg, raw) == calibration_window(date(2001, 1, 1), date(2002, 12, 31))


def test_no_window_is_the_whole_declared_period(tmp_path) -> None:
    cfg, raw = load_toml_calibration(_case(tmp_path))

    assert search_windows(cfg, raw) == calibration_window(date(2000, 1, 1), date(2002, 12, 31))


def test_the_validation_window_comes_second_on_a_search_it_is_scored_on(tmp_path) -> None:
    dated = CASE.replace(
        'support = "network"\nmap.complete = "net.gpkg"\n',
        'support = "point"\nvariable = "discharge"\nobserves = "J1"\n',
    ).replace('metric = "distance_gap"', 'metric = "rmse"')
    dated = dated.replace(
        "max_trials = 3\n",
        'max_trials = 3\nvalidation_window = { start = "2002-01-01", end = "2002-12-31" }\n',
    )
    dated += '[metrics]\nwindow = { start = "2000-01-01", end = "2002-12-31" }\n'
    cfg, raw = load_toml_calibration(_case(tmp_path, dated))

    assert search_windows(cfg, raw) == {
        **calibration_window(date(2000, 1, 1), date(2001, 12, 31)),
        "validation": PeriodWindow(
            role="validation", start=date(2002, 1, 1), end=date(2002, 12, 31)
        ),
    }
    steady = CalibPhaseDecl(
        name="s",
        parameters=["K"],
        objective_blocks=["network"],
        regime="steady",
        window={"start": "2001-01-01", "end": "2001-06-30"},
    )
    assert search_windows(cfg, raw, phase=steady) == calibration_window(
        date(2001, 1, 1), date(2001, 6, 30)
    )


def test_a_count_of_skipped_samples_is_refused_with_the_way_out(tmp_path) -> None:
    path = _case(
        tmp_path, CASE.replace("max_trials = 3\n", "max_trials = 3\nwarmup_periods = 12\n")
    )

    with pytest.raises(
        ConfigError, match=r"holds calibration\.warmup_periods, written by a pre-release"
    ):
        load_toml_calibration(path)


def test_a_staged_calibration_names_the_window_of_its_last_phase(tmp_path) -> None:
    staged = CASE + (
        "\n[calibration.parameters.Sy]\n"
        "bounds = [0.01, 0.3]\n"
        'target = "flow.param.Sy.field.value"\n'
        "\n[[calibration.phases]]\n"
        'name = "steady_k"\n'
        'method = "bisection"\n'
        'parameters = ["K"]\n'
        'objective_blocks = ["network"]\n'
        "\n[[calibration.phases]]\n"
        'name = "transient_sy"\n'
        'method = "grid"\n'
        'parameters = ["Sy"]\n'
        'objective_blocks = ["network"]\n'
        'depends_on = "steady_k"\n'
        "\n[calibration.phases.window]\n"
        'start = "2001-06-01"\n'
    )
    cfg, raw = load_toml_calibration(_case(tmp_path, staged))

    assert search_windows(cfg, raw) == calibration_window(date(2001, 6, 1), date(2002, 12, 31))


# From test_a_staged_session_names_the_objective_of_its_kept_value.py
# A staged session names the objective its kept value is a cost of.
#
# ``session.json`` of a two-stage calibration wrote ``cost_name =
# "distance_gap + nse_log"``, every block of every stage joined, while its value
# and its window are those of the last stage, scored on ``nse_log`` alone. The
# promoted run inherits the name. It now names what the last stage scores.


_PARAMETERS = {
    "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
    "Sy": {"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
}
_OUTPUTS = {
    "net": {"support": "network", "map": {"complete": "streams.gpkg"}},
    "gauge": {"support": "point", "observes": "J0014", "variable": "discharge"},
}
_BLOCKS = [
    {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
    {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
]


def _staged(last: dict) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": _PARAMETERS,
            "outputs": _OUTPUTS,
            "objective_blocks": _BLOCKS,
            "phases": [
                {"name": "steady", "parameters": ["K"], "objective_blocks": ["network"]},
                {"name": "transient", "parameters": ["Sy"], **last},
            ],
        }
    )


def test_the_name_is_the_last_stage_s_metric() -> None:
    cfg = _staged({"objective_blocks": ["hydrograph"]})

    assert session_cost_name(cfg) == "nse_log"


def test_a_last_stage_on_the_single_metric_route_names_its_objective() -> None:
    cfg = _staged({"variable": "gauge", "objective": "kge"})

    assert session_cost_name(cfg) == "kge"


# From test_calibration_cli.py
# Unit tests for :mod:`hydromodpy.calibration.runners.cli_runner`.
#
# Exercises the end-to-end wiring of ``run_calibration_cli`` without
# touching MODFLOW: ``prepare_trials`` and ``promote_prepared_trial`` are
# monkey-patched to return deterministic stubs, and a custom ``metric_fn``
# is injected so each trial returns a closed-form objective. This lets us
# verify:
#
# - the session is written under ``sessions/<case>/`` and closed with its status,
# - ``save_runs`` modes (``"none"`` / ``"best_n"`` / ``"all"``) promote the
#   expected number of trials, to the directories the target names,
# - the promoted runs are linked back into ``trials.jsonl``,
# - the ``ParamsHashCache`` preloads the trials of an earlier session,
# - the ``objective="module.path:fn"`` escape hatch resolves and invokes
#   the user-supplied callable,
# - an interrupted or failed search closes its session with the right status.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
TOML_TEMPLATE = """\
[workspace]
root = "{workspace}"

[simulation]
name = "toy"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow_nwt"]

[flow.param.K.field]
value = 1e-4

[calibration]
method = "grid"
max_trials = 5
save_runs = "{save_runs}"
save_best_n = 2
seed = 42
objective = "nse"
variable = "discharge"
use_cache = true

[calibration.parameters.K]
bounds = [1e-6, 1e-3]
search_space = "log"
sampling = "log_uniform"
path = "flow.param.K.field.value"
"""


def _write__calibration_cli(
    tmp_path: Path, *, save_runs: str, name: str = "run_calibration_k"
) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    toml = tmp_path / f"{name}.toml"
    toml.write_text(
        TOML_TEMPLATE.format(workspace=str(ws).replace("\\", "/"), save_runs=save_runs),
        encoding="utf-8",
    )
    return toml


@pytest.fixture
def calib_toml(tmp_path: Path) -> Path:
    return _write__calibration_cli(tmp_path, save_runs="best_n")


def _the_session(project: Path):
    (directory,) = list_session_dirs(project)
    return directory


@pytest.fixture
def run(calib_toml, fake_pipeline, quadratic_metric):
    """Run the grid calibration of ``calib_toml`` on the fake pipeline."""
    return lambda **kwargs: run_calibration_cli(calib_toml, metric_fn=quadratic_metric, **kwargs)


def _dry_run(calib_toml: Path) -> dict:
    return describe_dry_run(
        load_toml_calibration(calib_toml)[0], calib_toml, workspace=calib_toml.parent
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestRunCalibrationCli:
    def test_run_completes_and_returns_summary(self, run, fake_pipeline):
        summary = run(project="toy_project")
        assert summary.session_id
        assert summary.method == "grid"
        assert summary.n_trials == 5
        assert summary.save_runs == "best_n"
        assert summary.best_cost is not None
        assert summary.best_trial in range(1, 6)
        # best_n with 2: the best to runs/<case>, the next one under the session
        assert summary.promoted == 2
        assert summary.best_rel_dir == "runs/toy"
        assert len(fake_pipeline) == 2

    # The file writes [simulation] name = "toy" itself, so the case is "toy" (D3).
    def test_the_session_sits_under_the_case_and_the_runs_beside_it(
        self, run, calib_toml, fake_pipeline
    ):
        run()

        project = calib_toml.parent
        assert _the_session(project) == project / "sessions" / "toy"
        assert (project / "sessions" / "toy" / "config.toml").is_file()
        dirs = [row["run_dir"] for row in fake_pipeline]
        assert dirs[0] == project / "runs" / "toy"
        assert dirs[1].parent == project / "sessions" / "toy" / "trials"
        assert fake_pipeline[0]["calibrated_by"] is not None
        assert fake_pipeline[0]["lineage"].kind == "promoted"
        assert fake_pipeline[1]["calibrated_by"] is None
        assert fake_pipeline[1]["lineage"].kind == "trial"

    def test_save_runs_none_skips_promotion(self, tmp_path, fake_pipeline, quadratic_metric):
        toml = _write__calibration_cli(tmp_path, save_runs="none", name="run")
        summary = run_calibration_cli(toml, metric_fn=quadratic_metric)
        assert summary.save_runs == "none"
        assert summary.promoted == 0
        assert fake_pipeline == []
        assert not (tmp_path / "runs").exists()

    def test_save_runs_all_promotes_every_completed(
        self, tmp_path, fake_pipeline, quadratic_metric
    ):
        toml = _write__calibration_cli(tmp_path, save_runs="all", name="run")
        summary = run_calibration_cli(toml, metric_fn=quadratic_metric)
        assert summary.save_runs == "all"
        # grid with max_trials=5: 5 trials, each one promoted
        assert summary.promoted == 5
        assert len(fake_pipeline) == 5

    def test_the_trials_are_journaled_and_linked_to_their_runs(self, run, calib_toml):
        summary = run()

        trials = read_trials(_the_session(calib_toml.parent))
        assert [t.trial for t in trials] == [1, 2, 3, 4, 5]
        linked = [t for t in trials if t.only_case.sim_id is not None]
        assert len(linked) == 2
        best = next(t for t in trials if t.trial == summary.best_trial).only_case
        assert best.sim_id == summary.best_sim_id
        assert best.rel_dir == "runs/toy"

    def test_the_session_is_closed_with_its_best(self, run, calib_toml):
        summary = run()

        session_dir = _the_session(calib_toml.parent)
        descriptor = read_session(session_dir)
        assert descriptor.status == "completed"
        assert descriptor.case_id == "toy"
        assert descriptor.best is not None
        assert descriptor.best.trial == summary.best_trial
        assert descriptor.only_run.sim_id == summary.best_sim_id
        assert descriptor.only_run.rel_dir == "runs/toy"
        outcome = read_outcome(session_dir)
        assert outcome is not None and outcome.status == "completed"
        assert (session_dir / "README.md").is_file()

    def test_a_second_run_of_the_file_takes_the_next_version(self, run):
        run()
        summary = run()

        assert summary.session_dir.name == "toy.v2"
        assert summary.best_rel_dir == "runs/toy.v2"

    def test_a_dry_run_writes_nothing(self, calib_toml, fake_pipeline):
        plan = _dry_run(calib_toml)

        assert plan["case"] == "toy"
        assert plan["version"] == "toy"
        assert plan["session_dir"] == "sessions/toy"
        assert plan["phases"][0]["parameters"] == ["K"]
        assert not (calib_toml.parent / "sessions").exists()

    def test_a_dry_run_quotes_the_version_the_session_would_take(self, run, calib_toml):
        run()

        plan = _dry_run(calib_toml)

        assert plan["version"] == "toy.v2"
        assert plan["session_dir"] == "sessions/toy.v2"
        assert plan["run_dir"] == "runs/toy.v2"
        assert not (calib_toml.parent / "sessions" / "toy.v2").exists()

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("[simulation]\nname = 'nope'\n", "No \\[calibration\\] section"),
            (
                '[calibration]\nmethod = "grid"\nmax_trials = 3\nobjective = "nse"\n'
                'variable = "discharge"\n\n[calibration.parameters.K]\nbounds = [1e-6, 1e-3]\n',
                "must declare a 'path'",
            ),
        ],
        ids=["missing_calibration_section", "parameters_without_path"],
    )
    def test_a_file_the_run_cannot_read_raises(self, tmp_path, fake_pipeline, text, match):
        with pytest.raises(ValueError, match=match):
            run_calibration_cli(write_document(tmp_path, text, "bad.toml"))


class TestCachePreload:
    def test_preload_populates_from_previous_session(self, run, monkeypatch):
        """The second session sees cache hits for every trial the first one journaled."""
        assert run().promoted == 2

        preloaded_snapshot: dict = {}
        real_preload = state.preload_hash_cache

        def spy(project_root, cache):
            n = real_preload(project_root, cache)
            preloaded_snapshot.update(cache._hits)
            return n

        monkeypatch.setattr(search, "preload_hash_cache", spy)

        run()
        assert len(preloaded_snapshot) == 5
        assert all(key.startswith("v2:") for key in preloaded_snapshot)

    def test_preload_ignores_unscoped_hashes(self, tmp_path):
        make_session(
            tmp_path,
            "old",
            costs=tuple(
                {"cost": float(n), "components": {"rmse": float(n)}, "metadata": {"params_hash": h}}
                for n, h in ((1, "legacyhash"), (2, "v2:scopedhash"))
            ),
            project="p",
            cost_name="rmse",
            bounds={},
        )

        cache = ParamsHashCache()
        n_preloaded = state.preload_hash_cache(tmp_path, cache)

        assert n_preloaded == 1
        assert "legacyhash" not in cache
        assert "v2:scopedhash" in cache


class TestObjectiveEscapeHatch:
    def test_module_fn_spec_is_loaded_and_invoked(self, calib_toml, fake_pipeline, monkeypatch):
        calls: list[dict] = []

        def my_metric(ctx, *, objective, variable):
            calls.append({"objective": objective, "variable": variable})
            return float(abs(ctx.cfg.flow.param.K.field.value - 1e-4)), {}

        monkeypatch.setitem(
            sys.modules, "test_calib_metric_mod", SimpleNamespace(my_metric=my_metric)
        )

        summary = run_calibration_cli(calib_toml, objective="test_calib_metric_mod:my_metric")
        assert summary.n_trials == 5
        assert len(calls) == 5
        assert all(c["variable"] == "discharge" for c in calls)


def test_no_default_evaluator_is_exported():
    """The user-facing path must not use the mock."""
    for module in (cli_runner, document, search, session_scope):
        assert not hasattr(module, "_default_evaluator")


class TestConfigOverridePaths:
    @staticmethod
    def _config(**parameters) -> CalibrationConfig:
        return CalibrationConfig.model_validate(
            {"method": "grid", "max_trials": 5, "objective": "nse", "variable": "discharge"}
            | {"parameters": parameters}
        )

    def test_extracts_paths_correctly(self):
        cfg = self._config(
            K={"bounds": [1e-6, 1e-3], "search_space": "log", "path": "flow.param.K.field.value"},
            Sy={"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
        )

        assert state.override_paths(cfg) == {
            "K": "flow.param.K.field.value",
            "Sy": "flow.param.Sy.field.value",
        }

    def test_all_parameters_missing_path_raises(self):
        with pytest.raises(ValueError, match="must declare a 'path'"):
            state.override_paths(self._config(K={"bounds": [1e-6, 1e-3]}))


def _fail_engine(monkeypatch, error: BaseException) -> None:
    def boom(self):
        raise error

    monkeypatch.setattr(engine_mod.CalibrationEngine, "run", boom)


def _cut_after_two_trials(monkeypatch) -> None:
    """Make the engine raise SIGTERM's exception once two trials are scored."""
    real_run_until = engine_mod.CalibrationEngine._run_until

    def _cut(self, budget, n_done, session, reporter):
        real_run_until(self, 2, n_done, session, reporter)
        raise TerminationRequested("signal 15")

    monkeypatch.setattr(engine_mod.CalibrationEngine, "_run_until", _cut)


class TestSessionLifecycle:
    """No zombie ``running`` session on disk: failures and aborts close it."""

    @pytest.mark.parametrize(
        ("error", "status", "message"),
        [
            (RuntimeError("boom from engine"), "failed", "boom from engine"),
            (KeyboardInterrupt(), "aborted", "SIGINT"),
            (TerminationRequested("signal 15"), "aborted", "SIGTERM"),
            (
                StopRequested("stop requested at 2026-11-10T09:30:00+00:00"),
                "aborted",
                "stop requested at 2026-11-10T09:30:00+00:00",
            ),
        ],
        ids=[
            "engine_failure_marks_session_failed",
            "keyboard_interrupt_marks_session_aborted",
            "sigterm_marks_session_aborted",
            "stop_request_marks_session_aborted_with_its_date",
        ],
    )
    def test_an_error_of_the_engine_closes_the_session(
        self, calib_toml, fake_pipeline, monkeypatch, error, status, message
    ):
        _fail_engine(monkeypatch, error)

        with pytest.raises(type(error)):
            run_calibration_cli(calib_toml)

        descriptor = read_session(_the_session(calib_toml.parent))
        assert (descriptor.status, descriptor.error_message) == (status, message)
        outcome = read_outcome(_the_session(calib_toml.parent))
        assert outcome is not None and outcome.status == status

    @staticmethod
    def _metric(ctx, *, objective, variable):
        return (math.log10(ctx.cfg.flow.param.K.field.value) - math.log10(1e-4)) ** 2, {}

    def test_a_termination_points_at_the_best_trial_so_far(
        self, calib_toml, fake_pipeline, monkeypatch
    ):
        """SIGTERM: ``aborted`` and the pointer of the best completed trial.

        The fake pipeline keeps no solve, so nothing is promoted: a replay
        after a signal is left to ``hmp campaign promote``.
        """
        _cut_after_two_trials(monkeypatch)

        with pytest.raises(TerminationRequested):
            run_calibration_cli(calib_toml, metric_fn=self._metric)

        session_dir = _the_session(calib_toml.parent)
        descriptor = read_session(session_dir)
        assert (descriptor.status, descriptor.error_message) == ("aborted", "SIGTERM")
        trials = read_trials(session_dir)
        assert len(trials) == 2
        assert descriptor.best is not None
        assert descriptor.best.trial == min(trials, key=lambda t: t.cost).trial
        assert descriptor.only_run.sim_id is None, "no kept solve: nothing to promote in the margin"
        assert fake_pipeline == []
        assert not (calib_toml.parent / "runs").exists()
        outcome = read_outcome(session_dir)
        assert outcome is not None and outcome.status == "aborted"

    def test_a_stop_flag_ends_the_search_between_two_trials_and_a_resume_answers_it(
        self, calib_toml, fake_pipeline
    ):
        """The flag of the session is read before each ask; reopening removes it."""
        seen: list[int] = []

        def stop_after_two(ctx, *, objective, variable):
            seen.append(len(seen) + 1)
            if len(seen) == 2:
                request_stop(_the_session(calib_toml.parent))
            return (math.log10(ctx.cfg.flow.param.K.field.value) - math.log10(1e-4)) ** 2, {}

        with pytest.raises(StopRequested):
            run_calibration_cli(calib_toml, metric_fn=stop_after_two)

        session_dir = _the_session(calib_toml.parent)
        descriptor = read_session(session_dir)
        assert descriptor.status == "aborted"
        assert (descriptor.error_message or "").startswith("stop requested at ")
        assert len(read_trials(session_dir)) == 2
        assert stop_flag_for(session_dir).is_file()

        report = run_calibration_cli(calib_toml, metric_fn=self._metric, resume=True)

        assert not stop_flag_for(session_dir).exists()
        assert read_session(session_dir).status == "completed"
        assert report.n_trials == 5

    def test_a_termination_promotes_the_best_trial_from_its_kept_solve(
        self, calib_toml, fake_pipeline, monkeypatch
    ):
        """After the pointer is written, the pointed trial is promoted from its kept solve."""
        _cut_after_two_trials(monkeypatch)
        monkeypatch.setattr(
            TrialSolveRetention,
            "take",
            lambda self, trial_id: (KeptSolve(trial_id=int(trial_id), cost=0.0, folders=()), None),
        )

        with pytest.raises(TerminationRequested):
            run_calibration_cli(calib_toml, metric_fn=self._metric)

        session_dir = _the_session(calib_toml.parent)
        descriptor = read_session(session_dir)
        assert descriptor.status == "aborted"
        (call,) = fake_pipeline
        assert call["run_dir"] == calib_toml.parent / "runs" / "toy"
        assert call["lineage"].kind == "promoted"
        assert call["calibrated_by"].session_status == "aborted"
        assert call["lineage"].trial == descriptor.best.trial
        run = descriptor.only_run
        assert (run.sim_id, run.rel_dir) == (call["sim_id"], "runs/toy")
        line = {t.trial: t for t in read_trials(session_dir)}[descriptor.best.trial].only_case
        assert (line.sim_id, line.rel_dir) == (call["sim_id"], "runs/toy")

    def test_the_abort_writes_its_pointer_in_under_a_second(self, tmp_path):
        """The pointer of a long session is written before any signal can follow."""
        persistence = make_session(tmp_path, "long", project="p", bounds={})
        for index, name in enumerate(("steady_k", "transient_sy", "transient_n")):
            context = PhaseContext(name, index, 0)
            persistence.start_phase(context, frozen={})
            for trial_id in range(300):
                journal_trial(persistence, trial_id, float(trial_id), k=1e-5, phase=context)
            if index < 2:
                persistence.finish_phase(
                    name, status="completed", best=None, widths={name: ParameterWidth(sigma=1.5)}
                )

        started = time.perf_counter()
        pointed = abort_session(persistence, phase="transient_n", error="SIGTERM")
        elapsed = time.perf_counter() - started

        assert elapsed < 1.0, f"the abort took {elapsed:.2f} s"
        assert pointed == "transient_sy", "the last completed phase, not the cut one"
        descriptor = read_session(persistence.directory)
        assert descriptor.status == "aborted"
        assert descriptor.best is not None and descriptor.best.trial == 301
        assert read_phase(persistence.directory, "transient_n").status == "aborted"
        assert read_phase(persistence.directory, "transient_sy").status == "completed"
        # The closed phases keep their widths in the session that the abort rewrites.
        assert descriptor.widths == {
            "steady_k": ParameterWidth(sigma=1.5),
            "transient_sy": ParameterWidth(sigma=1.5),
        }

    def test_all_iterations_crashed_stops_and_marks_failed(self, calib_toml, fake_pipeline):
        """A search that cannot score anything is refused, not run to its budget."""

        def crashing_metric(ctx, *, objective, variable):
            raise RuntimeError("metric blew up")

        with pytest.raises(EveryTrialFailedError, match="metric blew up"):
            run_calibration_cli(calib_toml, metric_fn=crashing_metric)

        session_dir = _the_session(calib_toml.parent)
        assert read_session(session_dir).status == "failed"
        assert len(read_trials(session_dir)) == 5


class TestAFailedPromotion:
    def test_the_report_names_the_failed_promotions_and_keeps_the_search(
        self, run, calib_toml, monkeypatch
    ):
        """A promotion that fails leaves the search sound: the report says which one."""

        def _fail_promote(*args, **kwargs):
            raise RuntimeError("step 'display' failed")

        monkeypatch.setattr(promotion_module, "promote_prepared_trial", _fail_promote)

        summary = run()

        assert summary.best_parameters
        assert summary.promoted == 0
        failures = summary.extra["promotion_failures"]
        assert len(failures) == 2
        assert all("step 'display' failed" in line for line in failures)
        assert promotion_failures(summary) == failures
        descriptor = read_session(_the_session(calib_toml.parent))
        # The search completed: a promotion failure never writes it failed.
        assert descriptor.status == "partial"
        assert "step 'display' failed" in (descriptor.error_message or "")

    def test_a_calibration_whose_promotions_succeed_names_none(self, run):
        summary = run()

        assert "promotion_failures" not in summary.extra
        assert promotion_failures(summary) == []


class TestWhatTheSessionSays:
    def test_the_session_names_the_project_it_ran_in(self, run, calib_toml):
        """Not the placeholder 'calibration': the project the file sits in."""
        run()

        session_dir = _the_session(calib_toml.parent)
        outcome = read_outcome(session_dir)
        assert outcome is not None and outcome.project == calib_toml.parent.name
        assert read_session(session_dir).cost_name == "nse"

    def test_a_named_project_is_kept(self, run, calib_toml):
        run(project="demo")

        outcome = read_outcome(_the_session(calib_toml.parent))
        assert outcome is not None and outcome.project == "demo"

    @pytest.mark.parametrize(
        ("update", "name"),
        [
            pytest.param(
                {
                    "outputs": {
                        "net": {"support": "network", "map": {"complete": "streams.gpkg"}},
                        "gauge": {"support": "point", "observes": "J0014", "variable": "discharge"},
                    },
                    "objective_blocks": [
                        {"name": "network", "metric": "distance_gap", "uses_outputs": ["net"]},
                        {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]},
                    ],
                },
                "distance_gap + nse_log",
                id="a_search_scored_by_blocks_names_its_blocks_not_the_default_pair",
            ),
            pytest.param(
                {
                    "objective": "kge",
                    "variable": "discharge",
                    "outputs": {
                        "discharge": {
                            "support": "point",
                            "observes": "J0014",
                            "variable": "discharge",
                        }
                    },
                },
                "kge",
                id="a_single_metric_search_keeps_the_pair_it_scores",
            ),
        ],
    )
    def test_the_name_of_the_cost(self, update, name):
        cfg = make_config(**update)

        assert session_cost_name(cfg) == name


class TestTheProjectDefaults:
    _SITE = '[site]\nname = "nancon"\ngauge = "NANCON"\n\n'
    _SEARCH = (
        '[calibration]\nmethod = "grid"\nmax_trials = 2\n{extra}\n'
        '[calibration.parameters.K]\nbounds = [1e-6, 1e-3]\npath = "flow.param.K.field.value"\n'
    )

    def test_the_site_gauge_is_the_station_of_the_outputs(self, tmp_path):
        text = (
            self._SITE
            + '[metrics]\nwindow = { start = "2001-01-01", end = "2002-12-31" }\n\n'
            + self._SEARCH.format(extra="")
            + '\n[calibration.outputs.gauge]\nsupport = "point"\nvariable = "discharge"\n\n'
            + '[[calibration.objective_blocks]]\nname = "hydrograph"\nmetric = "nse"\n'
            + 'uses_outputs = ["gauge"]\n'
        )

        cfg, _raw = load_toml_calibration(write_document(tmp_path, text, "calage.toml"))

        assert cfg.outputs["gauge"].observes == "NANCON"
        assert (cfg.window.start, cfg.window.end) == ("2001-01-01", "2002-12-31")

    def test_a_station_key_is_refused_for_the_gauge(self, tmp_path):
        text = self._SITE + self._SEARCH.format(extra='observed_station_id = "OTHER"')

        with pytest.raises(
            ConfigError, match=r"holds calibration\.observed_station_id, written by a pre-release"
        ):
            load_toml_calibration(write_document(tmp_path, text, "calage.toml"))


class TestAnIntervalOfOneTrial:
    def test_the_log_says_no_other_trial_rather_than_a_zero_width_interval(self, caplog):
        interval = ParameterInterval(
            name="K",
            best=1e-6,
            lower=1e-6,
            upper=1e-6,
            margin=0.05,
            kind="relative",
            threshold=0.0179,
            n_within=1,
            n_trials=5,
            reaches_lower_bound=False,
            reaches_upper_bound=False,
        )

        with caplog.at_level(logging.INFO, logger=search.logger.name):
            log_parameter_interval(interval, None)

        assert "no other trial within the cost margin" in caplog.text
        assert "[1e-06, 1e-06]" not in caplog.text


# From test_calibration_toml_errors_name_the_file.py
# A broken calibration TOML must be repairable from its own error message.
#
# The people who run a calibration read TOML, not Python. A raw Pydantic
# ``ValidationError`` reaching the terminal gives them the model class names, the
# nested field the validator happened to build, and a link to the pydantic error
# reference: nothing that says which line of which file to open.
#
# ``core/toml_io/error_locator`` already maps a validation error back to a file and
# a line. It had no call site on this path, so the config load raised raw.


_BROKEN = """\
[calibration]
method = "grid"
objective = "nse_lo"

[calibration.parameters.K]
bounds = [1e-8, 1e-2]
search_space = "log"
"""


@pytest.fixture
def broken_toml(tmp_path: Path) -> Path:
    target = tmp_path / "calibration.toml"
    target.write_text(_BROKEN, encoding="utf-8")
    return target


def test_the_message_names_the_file_the_line_and_the_key(broken_toml: Path) -> None:
    """Everything needed to fix the file, without opening a .py."""
    with pytest.raises(ConfigError) as failure:
        load_toml_calibration(broken_toml)

    message = str(failure.value)
    assert broken_toml.name in message
    assert ":3:" in message, f"the line carrying the bad value is not named: {message}"
    assert "objective" in message


def test_the_message_does_not_send_the_reader_to_pydantic(broken_toml: Path) -> None:
    """A hydrogeologist has no use for the pydantic error reference."""
    with pytest.raises(ConfigError) as failure:
        load_toml_calibration(broken_toml)

    assert "errors.pydantic.dev" not in str(failure.value)


def test_a_valid_file_still_loads(tmp_path: Path) -> None:
    """The guard only shapes the failure; it does not touch the success path."""
    target = tmp_path / "calibration.toml"
    target.write_text(_BROKEN.replace("nse_lo", "nse_log"), encoding="utf-8")

    cfg, raw = load_toml_calibration(target)

    assert cfg.objective == "nse_log"
    assert "calibration" in raw


# From test_cli_dispatch.py
# Tests for CLI dispatch of the enriched [calibration] schema.
#
# Covers Phase 7 of the calibration integration: ``hmp run`` routes a TOML
# with a rich ``[calibration]`` block (parameters + outputs + objective
# blocks) through the standard workflow dispatch without raising and the
# resolved workflow is ``"calibration"``.


def _write_rich_calibration_toml(path: Path) -> Path:
    content = """
[workflow]
mode = "calibration"

[calibration]
method = "grid"
max_trials = 20
seed = 42
variable = "head"

[calibration.parameters.K_aquifer]
bounds = [1e-6, 1e-3]
search_space = "log"
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
        resolved = resolve_workflow(path, cli_workflow=None)
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

    def test_toml_without_workflow_field_follows_its_sections(self, tmp_path: Path):
        path = tmp_path / "no_workflow.toml"
        path.write_text("[calibration]\nmethod = 'grid'\n", encoding="utf-8")

        assert resolve_workflow(path, cli_workflow=None) == "calibration"

    def test_a_retired_mode_names_its_replacement(self, tmp_path: Path):
        path = tmp_path / "old.toml"
        path.write_text('[workflow]\nmode = "comparison"\n', encoding="utf-8")

        with pytest.raises(WorkflowUnknownError, match="hmp diff"):
            resolve_workflow(path, cli_workflow=None)


@pytest.fixture
def bowl(tmp_path: Path) -> Path:
    """A calibration TOML that runs no HydroModPy model.

    ``evaluator = "analytic_bowl"`` keeps ``run_calibration_cli`` off the
    prepared-model path, so the test reaches the ``objective=`` check in
    milliseconds and needs no simulation config at all.
    """
    text = toml_doc(
        """
        [calibration]
        method = "grid"
        max_trials = 2
        method_options = { points_per_dim = 2 }
        evaluator = "analytic_bowl"
        use_cache = false
        @K
        """
    )
    return write_document(tmp_path, text)


class TestObjectiveEntryPointIsNotAMetricName:
    """``objective=`` is a ``module.path:fn`` entry point, never a metric name.

    D230 refuses a call that renames a metric extractor's route by naming
    both the built and the requested pair. The same principle applies here:
    a call that writes ``objective="kge"`` believing it selects a metric
    must be refused, naming the value it wrote, rather than silently
    calibrating on whatever ``[calibration] objective`` already declares.
    """

    def test_a_bare_metric_name_is_refused(self, bowl: Path):
        # The value is deliberately one no fixed part of the message could
        # contain. Matching on "kge" would pass on a refusal that never echoes
        # what it was handed, as long as the static text happened to list the
        # known metric names -- and the property this class exists for is that
        # the refusal NAMES the value.
        with pytest.raises(CalibrationError) as excinfo:
            run_calibration_cli(bowl, objective="nse_seasonal_v2")

        message = str(excinfo.value)
        assert "objective='nse_seasonal_v2'" in message
        assert "module.path:callable" in message
        assert "[calibration]" in message
        assert "objective_blocks" in message

    def test_the_refusal_comes_before_the_model_is_prepared(self, bowl: Path, monkeypatch):
        """A refused call pays nothing and leaves nothing behind.

        The check reads one argument. Placed where the value is consumed it
        sat behind ``prepare_trials`` and behind the catalog being opened, so
        a refused call ran the whole geographic, mesh and data prefix first and
        left a catalog, a lock and a WAL in a workspace where no calibration
        ever ran.
        """

        def _never(*args, **kwargs):
            raise AssertionError("prepare_trials must not run for a refused objective")

        monkeypatch.setattr(search, "prepare_trials", _never)

        with pytest.raises(CalibrationError):
            run_calibration_cli(bowl, objective="nse_seasonal_v2")

        assert not (bowl.parent / ".hmp").exists()

    def test_a_staged_run_that_reuses_every_phase_still_refuses(self, bowl: Path):
        """The reuse branch returns before the search, so the guard cannot live there.

        Under ``--resume`` a staged run can hand back a full report without
        ever reaching the search the check used to sit in -- and the value
        reaches the reuse fingerprint regardless.
        """
        phase = (
            '\n[[calibration.phases]]\nname = "one"\nmethod = "grid"\nmax_trials = 2\n'
            'parameters = ["K"]\nvariable = "discharge"\nobjective = "nse"\n'
        )
        bowl.write_text(bowl.read_text(encoding="utf-8") + phase, encoding="utf-8")

        with pytest.raises(CalibrationError) as excinfo:
            run_staged_calibration(bowl, objective="nse_seasonal_v2", resume=True)

        assert "objective='nse_seasonal_v2'" in str(excinfo.value)

    def test_a_well_formed_entry_point_is_not_refused(self, bowl: Path, monkeypatch):
        """A genuine ``module.path:fn`` spec must still resolve, not be caught by the guard."""

        def _metric(ctx, *, objective, variable):
            return 0.5, {}

        monkeypatch.setitem(
            sys.modules, "test_cli_dispatch_metric_mod", SimpleNamespace(my_metric=_metric)
        )

        summary = run_calibration_cli(bowl, objective="test_cli_dispatch_metric_mod:my_metric")
        assert summary.n_trials > 0


# From test_each_phase_lists_the_window_it_scores_on.py
# ``--list-phases``, ``--dry-run`` and ``hmp check`` say what each phase scores on.
#
# They listed the metric and the station of each phase, never its window, nor
# ``[metrics] window``, the one the run is scored on and the default of a
# transient phase. The window showed only when its author copied it into the
# phase description. Each phase now prints the window it scores on, and the
# check prints ``[metrics] window`` too.


EXAMPLE_04 = Path("examples/projects/04_streamflow_intermittence_in_transient")


def _staged__each_phase() -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": {
                "K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"},
                "Sy": {"bounds": [0.01, 0.3], "path": "flow.param.Sy.field.value"},
            },
            "outputs": {
                "gauge": {"support": "point", "observes": "J0014", "variable": "discharge"},
            },
            "objective_blocks": [
                {"name": "hydrograph", "metric": "nse_log", "uses_outputs": ["gauge"]}
            ],
            "phases": [
                {"name": "first", "parameters": ["K"], "objective_blocks": ["hydrograph"]},
                {
                    "name": "second",
                    "parameters": ["Sy"],
                    "objective_blocks": ["hydrograph"],
                    "window": {"start": "2016-01-01", "end": "2020-12-31"},
                },
            ],
        }
    )


def test_each_phase_summary_carries_its_window() -> None:
    rows = phase_summaries(_staged__each_phase())

    assert [row["window"] for row in rows] == [
        "no window, all of the run",
        "window 2016-01-01 to 2020-12-31",
    ]


def test_the_check_names_the_run_window_and_each_phase_s(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        calibration=_staged__each_phase(),
        metrics=MetricsConfig.model_validate(
            {"window": {"start": "2016-01-01", "end": "2020-12-31"}}
        ),
    )

    lines = comparison_lines(cfg, tmp_path / "calibration.toml")

    assert lines[0] == "[metrics] window: 2016-01-01 to 2020-12-31, the window the run is scored on"
    assert "  scores on: no window, all of the run" in lines
    assert "  scores on: window 2016-01-01 to 2020-12-31" in lines


@pytest.mark.fast
def test_list_phases_prints_the_window_under_each_phase(capsys) -> None:
    calibrate_cmd.run(
        argparse.Namespace(
            config=EXAMPLE_04 / "run_calibration.toml",
            check=False,
            list_phases=True,
            expand=False,
            phase=None,
            profile=None,
        )
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[2] == "    scores on: no window, all of the run"
    assert lines[5] == "    scores on: window 2001-01-01 to 2002-12-31"


def test_the_dry_run_names_the_window_of_each_phase(tmp_path: Path, capsys) -> None:
    config = EXAMPLE_04 / "run_calibration.toml"
    plan = describe_dry_run(load_toml_calibration(config)[0], config, workspace=tmp_path)

    calibrate_cmd._print_dry_run(plan)

    err = capsys.readouterr().err
    assert "phase transient_storage: Sy, " in err
    assert "trials, scores on window 2001-01-01 to 2002-12-31" in err


@pytest.mark.parametrize(
    ("section", "widths", "shown"),
    [(1, [5, None], 5), (4, [None, 2], 4), (3, [], 3)],
)
def test_the_dry_run_shows_the_widest_search(
    tmp_path: Path, section: int, widths: list[int | None], shown: int
) -> None:
    config = EXAMPLE_04 / "run_calibration.toml"
    cfg = load_toml_calibration(config)[0]
    phases = [
        phase.model_copy(update={"parallel": width}) for phase, width in zip(cfg.phases, widths)
    ]
    cfg = cfg.model_copy(update={"parallel": section, "phases": phases})

    assert describe_dry_run(cfg, config, workspace=tmp_path)["solves_in_parallel"] == shown


# From test_eq4_is_read_at_the_returned_trial.py
# Eq. 4 is read once, on the trial the search returns.
#
# The paper reads ``r_optim <= 2`` at the optimum ("At this point", HESS 27,
# p. 3225). A trial on the way to the root is not the result, so every trial
# keeps ``r_optim`` and its validity length as components and only the report
# qualifies the answer. The bound is a length: ``D_optim <= validity_length_m``.


def _network(**overrides):
    return validate_calib_output(
        {"support": "network", "map": {"complete": "streams.gpkg"}, **overrides}
    )


def _components(
    r_optim: float,
    *,
    name: str = "net",
    length: float = 150.0,
    provenance: str = "auto",
) -> dict[str, float]:
    return {
        f"{name}.r_optim": r_optim,
        f"{name}.h_obs": 75.0,
        f"{name}.D_optim": 75.0 * r_optim,
        f"{name}.validity_length_m": length,
        f"{name}.validity_length_provenance": VALIDITY_PROVENANCE_CODE[provenance],
    }


def test_a_returned_trial_inside_the_bound_is_recorded_valid(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        extra = r_optim_verdict_extra({"net": _network()}, _components(1.5))

    assert extra["r_optim_verdict"]["net"] == {
        "value": 1.5,
        "D_optim": 112.5,
        "h_obs": 75.0,
        "validity_length_m": 150.0,
        "provenance": "auto",
        "valid": True,
        "causes": [],
    }
    assert "Eq. 4" not in caplog.text


def test_a_returned_trial_past_the_bound_warns_once_by_default(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        extra = r_optim_verdict_extra({"net": _network()}, _components(5.31))

    verdict = extra["r_optim_verdict"]["net"]
    assert verdict["valid"] is False and verdict["causes"] == ["doptim"]
    warnings = [record for record in caplog.records if "Eq. 4" in record.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "D_optim = 398.2 m exceeds the validity length 150 m (auto)" in message
    assert "r_optim = 5.31 cells of h_obs" in message


def test_the_verdict_reads_the_length_the_trial_published_not_a_ratio() -> None:
    # A declared accuracy of 50 m on a 25 m grid: r_optim = 3 cells of h_obs,
    # past two cells, and still inside 2 * 50 m.
    components = {
        "net.r_optim": 3.0,
        "net.h_obs": 25.0,
        "net.D_optim": 75.0,
        "net.validity_length_m": 100.0,
        "net.validity_length_provenance": VALIDITY_PROVENANCE_CODE["declared_accuracy"],
    }

    verdict = r_optim_verdict_extra({"net": _network()}, components)["r_optim_verdict"]["net"]

    assert verdict["valid"] is True
    assert verdict["provenance"] == "declared_accuracy"


def test_strict_mode_raises_a_calibration_error_on_the_returned_trial() -> None:
    output = _network(verdict={"on_invalid": "error"})

    with pytest.raises(CalibrationError, match="exceeds the validity length 150 m"):
        r_optim_verdict_extra({"net": output}, _components(5.31))


def test_strict_mode_accepts_a_returned_trial_inside_the_bound() -> None:
    output = _network(verdict={"on_invalid": "error", "validity_length": "225 m"})

    extra = r_optim_verdict_extra(
        {"net": output}, _components(2.5, length=225.0, provenance="user")
    )

    assert extra["r_optim_verdict"]["net"]["valid"] is True
    assert extra["r_optim_verdict"]["net"]["provenance"] == "user"


def test_an_empty_network_at_the_returned_trial_is_not_qualified() -> None:
    extra = r_optim_verdict_extra({"net": _network()}, _components(math.nan))

    verdict = extra["r_optim_verdict"]["net"]
    assert verdict["value"] is None and verdict["valid"] is False
    assert verdict["causes"] == ["empty"]
    with pytest.raises(CalibrationError, match="not a number"):
        r_optim_verdict_extra(
            {"net": _network(verdict={"on_invalid": "error"})}, _components(math.nan)
        )


def test_a_trial_without_a_published_length_is_not_qualified() -> None:
    components = {"net.r_optim": 1.0, "net.h_obs": 75.0, "net.D_optim": 75.0}

    verdict = r_optim_verdict_extra({"net": _network()}, components)["r_optim_verdict"]["net"]

    assert verdict["valid"] is False and verdict["validity_length_m"] is None


def test_each_network_output_gets_its_own_verdict() -> None:
    outputs = {"a": _network(), "b": _network(verdict={"validity_length": "750 m"})}
    components = {
        **_components(3.0, name="a"),
        **_components(3.0, name="b", length=750.0, provenance="user"),
    }

    verdicts = r_optim_verdict_extra(outputs, components)["r_optim_verdict"]

    assert (verdicts["a"]["valid"], verdicts["b"]["valid"]) == (False, True)


def test_nothing_is_published_without_a_network_output_or_a_best_trial() -> None:
    assert r_optim_verdict_extra({"net": _network()}, None) == {}
    assert r_optim_verdict_extra(None, _components(1.0)) == {}


class _StrictFirstPhase(FakeRunner):
    """The first phase fails Eq. 4 in strict mode, after its session is saved."""

    def run_calibration_core(self, cfg, trial_ctx, **kwargs):
        report = super().run_calibration_core(cfg, trial_ctx, **kwargs)
        if len(self.calls) == 1:
            raise CalibrationError("r_optim = 5.31 exceeds the bound 2")
        return report


def test_a_strict_violation_stops_a_staged_run_before_it_freezes(tmp_path, monkeypatch) -> None:
    fake = _StrictFirstPhase()
    fake.patch(monkeypatch)

    with pytest.raises(CalibrationError, match="r_optim"):
        run_staged_calibration(write_document(tmp_path, STAGED_HEAD + TWO_PHASES))

    # The dependent phase never ran, so nothing was calibrated on a K the
    # bound refused.
    assert fake.phases_run == ["steady_k"]


# From test_first_trial_pairing.py
# What the first trial paired against an observed record, once per phase.
#
# ``ObservableScorer.score`` (``metrics/observable_scoring.py``) writes
# ``<name>.n_paired`` and ``<name>.date_start`` / ``<name>.date_end`` into every
# trial's components. ``_first_trial_pairing`` reads them off the first entry of
# a phase's history rather than recomputed trial to trial: the pairing a search
# follows is set before the first candidate is scored and does not change
# after it.


def _paired(name: str, n: float, start: date | None = None, end: date | None = None) -> dict:
    components = {f"{name}.n_paired": n}
    if start:
        components |= {
            f"{name}.date_start": float(start.toordinal()),
            f"{name}.date_end": float(end.toordinal()),
        }
    return components


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        pytest.param(
            [_paired("q", 3.0, date(2001, 1, 2), date(2001, 1, 4)), _paired("q", 5.0)],
            {"q": {"n_paired": 3, "start": "2001-01-02", "end": "2001-01-04"}},
            id="reads_the_first_trial_not_a_later_one",
        ),
        pytest.param(
            [
                _paired("outlet", 2.0, date(2001, 1, 1), date(2001, 1, 2))
                | _paired("piezo", 4.0, date(2000, 6, 1), date(2000, 6, 4))
            ],
            {
                "outlet": {"n_paired": 2, "start": "2001-01-01", "end": "2001-01-02"},
                "piezo": {"n_paired": 4, "start": "2000-06-01", "end": "2000-06-04"},
            },
            id="one_entry_per_output",
        ),
        pytest.param([{"flow.raw_cost": 1.0}], None, id="none_without_a_paired_output"),
        pytest.param([], None, id="none_for_empty_history"),
        pytest.param([_paired("q", 7.0)], {"q": {"n_paired": 7}}, id="count_without_dates"),
    ],
)
def test_the_first_trial_pairing(history, expected) -> None:
    results = [
        result_of(ParamSuggestion(trial_id=index, values={}), 0.1, components=item)
        for index, item in enumerate(history)
    ]

    assert _first_trial_pairing(results) == expected


# ---------------------------------------------------------------------------
# End to end: a full run through run_calibration_cli reads the first trial,
# not a later one -- no solver, a custom evaluator stands in for the model.
# ---------------------------------------------------------------------------
class _FirstTrialProbe:
    """Reports a different pairing on every trial: the report must keep the first."""

    evaluator_id = "test_first_trial_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _FirstTrialProbe.calls += 1
        first = _FirstTrialProbe.calls == 1
        n = 3 if first else 30
        end = date(2001, 1, 3) if first else date(2001, 2, 1)
        return TrialOutcome(
            cost=float(request.values["K"]),
            status="completed",
            duration_s=0.0,
            components={
                "q.n_paired": float(n),
                "q.date_start": float(date(2001, 1, 1).toordinal()),
                "q.date_end": float(end.toordinal()),
            },
        )


@pytest.fixture
def first_trial_probe():
    _FirstTrialProbe.calls = 0
    evaluation_registry.evaluators.register(_FirstTrialProbe, replace=True)
    try:
        yield _FirstTrialProbe
    finally:
        evaluation_registry.evaluators.unregister(_FirstTrialProbe.evaluator_id)


PROBE_TOML = toml_doc(
    """
    [calibration]
    method = "grid"
    max_trials = 3
    evaluator = "test_first_trial_probe"
    use_cache = false
    method_options = { points_per_dim = 3 }
    @KLOG
    @NET
    @GAP
    """
)


def test_the_full_run_reports_the_first_trial_not_a_later_one(
    tmp_path: Path, first_trial_probe
) -> None:
    path = write_document(tmp_path, PROBE_TOML)

    report = run_calibration_cli(path, workspace=tmp_path)

    assert first_trial_probe.calls >= 2  # more than one trial ran
    pairing = report.extra["first_trial_pairing"]
    assert pairing == {"q": {"n_paired": 3, "start": "2001-01-01", "end": "2001-01-03"}}


# From test_persistence.py
# The journal of a session is written as the search goes, and read back whole.
#
# No index anywhere: ``CalibrationPersistence`` writes ``session.json``,
# ``outcome.json``, ``trials.jsonl`` and ``phases/<phase>/session.json`` under
# one session directory, and reads them back for the promotion and the report.


def _open(tmp_path: Path, name: str = "calage") -> CalibrationPersistence:
    windows = calibration_window(date(2001, 1, 1), date(2002, 12, 31))
    return make_session(tmp_path, name, site="nancon", windows=windows)


ROOTS = {
    "parameter": "K",
    "minimal": {"k_star": 3.0e-6, "low": 2.9e-6, "high": 3.1e-6, "weight": 0.5},
    "maximal": {"k_star": 2.0e-4, "low": 1.9e-4, "high": 2.1e-4, "weight": 0.5},
    "delta_log10": 1.82,
    "value": 2.4e-5,
    "combined_trial_id": 23,
    "closed": True,
}


class TestTheSessionOpensAndCloses:
    def test_the_opening_writes_a_running_descriptor_and_outcome(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        descriptor = read_session(persistence.directory)
        assert descriptor.status == "running"
        assert descriptor.case_id == "calage"
        assert descriptor.only_site == "nancon"
        assert descriptor.windows == calibration_window(date(2001, 1, 1), date(2002, 12, 31))
        outcome = read_outcome(persistence.directory)
        assert outcome is not None
        assert (outcome.status, outcome.case_id, outcome.project) == ("running", "calage", "demo")
        assert outcome.written_by == "worker"

    def test_the_closing_writes_the_status_the_best_and_the_outcome(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        journal_trial(persistence, 1, 0.4)
        journal_trial(persistence, 2, 0.1, k=2e-4)

        persistence.finalize_session(
            status="completed",
            best=persistence.best_pointer(persistence.best_trial()),
            root_search={"bracket": {"low": 1.0}},
        )

        descriptor = read_session(persistence.directory)
        assert descriptor.status == "completed"
        assert descriptor.ended_at is not None
        assert descriptor.best is not None
        assert (descriptor.best.trial, descriptor.best.cost) == (2, 0.1)
        assert descriptor.root_search == {"bracket": {"low": 1.0}}
        outcome = read_outcome(persistence.directory)
        assert outcome is not None and outcome.status == "completed"

    @pytest.mark.parametrize(("status", "error"), [("failed", "boom"), ("aborted", "SIGTERM")])
    def test_a_failed_or_aborted_closing_carries_its_error(self, tmp_path, status, error) -> None:
        persistence = _open(tmp_path)

        persistence.finalize_session(status=status, best=None, error=error)

        assert read_session(persistence.directory).error_message == error
        outcome = read_outcome(persistence.directory)
        assert outcome is not None
        assert outcome.status == status
        assert outcome.error is not None and outcome.error.message == error

    def test_a_reopened_session_runs_again_and_keeps_its_trials(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        journal_trial(persistence, 1, 0.4)
        persistence.finalize_session(status="partial", best=None, error="cut")

        reopened = CalibrationPersistence(persistence.directory)
        reopened.resume_session()

        descriptor = read_session(persistence.directory)
        assert (descriptor.status, descriptor.ended_at, descriptor.error_message) == (
            "running",
            None,
            None,
        )
        assert [line.trial for line in reopened.trials()] == [1]
        line = journal_trial(reopened, 1, 0.2, k=3e-4)
        assert line.trial == 2, "the numbering goes on from the highest trial journaled"


class TestTheRootSearchOutlivesTheRun:
    """A root search's bracket and two roots are kept in ``session.json``."""

    def test_the_descriptor_keeps_the_two_roots(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        persistence.finalize_session(status="completed", best=None, root_search={"roots": ROOTS})

        assert read_session(persistence.directory).root_search == {"roots": ROOTS}
        payload = json.loads((persistence.directory / "session.json").read_text())
        assert payload["root_search"]["roots"]["minimal"]["k_star"] == pytest.approx(3.0e-6)

    def test_any_other_search_keeps_no_root_search(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        persistence.finalize_session(status="completed", best=None)

        assert read_session(persistence.directory).root_search is None

    def test_the_close_of_a_search_hands_the_roots_of_its_report_to_the_descriptor(
        self, tmp_path
    ) -> None:
        persistence = _open(tmp_path)
        journal_trial(persistence, 1, 0.4)
        report = make_report(
            method="bisection",
            best_cost=0.4,
            duration_s=1.0,
            workspace=tmp_path,
            session_dir=persistence.directory,
            extra={"search_status": "completed", "bracket": {"low": 1.0}, "roots": ROOTS},
        )

        promote_and_close(
            cfg=CalibrationConfig(save_runs="none"),
            trial_ctx=None,
            persistence=persistence,
            project_root=tmp_path,
            report=report,
            phase="main",
            status="completed",
        )

        descriptor = read_session(persistence.directory)
        assert descriptor.status == "completed"
        assert descriptor.root_search == {"bracket": {"low": 1.0}, "roots": ROOTS}


class TestTheTrialNumbering:
    def test_the_number_is_unique_across_phases_and_restarts(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        steady = PhaseContext("steady_k", 0, 0)
        transient = PhaseContext("transient_sy", 1, 0)
        again = PhaseContext("transient_sy", 1, 1)

        numbers = [
            journal_trial(persistence, trial_id, cost, k=k, phase=phase).trial
            for trial_id, cost, k, phase in (
                (0, 0.4, 1e-4, steady),
                (1, 0.3, 2e-4, steady),
                (0, 0.2, 0.05, transient),
                (0, 0.1, 0.07, again),
            )
        ]

        assert numbers == [1, 2, 3, 4]
        trials = read_trials(persistence.directory)
        assert [(t.phase, t.restart) for t in trials] == [
            ("steady_k", 0),
            ("steady_k", 0),
            ("transient_sy", 0),
            ("transient_sy", 1),
        ]
        assert persistence.trial_number(0, transient) == 3
        assert persistence.trial_number(0, again) == 4

    def test_the_number_is_given_before_the_trial_runs_and_kept_at_its_line(self, tmp_path) -> None:
        """The sandbox and the kept solve of a trial carry the number of its journal line."""
        persistence = _open(tmp_path)
        steady = PhaseContext("steady_k", 0, 0)

        given = [persistence.assign_trial_number(engine_id, steady) for engine_id in (0, 1)]
        line = journal_trial(persistence, 1, 0.3, k=2e-4, phase=steady)

        assert given == [1, 2]
        assert line.trial == 2
        assert persistence.assign_trial_number(1, steady) == 2, "given once"
        assert persistence.trial_number(0, steady) == 1

    def test_an_engine_trial_written_twice_keeps_its_number(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        first = journal_trial(persistence, 3, 0.4)
        second = journal_trial(persistence, 3, 0.2)

        assert first.trial == second.trial == 1
        assert [line.cost for line in read_trials(persistence.directory)] == [0.2]

    def test_a_cached_result_is_a_completed_trial_from_the_cache(self, tmp_path) -> None:
        line = journal_trial(_open(tmp_path), 1, 0.4, status="cached", from_cache=True)

        assert (line.status, line.only_case.from_cache) == ("completed", True)

    @pytest.mark.parametrize(
        ("status", "error"),
        [("crashed", "mf6 stopped"), ("infeasible", "infeasible: head above the top")],
        ids=["a_failed_trial_keeps_no_cost_and_names_its_error", "an_infeasible_point_is_no_crash"],
    )
    def test_a_trial_without_a_cost_names_its_error(self, tmp_path, status, error) -> None:
        persistence = _open(tmp_path)
        line = journal_trial(persistence, 1, float("nan"), status=status, metadata={"error": error})

        assert line.status == status
        assert line.cost is None
        assert line.only_case.error == error
        assert persistence.best_trial() is None


class TestWhatIsReadBack:
    def test_top_n_and_the_best_trial_rank_by_cost(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        for trial_id, cost in ((1, 0.9), (2, 0.1), (3, 0.5), (4, float("nan"))):
            status = "completed" if cost == cost else "crashed"
            journal_trial(persistence, trial_id, cost, status=status)

        assert [row["trial"] for row in persistence.top_n(2)] == [2, 3]
        best = persistence.best_trial()
        assert best is not None and best.trial == 2
        rows = persistence.load_iterations()
        assert [row["trial"] for row in rows] == [1, 2, 3, 4]
        assert rows[0]["parameters"] == {"K": {"value": 1e-4}}
        assert rows[3]["cost"] is None
        assert set(rows[0]) == {
            "phase",
            "restart",
            "trial",
            "case_id",
            "cost",
            "case_cost",
            "components",
            "parameters",
            "status",
            "case_status",
            "from_cache",
            "params_hash",
            "sim_id",
            "rel_dir",
            "speculative_unused",
            "duration_s",
            "batch",
            "rule",
            "window",
            "solve_s",
            "reused",
        }
        assert (rows[0]["case_id"], rows[0]["case_cost"]) == ("calage", 0.9)

    def test_a_linked_trial_rewrites_its_line_with_the_run(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        journal_trial(persistence, 1, 0.4)

        linked = persistence.link_trial(1, sim_id="9a4f" * 8, rel_dir="runs/calage")

        run = linked.only_case
        assert (run.sim_id, run.rel_dir) == ("9a4f" * 8, "runs/calage")
        lines = trials_path(persistence.directory).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2, "the last line of a trial wins"
        assert json.loads(lines[-1])["cases"]["calage"]["rel_dir"] == "runs/calage"
        assert read_trials(persistence.directory)[0].only_case.rel_dir == "runs/calage"

    def test_the_detail_decides_what_a_line_carries(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        fields = {"components": {"rmse": 0.4}, "metadata": {"block_costs": {"head": 0.5}}}

        none, full, summary = (
            journal_trial(persistence, number, 0.4, detail=detail, **fields).only_case
            for number, detail in ((1, "none"), (2, "full"), (3, "summary"))
        )

        assert (none.components, none.detail) == ({}, {})
        assert full.components == {"rmse": 0.4}
        assert full.detail == {"block_costs": {"head": 0.5}}
        assert (summary.components, summary.detail) == ({"rmse": 0.4}, {})


class TestThePhases:
    def test_a_phase_opens_running_and_closes_with_its_best(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        context = PhaseContext("steady_k", 0, 0)
        persistence.start_phase(context, frozen={})
        journal_trial(persistence, 1, 0.4, phase=context)
        journal_trial(persistence, 2, 0.1, k=2e-4, phase=context)

        assert read_phase(persistence.directory, "steady_k").status == "running"
        persistence.finish_phase(
            "steady_k",
            status="completed",
            best=persistence.best_pointer(persistence.best_trial("steady_k")),
        )

        phase = read_phase(persistence.directory, "steady_k")
        assert phase.status == "completed"
        assert phase.best is not None and phase.best.trial == 2
        assert [item.name for item in persistence.phases()] == ["steady_k"]

    def test_a_restarted_phase_keeps_its_id_and_counts_the_restarts(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        frozen = {"K": FrozenValue(value=6e-6, mode="replace", from_phase="steady_k")}
        first = persistence.start_phase(PhaseContext("sy", 1, 0), frozen=frozen)
        journal_trial(persistence, 1, 0.4, k=0.1, phase=PhaseContext("sy", 1, 0))
        journal_trial(persistence, 1, 0.3, k=0.2, phase=PhaseContext("sy", 1, 1))
        again = persistence.start_phase(PhaseContext("sy", 1, 1), frozen=frozen)

        assert again.phase_id == first.phase_id
        assert again.frozen == frozen
        closed = persistence.finish_phase("sy", status="completed", best=None)
        assert closed.restarts == 1

    def test_the_best_of_a_phase_reads_that_phase_only(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        journal_trial(persistence, 1, 0.9, phase=PhaseContext("steady_k", 0, 0))
        journal_trial(persistence, 1, 0.1, k=0.05, phase=PhaseContext("transient_sy", 1, 0))

        best_steady = persistence.best_trial("steady_k")
        assert best_steady is not None and best_steady.trial == 1
        best_all = persistence.best_trial()
        assert best_all is not None and best_all.trial == 2

    def test_the_best_pointer_adds_the_frozen_values_to_the_run_of_each_case(
        self, tmp_path
    ) -> None:
        persistence = _open(tmp_path)
        context = PhaseContext("sy", 1, 0)
        frozen = {"K": FrozenValue(value=6e-6, mode="replace", from_phase="steady_k")}
        persistence.start_phase(context, frozen=frozen)
        persistence.append_iteration(
            ParamSuggestion(trial_id=1, values={"Sy": 0.1}),
            result_of(ParamSuggestion(trial_id=1, values={"Sy": 0.1}), 0.4),
            phase=context,
        )
        persistence.link_trial(1, sim_id="9a4f" * 8, rel_dir="runs/calage")

        pointer = persistence.best_pointer(persistence.best_trial("sy"))

        assert pointer is not None
        assert pointer.parameters == {"K": 6e-6, "Sy": 0.1}
        assert (pointer.trial, pointer.cost) == (1, 0.4)
        assert pointer.cases["calage"].sim_id == "9a4f" * 8
        assert persistence.best_pointer(None) is None

    def test_the_cache_context_of_a_phase_is_kept_with_the_case(self, tmp_path) -> None:
        persistence = _open(tmp_path)

        persistence.record_context("sy", {"model": "a" * 16})
        persistence.record_context("k", {"model": "b" * 16})

        assert persistence.recorded_context("sy") == {"model": "a" * 16}
        assert persistence.recorded_context("other") == {}
        assert set(read_session(persistence.directory).cases["calage"].context) == {"sy", "k"}


class TestTheFixesOfTheReview:
    def test_the_session_reads_the_cost_of_the_phase_its_best_comes_from(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        context = PhaseContext("steady_k", 0, 0)
        persistence.start_phase(
            context, frozen={}, cost_name="distance_gap", cost_label="distance gap"
        )
        journal_trial(persistence, 1, 295.0, phase=context)
        best = persistence.best_pointer(persistence.best_trial("steady_k"))

        persistence.finalize_session(status="aborted", best=best, error="SIGTERM")

        descriptor = read_session(persistence.directory)
        assert (descriptor.cost_name, descriptor.cost_label) == ("distance_gap", "distance gap")
        assert descriptor.cases[descriptor.case_id].cost_name == "distance_gap"

    def test_a_cut_last_line_is_dropped_before_the_next_append(self, tmp_path) -> None:
        persistence = _open(tmp_path)
        journal_trial(persistence, 1, 0.4)
        journal_trial(persistence, 2, 0.3, k=2e-4)
        journal = trials_path(persistence.directory)
        journal.write_bytes(journal.read_bytes()[:-30])
        persistence.finalize_session(status="aborted", best=None, error="cut")

        reopened = CalibrationPersistence(persistence.directory)
        reopened.resume_session()
        journal_trial(reopened, 2, 0.2, k=3e-4)

        assert [line.trial for line in read_trials(persistence.directory)] == [1, 2]

    def test_a_session_whose_case_is_not_among_its_cases_is_refused_untouched(
        self, tmp_path
    ) -> None:
        persistence = _open(tmp_path)
        persistence.finalize_session(status="completed", best=None)
        descriptor = read_session(persistence.directory)
        write_session(persistence.directory, descriptor.model_copy(update={"case_id": "joint"}))
        before = (persistence.directory / "session.json").read_bytes()

        with pytest.raises(CalibrationError, match="joint"):
            CalibrationPersistence(persistence.directory).resume_session()

        assert (persistence.directory / "session.json").read_bytes() == before


# From test_protocol_reaches_the_loaders.py
# Naming a protocol has to change the run, not just the file.
#
# The expansion is written on the whole document, so it has to happen where the
# document is read. Both routes read one: the project loader and the calibration
# CLI. A protocol that reached neither would validate, persist, and calibrate
# nothing at all.


_TOML__protocol_reaches = textwrap.dedent(
    """
    [workspace]
    name = "protocol_probe"

    [simulation.time]
    start_datetime = "2000-01-01"
    end_datetime = "2000-12-31"
    step_value = 1
    step_unit = "day"

    [calibration]
    protocol = "matching_hydrographic_network"

    [calibration.parameters.K]
    bounds = [1e-8, 1e-2]
    search_space = "log"
    units = "m/s"

    [calibration.parameters.Sy]
    bounds = [1e-4, 0.5]
    search_space = "log"
    units = "-"

    [calibration.outputs.seepage_network]
    support = "network"
    map.complete = "network.gpkg"

    [[data.hydrometry.sources]]
    station_ids = ["G1"]
    """
)


@pytest.fixture
def project__protocol_reaches(tmp_path: Path) -> Path:
    path = tmp_path / "protocol.toml"
    path.write_text(_TOML__protocol_reaches, encoding="utf-8")
    (tmp_path / "network.gpkg").write_bytes(b"")
    return path


def test_the_cli_loader_runs_the_protocol(project__protocol_reaches: Path) -> None:
    cfg, _raw = load_toml_calibration(project__protocol_reaches)

    assert cfg.phases is not None
    assert [phase.name for phase in cfg.phases] == [
        "steady_conductivity",
        "transient_storage",
    ]
    assert cfg.objective_blocks[0].metric == "distance_gap"


def test_the_loaded_config_still_says_which_protocol_it_ran(
    project__protocol_reaches: Path,
) -> None:
    cfg, _raw = load_toml_calibration(project__protocol_reaches)

    assert cfg.protocol is not None
    assert cfg.protocol.name == "matching_hydrographic_network"


def test_a_protocol_that_nothing_expanded_is_refused_rather_than_ignored() -> None:
    """Validating [calibration] alone cannot see the window the stages need."""
    with pytest.raises(ValueError, match="protocol"):
        CalibrationConfig.model_validate(
            {
                "protocol": "matching_hydrographic_network",
                "parameters": {"K": {"bounds": [1e-8, 1e-2], "search_space": "log"}},
            }
        )


def test_one_stage_of_a_protocol_is_an_ordinary_calibration(
    project__protocol_reaches: Path,
) -> None:
    """A phase no longer declares the method that wrote it, and must not be refused."""

    cfg, _raw = load_toml_calibration(project__protocol_reaches)
    assert cfg.phases is not None

    phase_config = _phase_config(cfg, cfg.phases[0])

    assert phase_config.protocol is None
    assert phase_config.phases is None
    assert list(phase_config.parameters) == ["K"]


def test_the_run_records_what_the_protocol_rests_on(project__protocol_reaches: Path) -> None:
    """A calibrated value that came out of a published method has to say so."""

    cfg, _raw = load_toml_calibration(project__protocol_reaches)
    assert cfg.protocol is not None

    protocol = get_protocol(cfg.protocol.name)
    record = protocol_record(cfg.protocol.name)

    assert record["name"] == protocol.name
    assert record["title"] == protocol.title
    assert record["references"][0].startswith("Abherve")
    assert "10.5194/hess-27-3221-2023" in record["references"][0]


def test_the_report_carries_the_protocol_it_followed() -> None:
    summary = make_report(protocol=protocol_record("matching_hydrographic_network")).to_dict()

    assert summary["protocol"]["name"] == "matching_hydrographic_network"
    assert summary["protocol"]["references"]


def test_a_hand_written_report_says_nothing_about_a_protocol() -> None:
    assert "protocol" not in make_report().to_dict()


# From test_runner_decomposition.py
# Smoke tests that lock the runner.py decomposition.
#
# The legacy ``hydromodpy.calibration.runner`` god-module has been split into:
#
# - ``cli_runner``     CLI entry; ``search`` holds ``run_calibration_core``.
# - ``programmatic_runner``  ``Project.calibrate`` entry.
# - ``promotion``    promotion of the kept trials to runs.
# - ``state``      cache preload, fingerprinting.
#
# These tests guarantee each sub-module imports independently and exposes the
# expected public callables. The legacy ``runner`` module must be gone so
# nothing keeps pointing at the old location.


@pytest.mark.parametrize(
    ("module", "names"),
    [
        ("runners.cli_runner", ["run_calibration_cli"]),
        ("runners.search", ["run_calibration_core"]),
        ("runners.programmatic_runner", ["run_calibration_programmatic"]),
        (
            "runners.promotion",
            [
                "promote_session",
                "select_trials_to_promote",
                "promote_trial_from_session",
                "prune_session",
                "stored_parameter_value",
            ],
        ),
        (
            "runners.state",
            [
                "preload_hash_cache",
                "build_cache_context",
                "override_paths",
                "space_from_config",
                "load_metric_fn_entry_point",
            ],
        ),
        ("persistence", ["CalibrationPersistence"]),
    ],
)
def test_a_module_exposes_its_public_callables(module: str, names: list[str]) -> None:
    loaded = importlib.import_module(f"hydromodpy.calibration.{module}")

    assert all(callable(getattr(loaded, name)) for name in names)


def test_legacy_runner_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydromodpy.calibration.runner")


# From test_stream_geometry_resolution.py
# Where a calibration output looks for its mapped stream network.
#
# A path in a TOML is relative to that TOML, the way ``base_config`` is, and a
# bare filename falls back to ``<project>/data/hydrography/`` like every other
# data path of a project. Read against the working directory instead, the run
# depended on where it was launched from and failed on a path that is right.
#
# The anchoring is done where the CLI, the staged and the programmatic routes
# converge, so a configuration built in memory gets it too. That is what the
# in-memory test below covers; the TOML-route test beside it guards the older
# anchoring in ``load_toml_calibration``, which is a different site.


_PROJECT_NETWORK = b"the network the project declares"
_DECOY_NETWORK = b"a file of the same name, in the way"

TOML = """\
[workflow]
mode = "calibration"

[calibration]
method = "bisection"

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
search_space = "log"

[calibration.outputs.net]
support = "network"
map.complete = "{declared}"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]
"""


@pytest.fixture
def project__stream_geometry(tmp_path: Path) -> Path:
    """A project holding its network where the convention puts it."""
    geometry = tmp_path / "data" / "hydrography" / "streams.gpkg"
    geometry.parent.mkdir(parents=True)
    geometry.write_bytes(_PROJECT_NETWORK)
    configs = tmp_path / "configs"
    configs.mkdir()
    return tmp_path


def _load(project__stream_geometry: Path, declared: str, *, at: str = "configs") -> str | None:
    path = project__stream_geometry / at / "calibration.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TOML.format(declared=declared), encoding="utf-8")
    cfg, _raw = load_toml_calibration(path)
    resolved = cfg.outputs["net"].map.complete
    return None if resolved is None else str(resolved)


def test_a_bare_filename_falls_back_to_the_data_family(project__stream_geometry: Path) -> None:
    resolved = _load(project__stream_geometry, "streams.gpkg")
    assert (
        Path(resolved)
        == (project__stream_geometry / "data" / "hydrography" / "streams.gpkg").resolve()
    )


def test_a_relative_path_is_read_from_the_toml_that_declares_it(
    project__stream_geometry: Path,
) -> None:
    resolved = _load(project__stream_geometry, "../data/hydrography/streams.gpkg")
    assert (
        Path(resolved)
        == (project__stream_geometry / "data" / "hydrography" / "streams.gpkg").resolve()
    )


def test_an_absolute_path_is_left_alone(project__stream_geometry: Path) -> None:
    declared = (project__stream_geometry / "data" / "hydrography" / "streams.gpkg").resolve()
    # The field is a Path: Windows spells it with backslashes, the same file.
    assert Path(_load(project__stream_geometry, declared.as_posix())) == declared


def test_a_path_that_resolves_to_nothing_is_left_as_declared(
    project__stream_geometry: Path,
) -> None:
    # Loading a configuration must not require its data: --list-phases has to
    # work on a machine holding none of it, and the criterion names the file it
    # could not read when it gets there.
    assert _load(project__stream_geometry, "nowstreams.gpkg") == "nowstreams.gpkg"


@pytest.fixture
def decoy(tmp_path: Path) -> Path:
    """A directory holding another file of the same name, and its sub-path."""
    trap = tmp_path / "elsewhere"
    (trap / "data" / "hydrography").mkdir(parents=True)
    (trap / "streams.gpkg").write_bytes(_DECOY_NETWORK)
    (trap / "data" / "hydrography" / "streams.gpkg").write_bytes(_DECOY_NETWORK)
    return trap


@pytest.mark.parametrize("declared", ["streams.gpkg", "../data/hydrography/streams.gpkg"])
def test_the_network_is_the_same_file_from_any_working_directory(
    project__stream_geometry: Path, decoy: Path, monkeypatch: pytest.MonkeyPatch, declared: str
) -> None:
    monkeypatch.chdir(decoy)
    from_decoy = _load(project__stream_geometry, declared)
    monkeypatch.chdir(project__stream_geometry)
    from_project = _load(project__stream_geometry, declared)

    assert from_decoy == from_project
    # Both copies exist under that name; only the project's holds these bytes.
    assert Path(from_decoy).read_bytes() == _PROJECT_NETWORK


NAMED_SOURCE_TOML = toml_doc(
    """
    [workflow]
    mode = "calibration"
    [calibration]
    method = "bisection"
    @KB
    [calibration.outputs.net]
    support = "network"
    map.complete = "data.hydrography"
    @GAP
    """
)


def test_an_output_naming_its_source_has_no_path_to_anchor(project__stream_geometry: Path) -> None:
    # An output resolved from data.hydrography names no file to anchor.
    path = project__stream_geometry / "configs" / "calibration.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NAMED_SOURCE_TOML, encoding="utf-8")
    cfg, _raw = load_toml_calibration(path)
    assert cfg.map_files() == []


class _Halt(Exception):
    """Raised by the store factory to stop the run once the anchoring is done."""


def _halt(*_args: object, **_kwargs: object) -> NoReturn:
    raise _Halt


def _in_memory_config(declared: str) -> CalibrationConfig:
    """The configuration ``Project.calibrate`` builds: no TOML behind it."""
    return CalibrationConfig.model_validate(
        {
            "method": "bisection",
            "parameters": {
                "K": {
                    "bounds": [1e-9, 1e-3],
                    "search_space": "log",
                    "path": "flow.param.K.field.value",
                }
            },
            "outputs": {"net": {"support": "network", "map": {"complete": declared}}},
            "objective_blocks": [
                {"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]}
            ],
        }
    )


def test_a_route_that_never_reads_a_toml_still_anchors_the_network(
    project__stream_geometry: Path, decoy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python and embedded modes build the config in memory and reach the runner
    # without going through the TOML loader. Anchoring only there left them
    # reading the working directory.

    cfg = _in_memory_config("streams.gpkg")
    monkeypatch.chdir(decoy)
    # The cache preload is the first thing the core touches after anchoring.
    monkeypatch.setattr(search, "preload_hash_cache", _halt)
    session_dir = project__stream_geometry / "sessions" / "calage"
    session_dir.mkdir(parents=True)

    with pytest.raises(_Halt):
        run_calibration_core(
            cfg,
            None,
            persistence=CalibrationPersistence(session_dir),
            space=space_from_config(cfg),
            project_root=project__stream_geometry,
            cfg_path=project__stream_geometry / "project.toml",
        )

    assert Path(cfg.outputs["net"].map.complete).read_bytes() == _PROJECT_NETWORK


# From test_the_minimal_map_and_the_extent_are_checked_before_the_run.py
# The minimal map and the extent table, checked before the first solve.
#
# The minimal map is a file the TOML names, anchored on that TOML like the
# maximal one, and refused by preflight when it is not there. An extent table
# reads the timesteps of a transient run; on a search that runs steady, the
# criterion would refuse it at the first trial, after the phases before it had
# spent their budget.


_MAPS = """
[calibration.outputs.net]
support = "network"
map.complete = "{maximal}"
map.permanent = "{minimal}"
map.calibrate_on = {calibrate_on}
{extent}
"""

_ONE_SEARCH = "{flow}" + toml_doc(
    """
        [calibration]
        method = "bisection"
        @KLOG
        @GAP
        """
)

_TWO_PHASES = toml_doc(
    """
    [calibration]
    method = "bisection"
    @KLOG
    @SY
    @GAP

    [[calibration.phases]]
    name = "k_network"
    method = "bisection"
    parameters = ["K"]
    regime = "REGIME"
    SINGLE_METRIC

    [[calibration.phases]]
    name = "sy_network"
    method = "grid"
    max_trials = 4
    parameters = ["Sy"]
    objective_blocks = ["gap"]
    depends_on = "k_network"
    """
)


def _maps(tmp_path: Path) -> tuple[Path, Path]:
    maximal = tmp_path / "data" / "hydrography" / "streams.gpkg"
    minimal = tmp_path / "data" / "hydrography" / "permanent.gpkg"
    maximal.parent.mkdir(parents=True, exist_ok=True)
    maximal.write_bytes(b"maximal")
    minimal.write_bytes(b"minimal")
    return maximal, minimal


def _outputs(maximal: str, minimal: str, *, extent: bool) -> str:
    table = "[calibration.outputs.net.model.extent]" if extent else ""
    role = "{ permanent = 0.5, complete = 0.5 }" if extent else '"permanent"'
    return _MAPS.format(maximal=maximal, minimal=minimal, calibrate_on=role, extent=table)


class TestTheMinimalMap:
    def test_a_minimal_map_that_is_not_there_is_named(self, tmp_path) -> None:
        maximal, _ = _maps(tmp_path)
        doc = _ONE_SEARCH.format(flow="") + _outputs(
            maximal.as_posix(), "nowhere_permanent.gpkg", extent=False
        )

        findings = preflight_of(tmp_path, doc)

        named = [item for item in findings if "nowhere_permanent.gpkg" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert named[0].path == "calibration.outputs.net"
        assert "map.permanent" in named[0].detail

    @pytest.mark.parametrize(
        "declared", ["permanent.gpkg", "data/hydrography/permanent.gpkg", "absolute"]
    )
    def test_a_minimal_map_that_is_there_is_no_finding(self, tmp_path, declared: str) -> None:
        maximal, minimal = _maps(tmp_path)
        written = minimal.as_posix() if declared == "absolute" else declared
        doc = _ONE_SEARCH.format(flow="") + _outputs(maximal.as_posix(), written, extent=False)

        assert preflight_of(tmp_path, doc) == []

    @pytest.mark.parametrize(
        ("declared", "resolved"),
        [
            ("../data/hydrography/permanent.gpkg", "data/hydrography/permanent.gpkg"),
            ("permanent.gpkg", "data/hydrography/permanent.gpkg"),
            ("nowstreams.gpkg", None),
        ],
        ids=["relative_to_the_toml", "bare_name_falls_back_to_the_data_family", "left_as_declared"],
    )
    def test_a_minimal_map_is_anchored_where_the_run_reads_it(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, declared, resolved
    ) -> None:
        _maps(tmp_path)
        (tmp_path / "configs").mkdir()
        doc = "[workflow]\nmode = 'calibration'\n" + _ONE_SEARCH.format(flow="")
        path = write_document(
            tmp_path / "configs", doc + _outputs("streams.gpkg", declared, extent=False)
        )
        # A working directory that holds nothing: the path must not depend on it.
        (tmp_path / "elsewhere").mkdir()
        monkeypatch.chdir(tmp_path / "elsewhere")

        cfg, _raw = load_toml_calibration(path)

        output = cfg.outputs["net"]
        expected = Path(declared) if resolved is None else (tmp_path / resolved).resolve()
        assert Path(output.map.permanent) == expected
        assert (
            Path(output.map.complete)
            == (tmp_path / "data" / "hydrography" / "streams.gpkg").resolve()
        )


class TestTheExtentTable:
    def _one_search(self, tmp_path: Path, *, regime: str | None, extent: bool) -> str:
        maximal, minimal = _maps(tmp_path)
        flow = f'[flow]\nflow_regime = "{regime}"\n' if regime else ""
        return _ONE_SEARCH.format(flow=flow) + _outputs(
            maximal.as_posix(), minimal.as_posix(), extent=extent
        )

    def _two_phases(
        self, tmp_path: Path, *, regime: str, single_metric: bool, extent: bool = True
    ) -> str:
        maximal, minimal = _maps(tmp_path)
        route = 'variable = "net"\nobjective = "distance_gap"' if single_metric else ""
        route = route or 'objective_blocks = ["gap"]'
        return _TWO_PHASES.replace("REGIME", regime).replace("SINGLE_METRIC", route) + _outputs(
            maximal.as_posix(), minimal.as_posix(), extent=extent
        )

    def test_a_steady_project_scoring_an_extent_is_refused(self, tmp_path) -> None:
        doc = self._one_search(tmp_path, regime="steady", extent=True)

        findings = preflight_of(tmp_path, doc)

        refused = [item for item in findings if "extent table" in item.detail]
        assert len(refused) == 1
        assert refused[0].severity == "error"
        assert refused[0].path == "calibration.outputs.net"
        assert "[flow] flow_regime" in refused[0].detail

    @pytest.mark.parametrize(("regime", "extent"), [("transient", True), ("steady", False)])
    def test_a_transient_extent_or_a_steady_state_is_no_finding(
        self, tmp_path, regime: str, extent: bool
    ) -> None:
        doc = self._one_search(tmp_path, regime=regime, extent=extent)

        assert preflight_of(tmp_path, doc) == []

    def test_the_default_regime_is_transient(self, tmp_path) -> None:
        doc = self._one_search(tmp_path, regime=None, extent=True)

        assert "extent table" not in messages(preflight_of(tmp_path, doc))

    @pytest.mark.parametrize("single_metric", [False, True])
    def test_a_steady_phase_scoring_an_extent_is_refused(
        self, tmp_path, single_metric: bool
    ) -> None:
        doc = self._two_phases(tmp_path, regime="steady", single_metric=single_metric)

        findings = preflight_of(tmp_path, doc)

        refused = [item for item in findings if "extent table" in item.detail]
        # Only the steady phase is named; the transient one reads the extent.
        assert len(refused) == 1
        assert refused[0].path == "calibration.outputs.net"
        assert "'k_network'" in refused[0].detail

    def test_a_steady_phase_through_its_overrides_is_refused(self, tmp_path) -> None:
        doc = self._two_phases(tmp_path, regime="transient", single_metric=False).replace(
            'regime = "transient"', 'overrides = { "flow.flow_regime" = "steady" }'
        )

        findings = preflight_of(tmp_path, doc)

        refused = [item for item in findings if "extent table" in item.detail]
        assert len(refused) == 1
        assert "'k_network'" in refused[0].detail

    def test_a_transient_phase_over_a_steady_project_is_no_finding(self, tmp_path) -> None:
        doc = '[flow]\nflow_regime = "steady"\n' + self._two_phases(
            tmp_path, regime="transient", single_metric=False
        )

        findings = preflight_of(tmp_path, doc)

        # The second phase names no regime and inherits the steady project.
        refused = [item for item in findings if "extent table" in item.detail]
        assert [item.detail for item in refused if "'k_network'" in item.detail] == []
        assert len(refused) == 1
        assert "'sy_network'" in refused[0].detail


_PERMANENT_SOURCE = 'map.permanent = "data.hydrography"\nmap.calibrate_on = "permanent"'


class TestTheMinimalObservedNetworkSource:
    """``map.permanent = "data.hydrography"`` is checked as statically as the
    maximal map: a project declaring it with no ``[[data.hydrography.sources]]``
    at all is refused at preflight, not at the first trial's
    ``resolve_minimal_network`` call.
    """

    _DOC = toml_doc(
        """
        [calibration]
        method = "grid"
        @K
        [calibration.outputs.net]
        support = "network"
        map.complete = "MAXIMAL"
        MINIMAL
        @GAP
        """
    )

    def _doc(self, tmp_path: Path, *, minimal: str) -> str:
        maximal = tmp_path / "streams.gpkg"
        maximal.write_bytes(b"maximal")
        return self._DOC.replace("MAXIMAL", maximal.as_posix()).replace("MINIMAL", minimal)

    def test_a_minimal_source_with_no_hydrography_section_is_named(self, tmp_path) -> None:
        doc = self._doc(tmp_path, minimal=_PERMANENT_SOURCE)

        findings = preflight_of(tmp_path, doc)

        named = [item for item in findings if "map.permanent" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert named[0].path == "calibration.outputs.net"
        assert "data.hydrography.sources" in named[0].detail

    def test_a_minimal_source_with_a_hydrography_section_is_no_finding(self, tmp_path) -> None:
        doc = (
            self._doc(tmp_path, minimal=_PERMANENT_SOURCE)
            + '\n[[data.hydrography.sources]]\nsource = "bdtopage"\n'
        )

        findings = preflight_of(tmp_path, doc)

        assert findings == []

    def test_no_minimal_source_declared_is_no_finding(self, tmp_path) -> None:
        doc = self._doc(tmp_path, minimal="")

        findings = preflight_of(tmp_path, doc)

        assert findings == []


# From test_the_prepared_model_is_checked_before_the_session.py
# What only the prepared model shows is checked once, right after the preparation.
#
# Three checks need the configuration the pipeline was prepared from: a bound
# the field refuses, and the drain and release-package conductances a network
# search relies on. They ran at the top of every search, so once per restart,
# after the session had been reserved: a refused search left a failed session
# behind. They now run once per preparation, before the session is reserved, on
# every route.


_FILE = (
    PROJECT_BASE
    + PROCESS
    + toml_doc(
        """
        [calibration]
        method = "bisection"
        max_trials = "auto"
        @KLOG
        @NET
        @GAP
        """
    )
)

_PHASE = """
[[calibration.phases]]
name = "k_only"
method = "bisection"
parameters = ["K"]
"""


@pytest.fixture
def prepared(monkeypatch) -> list[str]:
    """Prepare a model whose drains carry a fixed conductance, and record it."""

    flow = FlowConfig.model_validate({"bc": {"drainage": {"kind": "drain", "value": 1e-3}}})
    reached: list[str] = []

    def _prepare(cfg_path, **_kwargs):
        reached.append(Path(cfg_path).name)
        return SimpleNamespace(base_cfg=SimpleNamespace(flow=flow))

    for module in (search, staged_runner):
        monkeypatch.setattr(module, "prepare_trials", _prepare)
    return reached


@pytest.mark.parametrize(
    ("extra", "status", "note"),
    [
        ({}, "completed", None),
        (
            {"search_status": "partial", "root_outside_bounds": "K*_maximal"},
            "partial",
            "K*_maximal",
        ),
    ],
)
def test_a_single_search_hands_each_step_what_the_one_before_made(
    monkeypatch, tmp_path, extra, status, note
) -> None:
    """The sequence is read through strict fakes: each step gets exactly what it names."""
    cfg = SimpleNamespace(
        evaluator="model", phases=[], window=None, validation_scored_by=lambda phase: False
    )
    space, trial_ctx, session = object(), object(), object()
    searched, spread = make_report(extra=extra), ("spread",)
    widened = make_report(extra=extra, n_trials=7)
    calls: dict[str, dict] = {}

    def record(name, result=None):
        def call(*args, **kwargs):
            calls[name] = {"args": args, "kwargs": kwargs}
            return result

        monkeypatch.setattr(search, name, call)

    record("promotion_name_check")
    record("resolve_override_paths", {"p": "q"})
    record("prepare_trials", trial_ctx)
    record("check_the_prepared_model")
    record("open_calibration_session", (session, False))
    record("keep_trial_solves")
    record("run_one_search", (searched, spread))
    record("_with_linearized_width", widened)
    record("parameter_widths", {"K": "width"})
    record("promote_and_close", "closed")
    monkeypatch.setattr(search, "closing_session", lambda scope: nullcontext())
    monkeypatch.setattr(
        search.evaluation_registry,
        "needs_prepared_model",
        lambda evaluator: evaluator == "model",
    )
    path = tmp_path / "c.toml"

    result = search.run_single_search(
        cfg,
        space=space,
        cfg_path=path,
        case="c",
        raw={"r": 1},
        project_root=tmp_path,
        project="demo",
        metric_fn=None,
        objective="rmse",
        resume=True,
    )

    assert result == ("closed", spread)
    assert calls["prepare_trials"] == {
        "args": (path,),
        "kwargs": {"override_paths": {"p": "q"}, "parameter_space": space, "bounds": None},
    }
    assert calls["open_calibration_session"]["kwargs"] == {
        "resume": True,
        "raw": {"r": 1},
        "cfg": cfg,
        "space": space,
        "trial_ctx": trial_ctx,
        "project": "demo",
        "objective": "rmse",
    }
    assert calls["run_one_search"]["kwargs"]["objective"] == "rmse"
    assert calls["run_one_search"]["kwargs"]["phase"] == PhaseContext(DEFAULT_PHASE, 0, 0)
    assert calls["parameter_widths"]["args"] == (widened, spread)
    closing = calls["promote_and_close"]["kwargs"]
    assert (closing["status"], closing["stop_note"], closing["widths"]) == (
        status,
        note,
        {"K": "width"},
    )
    assert closing["report"] is widened


def test_the_answer_of_a_search_is_the_trial_it_names_else_the_best_of_the_journal(
    tmp_path,
) -> None:
    persistence = _open(tmp_path)
    journal_trial(persistence, 1, 0.5, k=1e-4, components={"q.n_paired": 3})
    journal_trial(persistence, 2, 0.1, k=2e-4, components={"q.n_paired": 9})
    answered = SimpleNamespace(best_trial=1)

    named, named_scored = session_scope.answered_best(persistence, answered, DEFAULT_PHASE)
    lowest, scored = session_scope.answered_best(persistence, make_report(), DEFAULT_PHASE)
    nothing, none_scored = session_scope.answered_best(
        _open(tmp_path, "empty"), make_report(), DEFAULT_PHASE
    )

    assert (named.trial, lowest.trial) == (1, 2)
    assert ([item.n for item in named_scored], [item.n for item in scored]) == ([3], [9])
    assert (nothing, none_scored) == (None, [])


def _write__prepared_model(tmp_path: Path, *extra: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text(_FILE + "".join(textwrap.dedent(item) for item in extra), encoding="utf-8")
    (tmp_path / "streams.gpkg").write_text("", encoding="utf-8")
    return path


def _sessions(tmp_path: Path) -> list[str]:
    root = tmp_path / "sessions"
    return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


def test_a_search_without_phases_is_refused_before_its_session(tmp_path, prepared) -> None:
    with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
        run_calibration_cli(_write__prepared_model(tmp_path))

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []


def test_a_phase_is_refused_before_the_session(tmp_path, prepared) -> None:
    with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
        run_staged_calibration(_write__prepared_model(tmp_path, _PHASE))

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []


def test_a_search_from_python_is_refused_before_its_session(tmp_path, prepared) -> None:
    path = _write__prepared_model(tmp_path)
    with Project(path, headless=True) as project:
        with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
            project.calibrate(
                parameters={"K": {"bounds": [1e-7, 1e-3]}},
                outputs={"net": {"support": "network", "map": {"complete": "streams.gpkg"}}},
                objective_blocks=[
                    {"name": "gap", "metric": "distance_gap", "uses_outputs": ["net"]}
                ],
            )

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []


# From test_the_report_says_what_it_calibrated.py
# Two things a calibration run knows and used to keep to itself.
#
# A stream-network stage that moves K identifies the ratio K/R, never K alone.
# The report publishes that ratio with the other derived values of the paper's
# Table 1, and only for that search: the criterion can drive any parameter.
#
# And a value that closed on a search bound is the best point of a search that
# was forbidden to look further, not a value the trials converged onto. That
# used to be an informational line, indistinguishable from an ordinary interval.


def _interval(*, reaches_lower: bool = False, reaches_upper: bool = False) -> ParameterInterval:
    return ParameterInterval(
        name="Sy",
        best=5.0e-3,
        lower=5.0e-3,
        upper=8.0e-3,
        margin=0.05,
        kind="relative",
        threshold=0.1,
        n_within=3,
        n_trials=20,
        reaches_lower_bound=reaches_lower,
        reaches_upper_bound=reaches_upper,
    )


def _space(*, path: str = "flow.param.K.field.value", mode: str = "replace", units=None):
    return ParameterSpace(
        [CalibParameter(name="K", lower=1e-7, upper=1e-3, path=path, mode=mode, units=units)]
    )


R_MEAN = {"network.R_mean_m_s": 2.0e-8}


def _ratios(components=None, **overrides):
    """The K/R extra of a search on K = 5e-4 with one network output, *overrides* set over it."""
    arguments = {
        "network_outputs": ("network",),
        "components": R_MEAN if components is None else components,
        "best_parameters": {"K": 5.0e-4},
        "space": _space(),
        "trial_ctx": None,
    }
    return network_ratios_extra(**(arguments | overrides))


class TestTheRechargeBesideK:
    def test_the_line_of_k_gives_the_window_of_its_recharge(self) -> None:
        time = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31T00:00:00")
        trial_ctx = SimpleNamespace(base_cfg=SimpleNamespace(simulation=SimpleNamespace(time=time)))

        extra = _ratios(trial_ctx=trial_ctx)

        assert "m/s over 2000-01-01 to 2002-12-31 on output" in extra["k_over_r_note"]
        assert extra["r_mean_window"] == {"start": "2000-01-01", "end": "2002-12-31"}

    def test_a_run_with_no_dates_says_none(self) -> None:
        extra = _ratios()

        assert " over " not in extra["k_over_r_note"]
        assert "r_mean_window" not in extra


class TestPaperRatios:
    def test_every_ratio_of_table_1_for_a_conductivity_search(self) -> None:
        extra = _ratios({**R_MEAN, "network.d_sat_m": 12.0, "network.d_sat_over_d": 0.4})

        k_over_r = 5.0e-4 / 2.0e-8
        assert extra["k_over_r"] == k_over_r
        assert extra["k_optim_m_s"] == 5.0e-4
        assert extra["d_sat_m"] == 12.0
        assert extra["t_over_r_m"] == k_over_r * 12.0
        assert extra["t_optim_m2_s"] == 5.0e-4 * 12.0
        assert extra["d_sat_over_d"] == 0.4
        assert "t_over_r" in extra["k_over_r_note"]
        assert "full" not in extra["k_over_r_note"]

    def test_reads_the_recharge_under_the_output_name(self) -> None:
        # The trial publishes every network diagnostic as <output>.<key>. The
        # bare key is what the report used to read, and it found nothing.
        assert _ratios({"R_mean_m_s": 2.0e-8}) == {}
        assert _ratios()["k_over_r"] == 5.0e-4 / 2.0e-8

    def test_without_a_saturated_thickness_only_k_over_r(self) -> None:
        assert set(_ratios()) == {"k_over_r", "k_optim_m_s", "k_over_r_note"}

    def test_a_nearly_full_aquifer_is_said(self) -> None:
        extra = _ratios({**R_MEAN, "network.d_sat_m": 27.0, "network.d_sat_over_d": 0.9})

        assert "90% full" in extra["k_over_r_note"]

    def test_the_conductivity_is_read_in_its_declared_unit(self) -> None:
        extra = _ratios(space=_space(units="m/d"))

        assert extra["k_optim_m_s"] == pytest.approx(5.0e-4 / 86400.0)

    def test_the_field_unit_is_the_one_the_model_reads(self) -> None:
        field = SimpleNamespace(unit="m/d")
        param = {"K": SimpleNamespace(field=field)}
        trial_ctx = SimpleNamespace(base_cfg=SimpleNamespace(flow=SimpleNamespace(param=param)))

        extra = _ratios(space=_space(units="m/s"), trial_ctx=trial_ctx)

        assert extra["k_optim_m_s"] == pytest.approx(5.0e-4 / 86400.0)

    def test_the_note_names_the_output_it_read(self) -> None:
        extra = _ratios(
            {"a_net.R_mean_m_s": 2.0e-8, "b_net.R_mean_m_s": 9.0e-8},
            network_outputs=("b_net", "a_net"),
        )

        assert extra["k_over_r"] == 5.0e-4 / 2.0e-8
        assert "'a_net'" in extra["k_over_r_note"]

    def test_a_dry_catchment_is_a_value_not_a_gap(self) -> None:
        extra = _ratios({**R_MEAN, "network.d_sat_m": 0.0})

        assert extra["d_sat_m"] == 0.0
        assert extra["t_optim_m2_s"] == 0.0

    def test_a_unit_that_is_not_a_conductivity_warns_after_the_run(self, caplog) -> None:
        # The session is already saved when the report is assembled, so a
        # wrong unit costs the ratios and never the run.
        with caplog.at_level(logging.WARNING):
            extra = _ratios(space=_space(units="-"))

        assert extra == {}
        assert "No K/R in the report" in caplog.text

    @pytest.mark.parametrize(
        "overrides",
        [
            # The criterion drives any parameter. A thickness divided by R is not K/R.
            {"space": _space(path="domain.depth_model.thickness")},
            {"space": _space(mode="scale")},
            {"network_outputs": ()},
            {"components": {"network.alpha_obs_closure": 0.9}},
            {"best_parameters": None},
            {"best_parameters": {"K": 5.0e-4, "Sy": 0.1}},
        ],
        ids=[
            "another_parameter",
            "a_multiplier",
            "no_network_output",
            "no_r_mean",
            "no_best_parameters",
            "more_than_one_parameter",
        ],
    )
    def test_the_ratios_are_absent(self, overrides) -> None:
        assert _ratios(**overrides) == {}


class TestBoundWarning:
    def test_warns_on_a_bound(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            log_parameter_interval(
                _interval(reaches_lower=True),
                result_of(ParamSuggestion(trial_id=0, values={}), 0.42),
            )

        assert caplog.records
        assert caplog.records[0].levelno == logging.WARNING
        assert "lower search bound" in caplog.text
        assert "0.42" in caplog.text

    def test_a_value_inside_its_bounds_is_not_said_to_have_reached_one(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            log_parameter_interval(
                _interval(reaches_upper=True),
                result_of(ParamSuggestion(trial_id=0, values={}), 0.123),
            )

        assert "Sy = 0.005: the trials within 0.1 of the best run to the upper" in caplog.text
        assert "reached" not in caplog.text

    def test_stays_informational_inside_the_interval(self, caplog) -> None:
        with caplog.at_level(logging.INFO):
            log_parameter_interval(
                _interval(), result_of(ParamSuggestion(trial_id=0, values={}), 0.123)
            )

        assert caplog.records
        assert caplog.records[0].levelno == logging.INFO
        assert "search bound" not in caplog.text


# From test_the_uncertainty_is_declared.py
# How wide the answer is, said in the file rather than hardcoded.
#
# The interval reported beside a calibrated value was five per cent of the best
# cost, always. That is a fine default for an efficiency score and meaningless for
# a criterion solved at zero: five per cent of zero is zero, so a stream-network
# calibration got no interval at all and nothing said which line would give it
# one.
#
# The block declares it. The calibrated value never moves; only what is reported
# beside it does.


_SPACE = ParameterSpace.from_toml_mapping(
    {"K": {"bounds": [1.0, 5.0], "path": "flow.param.K.field.value"}}
)


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, object]]:
    return [{"parameters": {"K": value}, "cost": cost} for value, cost in pairs]


_SHARP = _trace([(1.0, 10.0), (2.0, 1.0), (3.0, 1.02), (4.0, 9.0), (5.0, 30.0)])
_AT_ZERO = _trace([(1.0, 40.0), (2.0, 0.0), (3.0, 12.0), (4.0, 30.0)])


class TestTheDeclaration:
    def test_the_default_is_five_per_cent_of_the_best(self) -> None:
        cfg = CalibrationConfig()
        decl = cfg.uncertainty

        # Unwritten stays unwritten: the width follows what the search scores,
        # and a search scored on an efficiency takes five per cent of its best.
        assert decl.method == "cost_profile"
        assert decl.cost_margin is None
        width = cfg.interval_width_for()
        assert (width.margin, width.kind, width.source) == (0.05, "relative", "default")

    def test_a_file_may_state_a_width_in_metres(self) -> None:
        cfg = make_config(objective="distance_gap", uncertainty={"cost_margin": "25 m"})

        assert cfg.uncertainty.cost_margin == "25 m"
        assert cfg.interval_width_for().margin == 25.0

    @pytest.mark.parametrize(
        "uncertainty",
        [{"cost_margin": "-1%"}, {"method": "bootstrap"}],
        ids=["a_negative_width", "a_method_that_does_not_exist"],
    )
    def test_a_declaration_that_cannot_be_read_is_refused(self, uncertainty) -> None:
        with pytest.raises(ValueError):
            make_config(uncertainty=uncertainty)


class TestWhatTheRunReports:
    def test_the_declared_width_is_the_one_used(self) -> None:
        decl = make_config(uncertainty={"cost_margin": "0.1%"}).interval_width_for()

        (interval,) = margin_intervals_or_none(_SHARP, ["K"], _SPACE, decl)

        assert interval.margin == pytest.approx(0.001)
        assert interval.lower == interval.upper == 2.0

    def test_an_absolute_width_reaches_a_criterion_solved_at_zero(self) -> None:
        cfg = make_config(objective="distance_gap", uncertainty={"cost_margin": "15 m"})

        (interval,) = margin_intervals_or_none(_AT_ZERO, ["K"], _SPACE, cfg.interval_width_for())

        assert interval.kind == "absolute"
        assert interval.lower == 2.0
        assert interval.upper == 3.0

    def test_a_relative_width_on_a_zero_cost_reports_nothing_and_says_why(self, caplog) -> None:
        decl = CalibrationConfig().interval_width_for()

        with caplog.at_level("WARNING"):
            assert margin_intervals_or_none(_AT_ZERO, ["K"], _SPACE, decl) == []

        assert "'25 m'" in caplog.text


# From test_validity_length_is_declared_in_metres.py
# ``verdict.validity_length`` on a network output: "auto" or a positive length.
#
# ``roptim_max`` is gone from the schema: a file that still carries it loads
# through the config migration, never through the model.


def test_auto_is_the_default() -> None:
    assert _network().verdict.validity_length == "auto"


@pytest.mark.parametrize(("declared", "metres"), [("150 m", 150.0), ("0.3 km", 300.0), (75, 75.0)])
def test_a_length_is_read_in_metres(declared: object, metres: float) -> None:
    output = _network(verdict={"validity_length": declared})

    assert float(output.verdict.validity_length.to("m").magnitude) == pytest.approx(metres)
    assert output.model_dump()["verdict"]["validity_length"] == pytest.approx(metres)


@pytest.mark.parametrize("declared", ["0 m", "-10 m", "2 s", "two cells"])
def test_a_length_that_is_not_one_is_refused(declared: str) -> None:
    with pytest.raises(ValidationError):
        _network(verdict={"validity_length": declared})


def test_the_ratio_bound_is_no_longer_a_field() -> None:
    with pytest.raises(ValidationError, match="roptim_max"):
        _network(roptim_max=2.0)


def test_a_declared_length_reaches_the_scoring_options() -> None:
    assert _scoring_options(_network())["validity_length_m"] is None
    assert (
        _scoring_options(_network(verdict={"validity_length": "300 m"}))["validity_length_m"]
        == 300.0
    )


_CALIBRATION = toml_doc(
    """
    [calibration]
    method = "bisection"
    @KLOG
    @GAP
    [calibration.outputs.net]
    support = "network"
    map.complete = "streams.gpkg"
    roptim_max = VALUE
    """
)


def _calibration_file(tmp_path, value: str):
    path = tmp_path / "calibration.toml"
    path.write_text(_CALIBRATION.replace("VALUE", value), encoding="utf-8")
    return path


@pytest.mark.parametrize("ratio", ["2", "3"])
def test_the_calibration_loader_refuses_a_ratio_by_name_and_leaves_the_file(
    tmp_path, ratio
) -> None:
    """``hmp calibrate`` names the key, points to the doctor of a 2.0.x release, edits nothing."""

    path = _calibration_file(tmp_path, ratio)
    before = path.read_bytes()

    with pytest.raises(ConfigError, match=r"holds calibration\.outputs\.net\.roptim_max") as raised:
        load_toml_calibration(path)

    assert path.name in str(raised.value)
    assert "hmp doctor --fix-config" in str(raised.value)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("delta", "warned"),
    [
        (None, False),
        (0.4, False),
        (0.5, False),
        (0.51, True),
        (1.82, True),
        (-1.276, True),
        (-0.4, False),
    ],
)
def test_two_roots_more_than_half_a_decade_apart_are_warned_about(delta, warned, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        search_record._log_the_two_roots({**ROOTS, "delta_log10": delta})

    assert ("satisfies neither map" in caplog.text) is warned


def test_the_two_roots_line_names_the_parameter_and_the_values(caplog) -> None:
    with caplog.at_level(logging.INFO):
        search_record._log_the_two_roots(ROOTS)
    assert "returned K = 2.4e-05" in caplog.text
    assert "Delta = 1.82 decade(s)" in caplog.text
    assert "weighted 0.5 / 0.5" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.INFO):
        search_record._log_the_two_roots({**ROOTS, "delta_log10": None, "value": None})
    assert "Delta = unknown" in caplog.text and "returned K = not solved" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        search_record._log_the_two_roots({**ROOTS, "delta_log10": -1.82})
    assert "lie 1.82 decades apart" in caplog.text


def test_a_bound_reached_without_a_best_result_logs_a_nan_cost(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        log_parameter_interval(_interval(reaches_lower=True), None)
    assert "Sy = 0.005 reached the lower search bound, at a cost of nan" in caplog.text


def test_an_interval_log_names_its_parameter(caplog) -> None:
    with caplog.at_level(logging.INFO):
        log_parameter_interval(_interval(), None)
    assert "Sy = 0.005, and 3 of 20 trials" in caplog.text
    caplog.clear()
    degenerate = dataclasses.replace(_interval(), n_within=1)
    with caplog.at_level(logging.INFO):
        log_parameter_interval(degenerate, None)
    assert "Sy = 0.005: " in caplog.text


def test_a_width_keeps_the_pairs_it_belongs_to_and_the_restarts_it_spans() -> None:
    report = SimpleNamespace(
        best_parameters={"K": 1e-5, "Sy": 0.1, "R": 0.3},
        parameter_uncertainty=[SimpleNamespace(parameter="K", sigma=2e-6)],
        extra={"parameter_correlations": [("K", "Sy", 0.9), ("Sy", "R", -0.4)]},
    )
    spread = [
        RestartSpread(parameter="Sy", best=0.1, lowest=0.08, highest=0.12, values=(0.08, 0.12))
    ]

    assert parameter_widths(report, spread) == {
        "K": ParameterWidth(sigma=2e-6, correlated={"Sy": 0.9}),
        "Sy": ParameterWidth(
            restarts=RestartRange(lowest=0.08, highest=0.12, values=[0.08, 0.12]),
            correlated={"K": 0.9, "R": -0.4},
        ),
        "R": ParameterWidth(correlated={"Sy": -0.4}),
    }


def _width(margin, kind="absolute", on_distances=False) -> IntervalWidth:
    return IntervalWidth(margin=margin, kind=kind, source="section", on_distances=on_distances)


@pytest.mark.parametrize(
    ("width", "trace", "message"),
    [
        (_width(None), _SHARP, "no trial measured the mesh"),
        (_width(0.05, "relative", on_distances=True), _SHARP, "a fraction has no meaning"),
        (_width(-1.0), _SHARP, "margin must not be negative"),
    ],
)
def test_a_width_that_cannot_be_read_gives_no_interval_and_says_why(
    width, trace, message, caplog
) -> None:
    with caplog.at_level("WARNING"):
        assert margin_intervals_or_none(trace, ["K"], _SPACE, width) == []

    assert message in caplog.text


@pytest.mark.parametrize(("root", "expected"), [(None, []), ("interval", ["interval"])])
def test_a_root_search_reads_its_interval_on_its_own_curve(root, expected) -> None:
    search = Mock(spec=BisectionAdapter)
    search.root_interval.return_value = root

    found = margin_intervals_or_none(_SHARP, ["K"], _SPACE, _width(25.0), search)

    assert found == expected
    search.root_interval.assert_called_once_with(margin=25.0, kind="absolute")


def test_the_mesh_cell_is_the_first_finite_one_a_trial_measured() -> None:
    def trial(components):
        return EvaluationResult(trial_id=1, sim_id=None, cost=1.0, components=components)

    results = [
        None,
        trial({"q.cost": 1.0}),
        trial({"net.cell_spacing_m": float("nan")}),
        trial({"net.cell_spacing_m": 30.0}),
        trial({"net.cell_spacing_m": 50.0}),
    ]
    measured = search_record.width_read_off_the_trials(_width(None), results[3], results)

    assert search_record._cell_measured_by_the_criterion(results[:3]) is None
    assert search_record._cell_measured_by_the_criterion(results) == 30.0
    assert measured.margin == 30.0


@pytest.mark.parametrize(
    ("found", "reads"),
    [
        ({"q.r_optim": 1.0}, [("q", "")]),
        ({"q.n_bounds_scored": 1.0}, []),
        (
            {
                "q.n_bounds_scored": 2.0,
                "q.r_optim_minimal": 1.0,
                "q.r_optim_maximal": 1.0,
                "q.weight_maximal": 0.0,
            },
            [("q_minimal", "_minimal")],
        ),
    ],
)
def test_the_r_optim_an_output_reads_follows_its_bounds(found, reads) -> None:
    assert search_record._r_optim_reads("q", found) == reads


def _line_capture(observed):
    """Return a capture whose simulation is ``K + j * Sy`` at the j-th observation."""

    def capture(*args, **kwargs):
        captured: dict = {}

        def metric_fn(trial_ctx, *, objective=None, variable=None):
            lever = np.arange(len(observed))
            captured["simulated"] = trial_ctx["K"] + lever * trial_ctx["Sy"]
            captured["observed"] = np.array(observed)
            return 0.0, {}

        return metric_fn, captured

    return capture


class _InProcessPool:
    """A pool whose workers are this process, so the patched trial runner is the one they use."""

    def __init__(self, evaluator_class, options, *, width):
        self.evaluator = evaluator_class(**options)
        self.trial_series_sink = self.evaluator.trial_series_sink
        self.evaluate = self.evaluator.evaluate
        self.closed = False

    def close(self):
        self.closed = True


def _attach(report, parallel=1, observed=(2.1, 2.4, 2.9)):
    return attach_a_linearized_width(
        report,
        cfg=SimpleNamespace(**{**vars(CFG), "parallel": parallel}),
        trial_ctx=bare_trial_ctx(),
        space=SimpleNamespace(names=("K", "Sy")),
        perturbation=0.01,
    )


@pytest.mark.parametrize("parallel", [1, 3])
def test_the_width_of_a_line_fit_is_its_first_order_covariance(monkeypatch, parallel) -> None:
    monkeypatch.setattr(composite, "build_paired_vector_capture", _line_capture((2.1, 2.4, 2.9)))
    monkeypatch.setattr(
        trial, "run_trial_light", _runs(lambda values: False, scores_before_failing=False)
    )
    monkeypatch.setattr(search, "TrialWorkerPool", _InProcessPool)
    report = SimpleNamespace(best_parameters=dict(ANSWER), parameter_uncertainty=None)
    with patch.object(
        search, "replace", lambda item, **kw: SimpleNamespace(**{**vars(item), **kw})
    ):
        widths = _attach(report, parallel).parameter_uncertainty

    # J = [[1, 0], [1, 1], [1, 2]], residuals (-0.1, 0.1, 0.1): s2 = 0.03, (J'J)^-1 = [[5, -3], [-3, 3]] / 6.
    assert [item.parameter for item in widths] == ["K", "Sy"]
    assert [item.sigma for item in widths] == pytest.approx(
        [math.sqrt(0.025), math.sqrt(0.015)], rel=1e-4
    )
    assert widths[0].correlations["Sy"] == pytest.approx(-3 / math.sqrt(15), rel=1e-4)


@pytest.mark.parametrize(
    ("observed", "answer", "message"),
    [
        ((2.1, 2.4), ANSWER, "degree(s) of freedom|leave 0"),
        ((2.1, 2.4, 2.9), {}, "No candidate was scored"),
    ],
)
def test_a_fit_without_freedom_or_without_an_answer_keeps_the_report(
    monkeypatch, caplog, observed, answer, message
) -> None:
    monkeypatch.setattr(composite, "build_paired_vector_capture", _line_capture(observed))
    monkeypatch.setattr(
        trial, "run_trial_light", _runs(lambda values: False, scores_before_failing=False)
    )
    report = SimpleNamespace(best_parameters=dict(answer), parameter_uncertainty=None)

    with caplog.at_level(logging.WARNING):
        assert _attach(report) is report

    assert __import__("re").search(message, caplog.text)


def test_a_document_that_cannot_carry_a_width_keeps_the_report(monkeypatch, caplog) -> None:
    def refuse(**options):
        raise search.UncertaintyNotAvailableError("the outputs name no station")

    monkeypatch.setattr(search, "_DerivativeEvaluator", refuse)
    report = SimpleNamespace(best_parameters=dict(ANSWER), parameter_uncertainty=None)

    with caplog.at_level(logging.WARNING):
        assert _attach(report) is report

    assert "No width is reported: the outputs name no station" in caplog.text


@pytest.mark.parametrize(
    ("raw", "window"),
    [(None, None), ({"metrics": "x"}, None), ({"metrics": {"window": "w"}}, "w")],
)
def test_the_metrics_window_is_read_off_the_document(raw, window) -> None:
    assert document.metrics_window_of(raw) == window


def test_a_search_that_scored_nothing_has_failed() -> None:
    assert session_scope.search_status(SimpleNamespace(history=[])) == "failed"


def _bisection(**records) -> Mock:
    search = Mock(spec=BisectionAdapter)
    search.roots = records.pop("roots", 1)
    search.bracket_record.return_value = records.get("bracket")
    search.roots_record.return_value = records.get("roots_record")
    search.root_outside_bounds.return_value = records.get("outside")
    return search


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        ({}, None),
        ({"bracket": {"low": 1}}, {"bracket": {"low": 1}}),
        (
            {"roots_record": {"value": 2}, "outside": "K*_maximal"},
            {"roots": {"value": 2}, "root_outside_bounds": "K*_maximal"},
        ),
    ],
)
def test_a_root_search_records_what_it_proved(records, expected) -> None:
    session = SimpleNamespace(optimizer=_bisection(**records))

    assert session_scope.root_search_record(session) == expected
    assert session_scope.root_search_record(SimpleNamespace(optimizer=object())) is None


def test_a_search_that_closed_two_roots_says_it_reports_no_interval(caplog) -> None:
    two, one = (
        SimpleNamespace(optimizer=_bisection(roots=2)),
        SimpleNamespace(optimizer=_bisection()),
    )

    with caplog.at_level("INFO"):
        assert (search_record.closes_two_roots(one), search_record.closes_two_roots(two)) == (
            False,
            True,
        )

    assert caplog.text.count("No interval of trials is reported") == 1


def test_the_search_outcome_logs_the_two_roots_it_closed(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(search_record, "_log_the_two_roots", seen.append)
    session = SimpleNamespace(
        optimizer=_bisection(roots_record={"delta_log10": 0.1}),
        stop_state="rule_met",
        converged=True,
        stopping_rule="tol",
        max_trials=9,
        extension=0,
        history=[],
    )

    extra = search_record.search_outcome_extra(session)

    assert extra["roots"] == {"delta_log10": 0.1}
    assert seen == [{"delta_log10": 0.1}]


def test_the_scratch_of_a_session_is_kept_on_demand_and_a_failed_cleanup_is_only_logged(
    monkeypatch, caplog
) -> None:
    from hydromodpy.catchment.preprocess import preprocessing_cleanup

    calls = []

    def cleanup(geographic, *, keep):
        calls.append((geographic, keep))
        if len(calls) == 2:
            raise OSError("busy")

    monkeypatch.setattr(preprocessing_cleanup, "cleanup_stable_folder", cleanup)
    monkeypatch.setattr(session_scope, "keep_trial_scratch", lambda: False)

    def trial_ctx(write):
        setup = SimpleNamespace(geographic="geo")
        cfg = SimpleNamespace(geographic=SimpleNamespace(write_intermediates=write))
        return SimpleNamespace(ctx=SimpleNamespace(setup=setup), base_cfg=cfg)

    session_scope.release_session_scratch(trial_ctx(True))
    with caplog.at_level("WARNING"):
        session_scope.release_session_scratch(trial_ctx(False))

    assert calls == [("geo", True), ("geo", False)]
    assert "Could not remove the calibration session scratch" in caplog.text


def test_a_phase_whose_trials_carry_no_block_cost_has_no_fractions() -> None:
    blocks = [SimpleNamespace(name="a", weight=1.0), SimpleNamespace(name="b", weight=1.0)]
    cfg = SimpleNamespace(objective_blocks=blocks)
    done = EvaluationResult(trial_id=1, sim_id=None, cost=1.0, components={})

    assert search.phase_cost_block_fractions(cfg, [done], done) is None


def test_a_default_the_project_refuses_is_reported_with_the_file(monkeypatch, tmp_path) -> None:
    def refuse(table, **kwargs):
        raise ConfigError("the gauge is unknown")

    monkeypatch.setattr("hydromodpy.calibration.config.apply_project_defaults", refuse)
    path = tmp_path / "calib.toml"

    with pytest.raises(ConfigError, match=f"^{path}: the gauge is unknown"):
        document._with_project_defaults({"calibration": {}}, path)


def test_a_name_the_project_does_not_carry_stops_the_load_and_any_other_failure_does_not(
    monkeypatch, tmp_path
) -> None:
    from hydromodpy.calibration.parameter_resolution import UnresolvedParameterName

    cfg = SimpleNamespace(parameters={"K": object()})
    document._resolve_parameter_names(SimpleNamespace(parameters={}), tmp_path)
    monkeypatch.setattr(trial, "_PIPELINE", FakePipeline(config_error=OSError("no data")))
    document._resolve_parameter_names(cfg, tmp_path)
    monkeypatch.setattr(
        trial,
        "_PIPELINE",
        FakePipeline(config_error=UnresolvedParameterName("no such name")),
    )

    with pytest.raises(UnresolvedParameterName, match="no such name"):
        document._resolve_parameter_names(cfg, tmp_path)


def test_a_bare_input_name_stops_the_load(monkeypatch, tmp_path) -> None:
    """A path 2.1.0 refuses is named, not left to fail later on a missing 'path'."""
    from hydromodpy.core.toml_io.paths import BareInputNameError

    cfg = SimpleNamespace(parameters={"K": object()})
    monkeypatch.setattr(
        trial,
        "_PIPELINE",
        FakePipeline(config_error=BareInputNameError("inputs 'piezometry' is a bare name")),
    )

    with pytest.raises(BareInputNameError, match="'piezometry' is a bare name"):
        document._resolve_parameter_names(cfg, tmp_path)
