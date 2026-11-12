"""The project runner: which steps a run executes, and how an attempt is claimed and closed.

A run executes only the steps it asks for (until_step, from_step), checked first by a dry
run and then on a small synthetic project. An attempt claims its run folder, is resumed
or refused, and closes its outcome when a signal or a crash cuts it.
"""

from __future__ import annotations

import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError, ResumeError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.pipeline_steps import STEP_NAMES
from hydromodpy.core.runtime.interrupts import TerminationRequested
from hydromodpy.core.state.layout import (
    INTERNAL_DIRNAME,
    PROJECT_MARKER_FILENAME,
    RUN_INTERNAL_CHECKPOINTS_DIRNAME,
)
from hydromodpy.project.launch.plan import PlanDraft
from hydromodpy.project.runner import ProjectRunner
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.storage.run_log import run_log_path
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.record.attempt import run_attempt, sealed_run_of
from hydromodpy.workflow.record.journal import WorkflowJournal
from tests._helpers.run_stores import facts_of, seal_demo_run
from tests.unit.project._helpers import DEM, PROJECT_TOML, REPO_ROOT

SYNTHETIC_PROJECT = REPO_ROOT / "examples" / "projects" / "00_getting_started" / "project.toml"


def _declared_config(root: Path):
    from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.core.workspace.config import WorkspaceConfig

    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(root), root=str(root)),
        geographic=GeographicConfig(source_mode="synthetic"),
        domain={"depth_model": {"kind": "constant_thickness", "thickness": 50.0}},
    )


class _StubProject:
    """The slice of ``Project`` that a dry run reads."""

    def __init__(self, root: Path, *, model_phase_ready: bool = False) -> None:
        self.built = 0
        self._run_counter = 0
        self._no_display = True
        self._config_path = root / "project.toml"
        # A real configuration: the runner copies it with the overrides folded in.
        self._cfg = _declared_config(root)
        # The ready check reads all three fields.
        self._ctx = SimpleNamespace(
            setup=SimpleNamespace(
                workspace=SimpleNamespace(project_root=root) if model_phase_ready else None,
                geographic="geo" if model_phase_ready else None,
                domain="domain" if model_phase_ready else None,
            )
        )

    def _ensure_model_built(self) -> None:
        self.built += 1
        self._ctx.setup.workspace = SimpleNamespace(project_root=self._cfg.workspace.project_root)
        self._ctx.setup.geographic = "geo"
        self._ctx.setup.domain = "domain"


def _dry_run(project: _StubProject, **kwargs) -> PlanDraft:
    return ProjectRunner(project).draft(**kwargs)  # type: ignore[arg-type]


def _isolate_workspace(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    # Keep the data folder off the repository examples, which xdist workers share.
    monkeypatch.setenv("HMP_WORKSPACE", str(root))
    monkeypatch.setenv("MPLBACKEND", "Agg")


@pytest.mark.parametrize(
    ("name", "resume", "named"),
    [
        (None, "", "declared"),
        ("asked", "", "asked"),
        ("asked", "kept", "kept"),
        (None, None, "declared"),
    ],
    ids=["bare resume", "bare resume and a case", "resume of a name", "no resume"],
)
def test_run_name(tmp_path: Path, name: str | None, resume: str | None, named: str) -> None:
    project = _StubProject(tmp_path)
    project._cfg.simulation.name = "declared"

    assert ProjectRunner(project)._run_name(name, resume) == named  # type: ignore[arg-type]


@pytest.mark.parametrize("until_step", [None, "setup_process", "run_solver", "export"])
def test_no_model_phase_built_up_front(tmp_path: Path, until_step: str | None) -> None:
    project = _StubProject(tmp_path)

    _dry_run(project, until_step=until_step)

    assert project.built == 0


def test_ready_project_skips_forward(tmp_path: Path) -> None:
    project = _StubProject(tmp_path, model_phase_ready=True)

    assert _dry_run(project, until_step=None).steps == STEP_NAMES[5:]


@pytest.mark.parametrize("bound", ["until_step", "from_step"])
@pytest.mark.parametrize(
    ("word", "says"),
    [
        (0, "named, not numbered"),
        ("3", "Unknown"),
        ("SetupProcessStep", "Unknown"),
        ("no", "Unknown"),
    ],
)
def test_step_is_named(tmp_path: Path, bound: str, word: object, says: str) -> None:
    with pytest.raises(ConfigError, match=says):
        _dry_run(_StubProject(tmp_path), **{bound: word})


def test_window_starts_after_it_ends(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="is past until_step"):
        _dry_run(_StubProject(tmp_path), from_step="build_mesh", until_step="resolve")


def test_model_phase_index() -> None:
    # A step list without setup_process gives 0, so every window reaches the model phase.
    from hydromodpy.workflow import window as runner_mod
    from hydromodpy.workflow.steps.sequence import standard_steps

    assert runner_mod.model_phase_index(()) == 0
    assert runner_mod.model_phase_index((SimpleNamespace(name="alpha"),)) == 0
    assert runner_mod.model_phase_index(standard_steps()) == 5


def test_head_only_window_cannot_resume(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="keeps no journal"):
        _dry_run(_StubProject(tmp_path), resume="earlier", until_step="build_geographic")


def test_delineation_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.project.facade import Project

    _isolate_workspace(monkeypatch, tmp_path)

    project = Project(SYNTHETIC_PROJECT, headless=True, no_display=True)
    try:
        project.simulate(name="geographic_only", until_step="build_geographic")
        setup = project._ctx.setup
        assert setup.geographic is not None, "the requested step did not run"
        assert setup.domain is not None
        assert setup.cell_mesh is None
        assert project._ctx.loaded_data.loaded_plan_types is None, "load_data ran unasked"
    finally:
        project.close()


def test_partial_run_is_adopted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Without adoption the next call runs setup_workspace again and drops the delineation.
    from hydromodpy.project.facade import Project

    _isolate_workspace(monkeypatch, tmp_path)

    project = Project(SYNTHETIC_PROJECT, headless=True, no_display=True)
    try:
        project.simulate(name="geographic_only", until_step="build_geographic")
        assert project._phase == "geographic"
        delineated = project._ctx.setup.geographic
        assert delineated is not None

        # A full run plans from the shared model phase instead of rebuilding it.
        draft = project.simulate(dry_run=True)

        assert project._ctx.setup.geographic is delineated, "the delineation was thrown away"
        assert draft.steps == STEP_NAMES[5:]
    finally:
        project.close()


UNTIL_CASE = "until_extract"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return project


def _runner_of(project: Path, monkeypatch: pytest.MonkeyPatch, *, write_facts: bool):
    with run_attempt(project, UNTIL_CASE, case_id=UNTIL_CASE, project="demo", site=None) as handle:
        if write_facts:
            facts = facts_of(handle.claim, project="demo", n_cells=4, n_layers=1)
            RunStore.open(handle.run_dir, facts=facts, workspace=project).close()
    sealed = sealed_run_of(handle.claim, project)
    owner = SimpleNamespace(_store=None, _run_history=[])
    runner = ProjectRunner(owner)
    monkeypatch.setattr(runner, "execute", lambda *_args, **_kwargs: sealed)
    monkeypatch.setattr("hydromodpy.project.phases.open_catalog", lambda _project: None)
    return runner, owner, sealed


def test_partial_run_read_from_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    runner, owner, sealed = _runner_of(project, monkeypatch, write_facts=True)

    assert effective_status(sealed.run_dir) == "partial"
    run = runner.run(until_step="extract")

    assert run is not None
    assert run.sim_id == sealed.sim_id
    assert run.name == UNTIL_CASE
    assert run.status == "partial"
    assert owner._run_history == [run]


def test_partial_run_without_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    runner, owner, _ = _runner_of(project, monkeypatch, write_facts=False)

    assert runner.run(until_step="extract") is None
    assert owner._run_history == []


LAST_WORDS = "stress period 51: the solver is about to give up"


@pytest.mark.parametrize(
    ("signal_error", "status", "number"),
    [
        (KeyboardInterrupt, "aborted", int(signal.SIGINT)),
        (TerminationRequested, "aborted", int(signal.SIGTERM)),
        (RuntimeError, "failed", None),
    ],
)
def test_interrupted_run_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal_error: type[BaseException],
    status: str,
    number: int | None,
) -> None:
    from hydromodpy.project.facade import Project

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()), encoding="utf-8"
    )

    class _Pipeline:
        def __init__(self, steps, *, workspace, run_dir) -> None:
            self.steps = steps
            self.run_dir = run_dir

        def run(self, state, **kwargs):
            heartbeat = kwargs.get("heartbeat")
            if heartbeat is not None:
                heartbeat.set_step("run_solver")
            get_logger("hydromodpy.solver.test").warning(LAST_WORDS)
            raise signal_error("cut")

    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)
    project = Project(config_path, no_display=True)

    with pytest.raises(signal_error):
        project._execute(name="asked_name")

    run_dir = tmp_path / "runs" / "asked_name"
    outcome = read_outcome(run_dir)
    assert outcome is not None
    assert outcome.status == status
    assert outcome.step == "run_solver"
    assert outcome.ended_at is not None
    assert outcome.signal == number
    if status == "failed":
        assert outcome.error is not None and outcome.error.type == "RuntimeError"
    assert outcome.log_tail, "the end of the run log travels with the outcome"
    assert any(LAST_WORDS in line for line in outcome.log_tail)
    assert run_log_path(run_dir).is_file()
    assert LAST_WORDS in run_log_path(run_dir).read_text(encoding="utf-8")
    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    assert LAST_WORDS in readme
    assert not (tmp_path / ".hmp" / "index.duckdb").exists()


WINDOW_CASE = "asked_name"


class _JournallingPipeline:
    """Journals its first step for real and records what it was asked."""

    calls: list[dict] = []

    def __init__(self, steps, *, workspace, run_dir) -> None:
        self.steps = steps
        self.workspace = workspace
        self.run_dir = run_dir

    def run(
        self, state, *, resume_from=None, parallel=True, model_phase_ready=False, heartbeat=None
    ):
        type(self).calls.append({"resume_from": resume_from, "steps": len(self.steps)})
        if heartbeat is not None:
            heartbeat.set_step("validate")
        if resume_from is None:
            journal = WorkflowJournal(self.run_dir)
            step_id = journal.start_step(
                run_id=state.run_id, step_order=0, step_name="validate", inputs_hash="x"
            )
            journal.finish_step(step_id=step_id, status="completed")
        return state


def test_unsealed_window_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.project.facade import Project

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()), encoding="utf-8"
    )
    _JournallingPipeline.calls = []
    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _JournallingPipeline)
    monkeypatch.setenv("HMP_WORKSPACE", str(tmp_path))
    run_dir = tmp_path / "runs" / WINDOW_CASE

    with Project(config_path, no_display=True) as project:
        project._execute(name=WINDOW_CASE, until_step="run_solver")

    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "completed" and outcome.attempt == 1
    assert effective_status(run_dir) == "partial", "completed without a seal is partial"
    checkpoints = run_dir / INTERNAL_DIRNAME / RUN_INTERNAL_CHECKPOINTS_DIRNAME
    assert (checkpoints / "steps.json").is_file(), "the journal survives a window without a seal"
    assert not (run_dir / "manifest.json").exists()

    with Project(config_path, no_display=True) as project:
        project._execute(resume=WINDOW_CASE, until_step="run_solver")

    resumed = read_outcome(run_dir)
    assert resumed is not None and resumed.attempt == 2
    assert (run_dir / "attempts" / "1" / "outcome.json").is_file()
    assert _JournallingPipeline.calls[-1]["resume_from"] == 1, "the resume picks up after step 0"
    assert (checkpoints / "steps.json").is_file()
    assert not (tmp_path / INTERNAL_DIRNAME / "index.duckdb").exists()


class _Claimed:
    """A claimed attempt in a real project, with the data layer and the keys doubled."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, if_exists="version"):
        import hydromodpy.data.loading.inputs as inputs
        import hydromodpy.project.runner as runner_module
        from hydromodpy.workflow.record.attempt import run_attempt

        self.root = tmp_path / "ws"
        self.root.mkdir()
        self.written: list[str] = []
        self.requests = iter(["rid-1", "rid-2", "rid-3"])
        self.cfg = SimpleNamespace(
            workspace=SimpleNamespace(project_root=str(self.root), data_path=self.root / "data"),
            simulation=SimpleNamespace(if_exists=if_exists),
            site=None,
            flow=None,
            mesh=None,
        )
        self.ctx = SimpleNamespace(
            bounds=None, inputs=None, run_dir=None, setup=SimpleNamespace(locked_inputs=None)
        )
        self.project = SimpleNamespace(_ctx=self.ctx)
        self.runner = ProjectRunner(self.project)  # type: ignore[arg-type]
        monkeypatch.setattr(inputs, "resolve_inputs", lambda cfg, **kw: "RESOLVED")
        monkeypatch.setattr(
            runner_module, "request_id_of", lambda cfg, resolved, **kw: next(self.requests)
        )
        monkeypatch.setattr(runner_module, "solution_key_of", lambda cfg, rid, **kw: f"key:{rid}")
        monkeypatch.setattr(runner_module, "solver_binaries", lambda cfg: {})
        monkeypatch.setattr(runner_module, "source_state_digests", lambda cfg, root: {})
        monkeypatch.setattr(runner_module, "zone_run_ids", lambda cfg, root: {})
        monkeypatch.setattr(
            runner_module,
            "write_claim_config",
            lambda ctx, **kw: (
                self.written.append(ctx.run_dir.name)
                or (ctx.run_dir / "config.toml").write_text("[flow]\n")
            ),
        )
        self.attempt = lambda name: run_attempt(
            self.root, name, case_id=name, project="ws", site=None
        )

    def claim(
        self, handle, *, name="demo", skip=True, form_of="dict", window_source=None, **members
    ):
        from hydromodpy.project.request import RunRequest

        request = RunRequest(config={"a": 1}, form=form_of, **members)
        return self.runner._claim_documents(
            handle,
            request,
            self.cfg,
            self.root,
            name=name,
            skip_identical=skip,
            window_source=window_source,
        )


def _identical(monkeypatch: pytest.MonkeyPatch, root: Path, key: str, name="demo") -> Path:
    import hydromodpy.results.storage.sealing as sealing
    import hydromodpy.workflow.replay_checks as replay_checks

    run_dir, _ = seal_demo_run(root, name)
    monkeypatch.setattr(
        sealing, "sealed_solution_key", lambda directory: key if directory == run_dir else None
    )
    monkeypatch.setattr(replay_checks, "api_inputs_intact", lambda directory, project: True)
    return run_dir


def test_identical_run_undoes_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)
    found = _identical(monkeypatch, claimed.root, "key:rid-1")

    with claimed.attempt("demo") as handle:
        key, identical = claimed.claim(handle)
        claimed_dir = handle.run_dir
        assert identical == found
        handle.withdraw()

    assert claimed_dir != found
    assert not claimed_dir.exists(), "no directory is left behind by a skipped run"
    assert sorted(entry.name for entry in (claimed.root / "runs").iterdir()) == ["demo"]


def test_if_exists_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.results.catalog.registration import NameTakenError

    claimed = _Claimed(tmp_path, monkeypatch, if_exists="fail")
    _identical(monkeypatch, claimed.root, "key:rid-1")

    # An identical run is still given back, whatever if_exists says.
    with claimed.attempt("demo") as handle:
        _, identical = claimed.claim(handle)
        assert identical is not None
        handle.withdraw()

    # A different request is refused, and its claim goes with the refusal.
    with pytest.raises(NameTakenError, match="runs/demo"), claimed.attempt("demo") as handle:
        claimed.claim(handle)
    assert sorted(entry.name for entry in (claimed.root / "runs").iterdir()) == ["demo"]


def test_if_exists_fail_free_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = _Claimed(tmp_path, monkeypatch, if_exists="fail")

    with claimed.attempt("demo") as handle:
        _, identical = claimed.claim(handle)
        run_dir = handle.run_dir

    assert identical is None
    assert run_dir.name == "demo"


def test_retry_of_another_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="boom"), claimed.attempt("demo") as handle:
        claimed.claim(handle)
        (handle.run_dir / "partial.dat").write_text("x")
        raise RuntimeError("boom")

    with claimed.attempt("demo") as handle:
        claimed.claim(handle)
        run_dir = handle.run_dir

    assert read_outcome(run_dir).attempt == 2
    assert (run_dir / "attempts" / "1" / "partial.dat").is_file(), "the other request is filed"
    assert not (run_dir / "partial.dat").exists()
    assert (run_dir / "config.toml").is_file(), "the new attempt keeps what it asks for"
    assert (run_dir / "request.json").is_file()
    assert (run_dir / "attempts" / "1" / "config.toml").is_file(), "attempt 1 keeps its own"
    assert (run_dir / "attempts" / "1" / "request.json").is_file()
    assert claimed.written == ["demo", "demo"], "each attempt writes its documents once"


def test_resume_of_a_changed_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="boom"), claimed.attempt("demo") as handle:
        claimed.claim(handle)
        (handle.run_dir / "partial.dat").write_text("x")
        raise RuntimeError("boom")
    stopped = read_outcome(handle.run_dir)

    with (
        pytest.raises(ResumeError, match="changed since attempt 1 stopped.*without --resume"),
        claimed.attempt("demo") as retry,
    ):
        claimed.claim(retry, resume="demo")

    assert read_outcome(handle.run_dir) == stopped, "the refusal leaves the attempt as it stopped"
    assert (handle.run_dir / "partial.dat").is_file()
    assert not (handle.run_dir / "attempts").exists()


def test_resume_of_the_same_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)
    claimed.requests = iter(["same", "same"])
    with pytest.raises(RuntimeError, match="boom"), claimed.attempt("demo") as handle:
        claimed.claim(handle)
        (handle.run_dir / "partial.dat").write_text("x")
        raise RuntimeError("boom")

    with claimed.attempt("demo") as retry:
        claimed.claim(retry, resume="demo")
        run_dir = retry.run_dir

    assert (run_dir / "partial.dat").is_file()
    assert read_outcome(run_dir).attempt == 2


def test_window_state_in_request_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hydromodpy.project.runner as runner_module

    claimed = _Claimed(tmp_path, monkeypatch)
    seen: list[dict] = []

    def spy(cfg, resolved, **kwargs):
        seen.append(kwargs)
        return "rid-w2"

    monkeypatch.setattr(runner_module, "request_id_of", spy)
    monkeypatch.setattr(
        runner_module,
        "window_input_entry",
        lambda root, source: SimpleNamespace(sha256="digest-w1"),
    )
    with claimed.attempt("island_w2") as handle:
        claimed.claim(handle, name="island_w2", window_source=object())
    with claimed.attempt("island") as handle:
        claimed.claim(handle, name="island")

    assert [kwargs["window_state"] for kwargs in seen] == ["digest-w1", None]


def test_failed_resolution_leaves_an_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The claim comes before the inputs, so a failed download shows in status.
    import hydromodpy.data.loading.inputs as inputs

    claimed = _Claimed(tmp_path, monkeypatch)

    def refuse(cfg, **kwargs):
        raise ConfigError("no network")

    monkeypatch.setattr(inputs, "resolve_inputs", refuse)
    with pytest.raises(ConfigError, match="no network"), claimed.attempt("demo") as handle:
        claimed.claim(handle)

    outcome = read_outcome(claimed.root / "runs" / "demo")
    assert outcome is not None and outcome.status == "failed"


def test_request_of_a_project() -> None:
    project = SimpleNamespace(_ctx=SimpleNamespace(raw_toml={"flow": {"a": 1}}))
    runner = ProjectRunner(project)  # type: ignore[arg-type]

    request = runner.request_of(name="asked", set={"K": 2e-5}, fresh=True, resume=None)

    assert request.config == {"flow": {"a": 1}}
    assert (request.name, request.set, request.fresh, request.form) == (
        "asked",
        {"K": 2e-5},
        True,
        "object",
    )
    with pytest.raises(ConfigError, match="Write 'two_words'"):
        runner.request_of(name="two words")


@pytest.mark.parametrize("error", ["conflict", "unreadable"])
def test_run_returned_when_index_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: str
) -> None:
    import hydromodpy.project.phases as phases
    import hydromodpy.project.runner as runner_module
    import hydromodpy.results.catalog.indexer as indexer
    from hydromodpy.core.exceptions import CatalogUnreadableError, WriteConflictError

    raised = (
        WriteConflictError("lock held") if error == "conflict" else CatalogUnreadableError("torn")
    )

    def refuse(project) -> None:
        raise raised

    sealed = SimpleNamespace(project_root=tmp_path, run_dir=tmp_path / "runs" / "r", sim_id="sid")
    project = SimpleNamespace(_run_history=[])
    runner = ProjectRunner(project)  # type: ignore[arg-type]
    monkeypatch.setattr(runner, "execute", lambda *a, **k: sealed)
    monkeypatch.setattr(indexer, "index_after_run", lambda root: object())
    monkeypatch.setattr(phases, "open_catalog", refuse)
    monkeypatch.setattr(runner_module, "run_view_of", lambda run_dir, **k: "V")

    assert runner.run() == "V"
    assert project._run_history == ["V"]


def test_failed_index_pass_skips_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import hydromodpy.project.phases as phases
    import hydromodpy.project.runner as runner_module
    import hydromodpy.results.catalog.indexer as indexer

    opened: list[object] = []
    sealed = SimpleNamespace(project_root=tmp_path, run_dir=tmp_path / "runs" / "r", sim_id="sid")
    runner = ProjectRunner(SimpleNamespace(_run_history=[]))  # type: ignore[arg-type]
    monkeypatch.setattr(runner, "execute", lambda *a, **k: sealed)
    monkeypatch.setattr(indexer, "index_after_run", lambda root: None)
    monkeypatch.setattr(phases, "open_catalog", opened.append)
    monkeypatch.setattr(runner_module, "run_view_of", lambda run_dir, **k: "V")

    assert runner.run() == "V"
    assert opened == []


def _failed_case(workspace: Path, name: str, *, frozen: bool = True) -> Path:
    from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
    from tests._helpers.sealed_runs import make_project, write_attempt

    make_project(workspace)
    run_dir = write_attempt(workspace, f"runs/{name}", status="failed", attempt=1)
    if frozen:
        (run_dir / RUN_CONFIG_FILENAME).write_text("# " + name + "\n", encoding="utf-8")
    return run_dir


@pytest.mark.parametrize(
    ("ref", "frozen", "message"),
    [
        ("nope", True, "No case named 'nope'"),
        ("case", False, "has no frozen config.toml"),
    ],
)
def test_resume_target_not_found(tmp_path, ref, frozen, message) -> None:
    from hydromodpy.core.exceptions import NothingThereError
    from hydromodpy.project.runner import resume_target

    _failed_case(tmp_path, "case", frozen=frozen)

    with pytest.raises(NothingThereError, match=message):
        resume_target(ref, tmp_path)


def test_calibration_run_cannot_resume(tmp_path) -> None:
    from hydromodpy.project.runner import resume_target
    from hydromodpy.results.record.checks import CalibratedBy
    from tests._helpers.sealed_runs import make_project, seal_run

    make_project(tmp_path)
    seal_run(
        tmp_path,
        "case",
        calibrated_by=CalibratedBy(
            session_id="s" * 32, phase="main", trial=1, session_status="completed"
        ),
    )

    with pytest.raises(ConfigError, match=r"hmp run <file>\.toml --resume"):
        resume_target("case", tmp_path)
