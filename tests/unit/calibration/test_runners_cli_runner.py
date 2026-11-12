"""Calibration runners from the command line down to the session on disk.

A calibration file is read, searched trial by trial with a stand-in or closed-form
evaluator, and its session (journal, phases, outcome) is closed with a status.
Costs are unitless, K is in m/s, windows are calendar dates.
"""

from __future__ import annotations

import argparse
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
from datetime import date
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
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.metrics import composite
from hydromodpy.calibration.optim import engine as engine_mod
from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.cache import ParamsHashCache, params_hash
from hydromodpy.calibration.optim.cost_margin import IntervalWidth, ParameterInterval
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import DEFAULT_PHASE, CalibrationPersistence, PhaseContext
from hydromodpy.calibration.preflight_report import comparison_lines
from hydromodpy.calibration.protocols.registry import protocol_record
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import (
    cli_runner,
    document,
    search,
    search_record,
    session_scope,
    staged_runner,
    trial,
)
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
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.calibration.runners.state import build_cache_context, space_from_config
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.core.code_fingerprint import (
    clear_fingerprint_cache,
    code_fingerprint,
    fingerprint_tree,
)
from hydromodpy.core.config_kit.field_param.sections import FieldHomogeneousSection
from hydromodpy.core.exceptions import CalibrationError, ConfigError, ObjectiveError
from hydromodpy.core.runtime.interrupts import StopRequested, TerminationRequested
from hydromodpy.core.scoring.stream_defaults import VALIDITY_PROVENANCE_CODE
from hydromodpy.core.state import host as host_module
from hydromodpy.core.state.layout import stop_flag_for
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.project.facade import Project
from hydromodpy.results.metric_rule import MetricsConfig, PeriodWindow
from hydromodpy.results.outcome import read_outcome, write_outcome
from hydromodpy.results.session.descriptor import (
    ParameterWidth,
    RestartRange,
    list_session_dirs,
    read_session,
    write_session,
)
from hydromodpy.results.session.journal import read_trials, trials_path
from hydromodpy.results.session.phase import read_phase
from hydromodpy.results.storage.attempt import request_stop
from hydromodpy.solver.base.simulation_config import SimulationTimeConfig
from hydromodpy.workflow.dispatch import KNOWN_WORKFLOWS, WorkflowUnknownError, resolve_workflow
from tests._helpers.persisting_simulation import SimulationStub
from tests._helpers.session_documents import calibration_window
from tests.unit.calibration._factories_config import PROCESS, PROJECT_BASE, preflight_of, toml_doc
from tests.unit.calibration._factories_runners import (
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

pytestmark = pytest.mark.usefixtures("ensure_bootstrap")


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


@pytest.mark.fast
def test_list_phases_gives_reason(tmp_path, capsys) -> None:
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
def test_list_phases_without_phases(tmp_path, capsys) -> None:
    path = write_document(tmp_path, SINGLE_STAGE)
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )

    out = capsys.readouterr().out.splitlines()
    assert out[0].split("\t") == ["[calibration]", "scipy_nelder_mead (cost to minimise)"]


@pytest.mark.fast
def test_method_options_need_method() -> None:
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
def test_single_stage_picks_method(tmp_path) -> None:
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
    ids=["failed run", "failed after scoring", "first run failing keeps the search"],
)
def test_failed_perturbed_run_gives_no_width(
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
def test_width_reaches_parallel_engines(method, parallel, width) -> None:
    cfg = make_config(method=method, parallel=parallel)

    kwargs = _engine_kwargs(cfg, space_from_config(cfg), start_at=None)

    assert kwargs.get("width") == width


@pytest.mark.parametrize(
    ("restarts", "indices"), [(None, [0]), (3, [0, 1, 2])], ids=["one search", "three restarts"]
)
def test_restarts_share_one_pool(monkeypatch, restarts, indices) -> None:
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


@pytest.mark.fast
def test_resume_after_docstring_edit_uses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _search(tmp_path)
    n_solved = len(first.trials())
    shipped = code_fingerprint()
    monkeypatch.setattr(state, "code_fingerprint", lambda: dict(shipped))

    again = _search(tmp_path, resume=True)

    assert all(line.only_case.from_cache for line in again.trials()[n_solved:])


@pytest.mark.fast
def test_resume_after_code_change_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _search(tmp_path)
    moved = {**code_fingerprint(), "solver": "another digest"}
    monkeypatch.setattr(state, "code_fingerprint", lambda: moved)

    with pytest.raises(CalibrationError, match=r"code\.solver changed since they ran"):
        _search(tmp_path, resume=True)


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
def test_value_unit_stays_as_written(
    model: type, first: dict[str, str], second: dict[str, str]
) -> None:
    dumps = [
        model.model_validate(doc).model_dump(mode="json", exclude_unset=True)
        for doc in (first, second)
    ]
    assert dumps[0] != dumps[1]


PHASE = PhaseContext(name="steady_k")
SCORED_BEFORE = {"schema": "test", "calibration": "2001-2002"}
SCORED_NOW = {"schema": "test", "calibration": "2001-2003"}


def _journal(
    persistence: CalibrationPersistence, k: float, *, context: dict | None, phase=PHASE
) -> None:
    metadata: dict[str, Any] = {"parameters": {"K": {"value": k}}}
    if context is not None:
        metadata["params_hash"] = params_hash({"K": k}, context=context)
    journal_trial(persistence, 1, k=k, phase=phase, metadata=metadata)


def test_trial_without_fingerprint_warns(tmp_path, caplog) -> None:
    persistence = make_session(tmp_path)
    _journal(persistence, 1e-5, context=None)

    with caplog.at_level(logging.WARNING):
        refuse_a_phase_another_cost_scored(persistence, PHASE.name, SCORED_NOW)

    assert "recorded no fingerprint" in caplog.text


def _claimed_by(persistence: CalibrationPersistence, pid: int) -> None:
    outcome = read_outcome(persistence.directory)
    assert outcome is not None
    write_outcome(
        persistence.directory,
        outcome.model_copy(update={"pid": pid, "host": socket.gethostname()}),
    )


def test_live_writer_blocks_resume(tmp_path) -> None:
    persistence = make_session(tmp_path)
    _claimed_by(persistence, os.getppid())

    with pytest.raises(CalibrationError, match="still written by process"):
        CalibrationPersistence(persistence.directory).resume_session()


def test_dead_writer_allows_resume(tmp_path, monkeypatch) -> None:
    persistence = make_session(tmp_path)
    _claimed_by(persistence, os.getppid())
    monkeypatch.setattr(host_module, "process_is_alive", lambda pid: False)

    descriptor = CalibrationPersistence(persistence.directory).resume_session()

    assert descriptor.status == "running"


def test_own_process_resumes(tmp_path) -> None:
    persistence = make_session(tmp_path)

    descriptor = CalibrationPersistence(persistence.directory).resume_session()

    assert descriptor.status == "running"


def test_refused_resume_keeps_files(tmp_path, monkeypatch) -> None:
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


def test_frozen_document_keeps_map(tmp_path) -> None:
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


def test_search_windows(tmp_path) -> None:
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


def test_staged_window_is_last_phase(tmp_path) -> None:
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


def test_session_cost_name() -> None:
    cfg = _staged({"variable": "gauge", "objective": "kge"})

    assert session_cost_name(cfg) == "kge"


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


def _write_search_toml(tmp_path: Path, *, save_runs: str, name: str = "run_calibration_k") -> Path:
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
    return _write_search_toml(tmp_path, save_runs="best_n")


def _the_session(project: Path):
    (directory,) = list_session_dirs(project)
    return directory


@pytest.fixture
def run(calib_toml, fake_pipeline, quadratic_metric):
    """Run the grid calibration of ``calib_toml`` on the fake pipeline."""
    return lambda **kwargs: run_calibration_cli(calib_toml, metric_fn=quadratic_metric, **kwargs)


def test_second_run_takes_next_version(run):
    run()
    summary = run()

    assert summary.session_dir.name == "toy.v2"
    assert summary.best_rel_dir == "runs/toy.v2"


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
    ids=["missing calibration section", "parameters without path"],
)
def test_unreadable_file_refused(tmp_path, fake_pipeline, text, match):
    with pytest.raises(ValueError, match=match):
        run_calibration_cli(write_document(tmp_path, text, "bad.toml"))


def test_preload_ignores_unscoped_hashes(tmp_path):
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


def test_objective_entry_point_runs(calib_toml, fake_pipeline, monkeypatch):
    calls: list[dict] = []

    def my_metric(ctx, *, objective, variable):
        calls.append({"objective": objective, "variable": variable})
        return float(abs(ctx.cfg.flow.param.K.field.value - 1e-4)), {}

    monkeypatch.setitem(sys.modules, "test_calib_metric_mod", SimpleNamespace(my_metric=my_metric))

    summary = run_calibration_cli(calib_toml, objective="test_calib_metric_mod:my_metric")
    assert summary.n_trials == 5
    assert len(calls) == 5
    assert all(c["variable"] == "discharge" for c in calls)


def test_no_default_evaluator():
    for module in (cli_runner, document, search, session_scope):
        assert not hasattr(module, "_default_evaluator")


def _config(**parameters) -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {"method": "grid", "max_trials": 5, "objective": "nse", "variable": "discharge"}
        | {"parameters": parameters}
    )


def test_missing_path_refused():
    with pytest.raises(ValueError, match="must declare a 'path'"):
        state.override_paths(_config(K={"bounds": [1e-6, 1e-3]}))


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
        "engine failure marks session failed",
        "keyboard interrupt marks session aborted",
        "sigterm marks session aborted",
        "stop request marks session aborted with its date",
    ],
)
def test_engine_error_closes_session(
    calib_toml, fake_pipeline, monkeypatch, error, status, message
):
    _fail_engine(monkeypatch, error)

    with pytest.raises(type(error)):
        run_calibration_cli(calib_toml)

    descriptor = read_session(_the_session(calib_toml.parent))
    assert (descriptor.status, descriptor.error_message) == (status, message)
    outcome = read_outcome(_the_session(calib_toml.parent))
    assert outcome is not None and outcome.status == status


def _metric(ctx, *, objective, variable):
    return (math.log10(ctx.cfg.flow.param.K.field.value) - math.log10(1e-4)) ** 2, {}


def test_stop_flag_then_resume(calib_toml, fake_pipeline):
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

    report = run_calibration_cli(calib_toml, metric_fn=_metric, resume=True)

    assert not stop_flag_for(session_dir).exists()
    assert read_session(session_dir).status == "completed"
    assert report.n_trials == 5


def test_termination_promotes_best_trial(calib_toml, fake_pipeline, monkeypatch):
    _cut_after_two_trials(monkeypatch)
    monkeypatch.setattr(
        TrialSolveRetention,
        "take",
        lambda self, trial_id: (KeptSolve(trial_id=int(trial_id), cost=0.0, folders=()), None),
    )

    with pytest.raises(TerminationRequested):
        run_calibration_cli(calib_toml, metric_fn=_metric)

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


def test_abort_is_fast(tmp_path):
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


def test_every_trial_crashing_fails(calib_toml, fake_pipeline):
    def crashing_metric(ctx, *, objective, variable):
        raise RuntimeError("metric blew up")

    with pytest.raises(EveryTrialFailedError, match="metric blew up"):
        run_calibration_cli(calib_toml, metric_fn=crashing_metric)

    session_dir = _the_session(calib_toml.parent)
    assert read_session(session_dir).status == "failed"
    assert len(read_trials(session_dir)) == 5


PRE_RELEASE_KEYS = [
    pytest.param("warmup_periods = 12", "warmup_periods", id="skipped samples"),
    pytest.param('observed_station_id = "OTHER"', "observed_station_id", id="station key"),
]


@pytest.mark.parametrize(("line", "key"), PRE_RELEASE_KEYS)
def test_pre_release_keys_refused(tmp_path, line, key) -> None:
    path = _case(tmp_path, CASE.replace("max_trials = 3\n", f"max_trials = 3\n{line}\n"))

    with pytest.raises(ConfigError, match=rf"holds calibration\.{key}, written by a pre-release"):
        load_toml_calibration(path)


RICH_CALIBRATION = """
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


def test_calibration_is_known_workflow() -> None:
    assert "calibration" in KNOWN_WORKFLOWS


WORKFLOW_FILES = [
    pytest.param(RICH_CALIBRATION, id="declared mode"),
    pytest.param("[calibration]\nmethod = 'grid'\n", id="calibration section only"),
]


@pytest.mark.parametrize("text", WORKFLOW_FILES)
def test_workflow_resolves_to_calibration(tmp_path, text) -> None:
    path = tmp_path / "calib.toml"
    path.write_text(text, encoding="utf-8")

    assert resolve_workflow(path, cli_workflow=None) == "calibration"


def test_retired_mode_names_replacement(tmp_path: Path):
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


def test_bare_metric_name_refused(bowl: Path):
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


def test_staged_reuse_refuses_metric_name(bowl: Path):
    phase = (
        '\n[[calibration.phases]]\nname = "one"\nmethod = "grid"\nmax_trials = 2\n'
        'parameters = ["K"]\nvariable = "discharge"\nobjective = "nse"\n'
    )
    bowl.write_text(bowl.read_text(encoding="utf-8") + phase, encoding="utf-8")

    with pytest.raises(CalibrationError) as excinfo:
        run_staged_calibration(bowl, objective="nse_seasonal_v2", resume=True)

    assert "objective='nse_seasonal_v2'" in str(excinfo.value)


def test_entry_point_is_accepted(bowl: Path, monkeypatch):
    def _metric(ctx, *, objective, variable):
        return 0.5, {}

    monkeypatch.setitem(
        sys.modules, "test_cli_dispatch_metric_mod", SimpleNamespace(my_metric=_metric)
    )

    summary = run_calibration_cli(bowl, objective="test_cli_dispatch_metric_mod:my_metric")
    assert summary.n_trials > 0


def _two_phase_config() -> CalibrationConfig:
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


def test_check_names_windows(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        calibration=_two_phase_config(),
        metrics=MetricsConfig.model_validate(
            {"window": {"start": "2016-01-01", "end": "2020-12-31"}}
        ),
    )

    lines = comparison_lines(cfg, tmp_path / "calibration.toml")

    assert lines[0] == "[metrics] window: 2016-01-01 to 2020-12-31, the window the run is scored on"
    assert "  scores on: no window, all of the run" in lines
    assert "  scores on: window 2016-01-01 to 2020-12-31" in lines


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


def test_strict_verdict_raises() -> None:
    output = _network(verdict={"on_invalid": "error"})

    with pytest.raises(CalibrationError, match="exceeds the validity length 150 m"):
        r_optim_verdict_extra({"net": output}, _components(5.31))


def test_empty_network_verdict() -> None:
    extra = r_optim_verdict_extra({"net": _network()}, _components(math.nan))

    verdict = extra["r_optim_verdict"]["net"]
    assert verdict["value"] is None and verdict["valid"] is False
    assert verdict["causes"] == ["empty"]
    with pytest.raises(CalibrationError, match="not a number"):
        r_optim_verdict_extra(
            {"net": _network(verdict={"on_invalid": "error"})}, _components(math.nan)
        )


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
            id="reads the first trial not a later one",
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
            id="one entry per output",
        ),
        pytest.param([{"flow.raw_cost": 1.0}], None, id="none without a paired output"),
        pytest.param([], None, id="none for empty history"),
        pytest.param([_paired("q", 7.0)], {"q": {"n_paired": 7}}, id="count without dates"),
    ],
)
def test_first_trial_pairing(history, expected) -> None:
    results = [
        result_of(ParamSuggestion(trial_id=index, values={}), 0.1, components=item)
        for index, item in enumerate(history)
    ]

    assert _first_trial_pairing(results) == expected


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


def test_descriptor_keeps_two_roots(tmp_path) -> None:
    persistence = _open(tmp_path)

    persistence.finalize_session(status="completed", best=None, root_search={"roots": ROOTS})

    assert read_session(persistence.directory).root_search == {"roots": ROOTS}
    payload = json.loads((persistence.directory / "session.json").read_text())
    assert payload["root_search"]["roots"]["minimal"]["k_star"] == pytest.approx(3.0e-6)


def test_close_hands_roots_to_descriptor(tmp_path) -> None:
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


def test_detail_sets_line_content(tmp_path) -> None:
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


def test_cut_journal_line_dropped(tmp_path) -> None:
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


def test_unknown_case_refused(tmp_path) -> None:
    persistence = _open(tmp_path)
    persistence.finalize_session(status="completed", best=None)
    descriptor = read_session(persistence.directory)
    write_session(persistence.directory, descriptor.model_copy(update={"case_id": "joint"}))
    before = (persistence.directory / "session.json").read_bytes()

    with pytest.raises(CalibrationError, match="joint"):
        CalibrationPersistence(persistence.directory).resume_session()

    assert (persistence.directory / "session.json").read_bytes() == before


def test_unexpanded_protocol_refused() -> None:
    with pytest.raises(ValueError, match="protocol"):
        CalibrationConfig.model_validate(
            {
                "protocol": "matching_hydrographic_network",
                "parameters": {"K": {"bounds": [1e-8, 1e-2], "search_space": "log"}},
            }
        )


def test_report_carries_protocol() -> None:
    summary = make_report(protocol=protocol_record("matching_hydrographic_network")).to_dict()

    assert summary["protocol"]["name"] == "matching_hydrographic_network"
    assert summary["protocol"]["references"]


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
def test_public_callables(module: str, names: list[str]) -> None:
    loaded = importlib.import_module(f"hydromodpy.calibration.{module}")

    assert all(callable(getattr(loaded, name)) for name in names)


def test_legacy_runner_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hydromodpy.calibration.runner")


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
def project_with_network(tmp_path: Path) -> Path:
    """A project holding its network where the convention puts it."""
    geometry = tmp_path / "data" / "hydrography" / "streams.gpkg"
    geometry.parent.mkdir(parents=True)
    geometry.write_bytes(_PROJECT_NETWORK)
    configs = tmp_path / "configs"
    configs.mkdir()
    return tmp_path


def _load(project_with_network: Path, declared: str, *, at: str = "configs") -> str | None:
    path = project_with_network / at / "calibration.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TOML.format(declared=declared), encoding="utf-8")
    cfg, _raw = load_toml_calibration(path)
    resolved = cfg.outputs["net"].map.complete
    return None if resolved is None else str(resolved)


def test_absolute_path_kept(project_with_network: Path) -> None:
    declared = (project_with_network / "data" / "hydrography" / "streams.gpkg").resolve()
    # The field is a Path: Windows spells it with backslashes, the same file.
    assert Path(_load(project_with_network, declared.as_posix())) == declared


@pytest.fixture
def decoy(tmp_path: Path) -> Path:
    """A directory holding another file of the same name, and its sub-path."""
    trap = tmp_path / "elsewhere"
    (trap / "data" / "hydrography").mkdir(parents=True)
    (trap / "streams.gpkg").write_bytes(_DECOY_NETWORK)
    (trap / "data" / "hydrography" / "streams.gpkg").write_bytes(_DECOY_NETWORK)
    return trap


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


def test_in_memory_config_anchors_network(
    project_with_network: Path, decoy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Python and embedded modes build the config in memory and reach the runner
    # without going through the TOML loader. Anchoring only there left them
    # reading the working directory.

    cfg = _in_memory_config("streams.gpkg")
    monkeypatch.chdir(decoy)
    # The cache preload is the first thing the core touches after anchoring.
    monkeypatch.setattr(search, "preload_hash_cache", _halt)
    session_dir = project_with_network / "sessions" / "calage"
    session_dir.mkdir(parents=True)

    with pytest.raises(_Halt):
        run_calibration_core(
            cfg,
            None,
            persistence=CalibrationPersistence(session_dir),
            space=space_from_config(cfg),
            project_root=project_with_network,
            cfg_path=project_with_network / "project.toml",
        )

    assert Path(cfg.outputs["net"].map.complete).read_bytes() == _PROJECT_NETWORK


_MAPS = """
[calibration.outputs.net]
support = "network"
map.complete = "{maximal}"
map.permanent = "{minimal}"
map.calibrate_on = {calibrate_on}
{extent}
"""


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


def _two_phases(tmp_path: Path, *, regime: str, single_metric: bool, extent: bool = True) -> str:
    maximal, minimal = _maps(tmp_path)
    route = 'variable = "net"\nobjective = "distance_gap"' if single_metric else ""
    route = route or 'objective_blocks = ["gap"]'
    return _TWO_PHASES.replace("REGIME", regime).replace("SINGLE_METRIC", route) + _outputs(
        maximal.as_posix(), minimal.as_posix(), extent=extent
    )


@pytest.mark.parametrize("single_metric", [False, True])
def test_steady_extent_refused(tmp_path, single_metric: bool) -> None:
    doc = _two_phases(tmp_path, regime="steady", single_metric=single_metric)

    findings = preflight_of(tmp_path, doc)

    refused = [item for item in findings if "extent table" in item.detail]
    # Only the steady phase is named; the transient one reads the extent.
    assert len(refused) == 1
    assert refused[0].path == "calibration.outputs.net"
    assert "'k_network'" in refused[0].detail


def test_steady_override_extent_refused(tmp_path) -> None:
    doc = _two_phases(tmp_path, regime="transient", single_metric=False).replace(
        'regime = "transient"', 'overrides = { "flow.flow_regime" = "steady" }'
    )

    findings = preflight_of(tmp_path, doc)

    refused = [item for item in findings if "extent table" in item.detail]
    assert len(refused) == 1
    assert "'k_network'" in refused[0].detail


_PERMANENT_SOURCE = 'map.permanent = "data.hydrography"\nmap.calibrate_on = "permanent"'


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


def _doc(tmp_path: Path, *, minimal: str) -> str:
    maximal = tmp_path / "streams.gpkg"
    maximal.write_bytes(b"maximal")
    return _DOC.replace("MAXIMAL", maximal.as_posix()).replace("MINIMAL", minimal)


def test_permanent_source_needs_hydrography(tmp_path) -> None:
    doc = _doc(tmp_path, minimal=_PERMANENT_SOURCE)

    findings = preflight_of(tmp_path, doc)

    named = [item for item in findings if "map.permanent" in item.detail]
    assert len(named) == 1
    assert named[0].severity == "error"
    assert named[0].path == "calibration.outputs.net"
    assert "data.hydrography.sources" in named[0].detail


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


def test_answered_best(
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


def _write_search_file(tmp_path: Path, *extra: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text(_FILE + "".join(textwrap.dedent(item) for item in extra), encoding="utf-8")
    (tmp_path / "streams.gpkg").write_text("", encoding="utf-8")
    return path


def _sessions(tmp_path: Path) -> list[str]:
    root = tmp_path / "sessions"
    return sorted(path.name for path in root.iterdir()) if root.is_dir() else []


def test_search_refused_before_session(tmp_path, prepared) -> None:
    with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
        run_calibration_cli(_write_search_file(tmp_path))

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []


def test_phase_refused_before_session(tmp_path, prepared) -> None:
    with pytest.raises(ObjectiveError, match=r"flow\.bc\.drainage\.value"):
        run_staged_calibration(_write_search_file(tmp_path, _PHASE))

    assert prepared == ["calib.toml"]
    assert _sessions(tmp_path) == []


def test_python_search_refused_before_session(tmp_path, prepared) -> None:
    path = _write_search_file(tmp_path)
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


def test_k_over_r_window() -> None:
    time = SimpleNamespace(start_datetime="2000-01-01", end_datetime="2002-12-31T00:00:00")
    trial_ctx = SimpleNamespace(base_cfg=SimpleNamespace(simulation=SimpleNamespace(time=time)))

    extra = _ratios(trial_ctx=trial_ctx)

    assert "m/s over 2000-01-01 to 2002-12-31 on output" in extra["k_over_r_note"]
    assert extra["r_mean_window"] == {"start": "2000-01-01", "end": "2002-12-31"}


def test_k_over_r_ratios() -> None:
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


def test_nearly_full_aquifer_said() -> None:
    extra = _ratios({**R_MEAN, "network.d_sat_m": 27.0, "network.d_sat_over_d": 0.9})

    assert "90% full" in extra["k_over_r_note"]


def model_with_k_unit(unit):
    param = {"K": SimpleNamespace(field=SimpleNamespace(unit=unit))}
    return SimpleNamespace(base_cfg=SimpleNamespace(flow=SimpleNamespace(param=param)))


K_UNITS = [
    pytest.param({"space": _space(units="m/d")}, id="unit declared by the search"),
    pytest.param(
        {"space": _space(units="m/s"), "trial_ctx": model_with_k_unit("m/d")},
        id="unit of the model field",
    ),
]


@pytest.mark.parametrize("overrides", K_UNITS)
def test_k_read_in_its_unit(overrides) -> None:
    extra = _ratios(**overrides)

    np.testing.assert_allclose(extra["k_optim_m_s"], 5.0e-4 / 86400.0)  # m/d to m/s


def test_dry_catchment_ratios() -> None:
    extra = _ratios({**R_MEAN, "network.d_sat_m": 0.0})

    assert extra["d_sat_m"] == 0.0
    assert extra["t_optim_m2_s"] == 0.0


def test_wrong_unit_warns(caplog) -> None:
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
        "another parameter",
        "a multiplier",
        "no network output",
        "no r mean",
        "no best parameters",
        "more than one parameter",
    ],
)
def test_ratios_absent(overrides) -> None:
    assert _ratios(**overrides) == {}


def test_interval_bound_wording(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        log_parameter_interval(
            _interval(reaches_upper=True),
            result_of(ParamSuggestion(trial_id=0, values={}), 0.123),
        )

    assert "Sy = 0.005: the trials within 0.1 of the best run to the upper" in caplog.text
    assert "reached" not in caplog.text


_SPACE = ParameterSpace.from_toml_mapping(
    {"K": {"bounds": [1.0, 5.0], "path": "flow.param.K.field.value"}}
)


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, object]]:
    return [{"parameters": {"K": value}, "cost": cost} for value, cost in pairs]


_SHARP = _trace([(1.0, 10.0), (2.0, 1.0), (3.0, 1.02), (4.0, 9.0), (5.0, 30.0)])


def test_declared_width_used() -> None:
    decl = make_config(uncertainty={"cost_margin": "0.1%"}).interval_width_for()

    (interval,) = margin_intervals_or_none(_SHARP, ["K"], _SPACE, decl)

    assert interval.margin == pytest.approx(0.001)
    assert interval.lower == interval.upper == 2.0


@pytest.mark.parametrize(("declared", "metres"), [("150 m", 150.0), ("0.3 km", 300.0), (75, 75.0)])
def test_length_read_in_metres(declared: object, metres: float) -> None:
    output = _network(verdict={"validity_length": declared})

    assert float(output.verdict.validity_length.to("m").magnitude) == pytest.approx(metres)
    assert output.model_dump()["verdict"]["validity_length"] == pytest.approx(metres)


@pytest.mark.parametrize("declared", ["0 m", "-10 m", "2 s", "two cells"])
def test_bad_length_refused(declared: str) -> None:
    with pytest.raises(ValidationError):
        _network(verdict={"validity_length": declared})


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
def test_distant_roots_warn(delta, warned, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        search_record._log_the_two_roots({**ROOTS, "delta_log10": delta})

    assert ("satisfies neither map" in caplog.text) is warned


def test_two_roots_line(caplog) -> None:
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


def test_parameter_widths() -> None:
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
def test_unreadable_width_warns(width, trace, message, caplog) -> None:
    with caplog.at_level("WARNING"):
        assert margin_intervals_or_none(trace, ["K"], _SPACE, width) == []

    assert message in caplog.text


@pytest.mark.parametrize(("root", "expected"), [(None, []), ("interval", ["interval"])])
def test_root_search_interval(root, expected) -> None:
    search = Mock(spec=BisectionAdapter)
    search.root_interval.return_value = root

    found = margin_intervals_or_none(_SHARP, ["K"], _SPACE, _width(25.0), search)

    assert found == expected
    search.root_interval.assert_called_once_with(margin=25.0, kind="absolute")


def test_mesh_cell_first_finite() -> None:
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
def test_line_fit_width(monkeypatch, parallel) -> None:
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
def test_fit_without_freedom_keeps_report(monkeypatch, caplog, observed, answer, message) -> None:
    monkeypatch.setattr(composite, "build_paired_vector_capture", _line_capture(observed))
    monkeypatch.setattr(
        trial, "run_trial_light", _runs(lambda values: False, scores_before_failing=False)
    )
    report = SimpleNamespace(best_parameters=dict(answer), parameter_uncertainty=None)

    with caplog.at_level(logging.WARNING):
        assert _attach(report) is report

    assert __import__("re").search(message, caplog.text)


def test_no_station_keeps_report(monkeypatch, caplog) -> None:
    def refuse(**options):
        raise search.UncertaintyNotAvailableError("the outputs name no station")

    monkeypatch.setattr(search, "_DerivativeEvaluator", refuse)
    report = SimpleNamespace(best_parameters=dict(ANSWER), parameter_uncertainty=None)

    with caplog.at_level(logging.WARNING):
        assert _attach(report) is report

    assert "No width is reported: the outputs name no station" in caplog.text


def test_empty_search_failed() -> None:
    assert session_scope.search_status(SimpleNamespace(history=[])) == "failed"


def _bisection(**records) -> Mock:
    search = Mock(spec=BisectionAdapter)
    search.roots = records.pop("roots", 1)
    search.bracket_record.return_value = records.get("bracket")
    search.roots_record.return_value = records.get("roots_record")
    search.root_outside_bounds.return_value = records.get("outside")
    return search


def test_two_roots_no_interval(caplog) -> None:
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


def test_outcome_logs_two_roots(monkeypatch) -> None:
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


def test_session_scratch_release(monkeypatch, caplog) -> None:
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


def test_no_block_cost_fractions() -> None:
    blocks = [SimpleNamespace(name="a", weight=1.0), SimpleNamespace(name="b", weight=1.0)]
    cfg = SimpleNamespace(objective_blocks=blocks)
    done = EvaluationResult(trial_id=1, sim_id=None, cost=1.0, components={})

    assert search.phase_cost_block_fractions(cfg, [done], done) is None


def test_project_default_error_names_file(monkeypatch, tmp_path) -> None:
    def refuse(table, **kwargs):
        raise ConfigError("the gauge is unknown")

    monkeypatch.setattr("hydromodpy.calibration.config.apply_project_defaults", refuse)
    path = tmp_path / "calib.toml"

    with pytest.raises(ConfigError, match=f"^{path}: the gauge is unknown"):
        document._with_project_defaults({"calibration": {}}, path)


def test_unresolved_parameter_name(monkeypatch, tmp_path) -> None:
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


def test_bare_input_name_stops_load(monkeypatch, tmp_path) -> None:
    from hydromodpy.core.toml_io.paths import BareInputNameError

    cfg = SimpleNamespace(parameters={"K": object()})
    monkeypatch.setattr(
        trial,
        "_PIPELINE",
        FakePipeline(config_error=BareInputNameError("inputs 'piezometry' is a bare name")),
    )

    with pytest.raises(BareInputNameError, match="'piezometry' is a bare name"):
        document._resolve_parameter_names(cfg, tmp_path)
