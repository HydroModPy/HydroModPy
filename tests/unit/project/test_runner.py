"""A run pays for the steps it asks for, and the Pipeline executes them.

``Project.simulate`` used to build the whole model phase - geographic, data,
mesh - before the Pipeline was even constructed, so ``until_step`` could only
ever make a run *shorter*, never *cheaper*: asking for a catchment outline still
downloaded the forcings and meshed the domain. That eager build is gone: the
Pipeline executes ``build_geographic``, ``load_data`` and ``build_mesh`` itself,
which is what gives each of them a journal row.

One run still builds the model phase up front, and only one: a run whose
overrides patch it, because the plan builder rebuilds the domain and replays the
data binders on a model that must already exist.

Two levels are covered here: the decision itself, through a dry run that
executes no step, and its effect on a real synthetic project run in process.

The runner also hands the Pipeline the state the facade verbs used to read off
the Project, reads a partial run from its directory (no index is opened), keeps
the attempt state of a window that stops before the seal, and closes the
outcome of a run cut by a signal or a crash.
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
from hydromodpy.project.launch.sites.expansion import PlanDraft
from hydromodpy.project.runner import ProjectRunner
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.storage.run_log import run_log_path
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.record.attempt import run_attempt, sealed_run_of
from hydromodpy.workflow.record.journal import WorkflowJournal
from hydromodpy.workflow.state import PipelineState
from tests._helpers.run_stores import facts_of, seal_demo_run
from tests.unit.project._helpers import DEM, PROJECT_TOML, REPO_ROOT

SYNTHETIC_PROJECT = REPO_ROOT / "examples" / "projects" / "00_getting_started" / "project.toml"


def _declared_config(root: Path):
    """The narrow slice of a real configuration a dry run reads."""
    from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.workspace.config import WorkspaceConfig

    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(root), root=str(root)),
        geographic=GeographicConfig(source_mode="synthetic"),
        domain={"depth_model": {"kind": "constant_thickness", "thickness": 50.0}},
    )


class _StubProject:
    """The narrow slice of ``Project`` that a dry run reads."""

    def __init__(self, root: Path, *, model_phase_ready: bool = False) -> None:
        self.built = 0
        self._run_counter = 0
        self._no_display = True
        self._config_path = root / "project.toml"
        # A real configuration, not a namespace: the runner resolves the one
        # this run is defined by before it decides anything, so a double that
        # cannot be copied with an override folded in proves nothing.
        self._cfg = _declared_config(root)
        # All three fields are what ``_is_model_phase_ready`` reads; a double
        # that sets only some of them proves nothing about the ready branch.
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
    """Bind the data workspace to ``root``; the project root is the folder of the file.

    Leaving the data workspace on the repository's own ``examples/`` would point
    the ``data/`` folder of these tests at files the tier shares under xdist and
    must never write.
    """
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
def test_a_bare_resume_names_the_run_the_request_names(
    tmp_path: Path, name: str | None, resume: str | None, named: str
) -> None:
    """A bare resume (``""``) names no run of its own, so the run keeps its name."""
    project = _StubProject(tmp_path)
    project._cfg.simulation.name = "declared"

    assert ProjectRunner(project)._run_name(name, resume) == named  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("until_step", "expected_steps"),
    [("validate", 1), ("resolve", 2), ("build_geographic", 3), ("load_data", 4), ("build_mesh", 5)],
)
def test_a_window_below_the_process_phase_builds_no_model_phase(
    tmp_path: Path,
    until_step: str,
    expected_steps: int,
) -> None:
    """Every head step can be asked for on its own, without the model phase."""
    project = _StubProject(tmp_path)

    draft = _dry_run(project, until_step=until_step)

    assert project.built == 0
    assert draft.steps == STEP_NAMES[:expected_steps]


@pytest.mark.parametrize("until_step", [None, "setup_process", "run_solver", "export"])
def test_a_window_reaching_the_process_phase_leaves_it_to_the_pipeline(
    tmp_path: Path, until_step: str | None
) -> None:
    """No window builds the model phase up front; the Pipeline executes it."""
    project = _StubProject(tmp_path)

    _dry_run(project, until_step=until_step)

    assert project.built == 0


def test_an_already_built_project_reruns_the_head_steps_it_is_asked_for(tmp_path: Path) -> None:
    """A model phase left over from an earlier run does not swallow the window.

    ``_is_model_phase_ready`` skips the Pipeline forward to ``setup_process``.
    Applied to a window that stops before it, that skip would leave the run with
    nothing to execute while still reporting success.
    """
    project = _StubProject(tmp_path, model_phase_ready=True)

    draft = _dry_run(project, until_step="build_geographic")

    assert project.built == 0
    assert draft.steps == STEP_NAMES[:3]


def test_a_model_phase_ready_project_still_skips_forward_on_a_full_run(tmp_path: Path) -> None:
    """The reuse shortcut itself is intact: it is the window that gates it."""
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
def test_a_step_is_only_named(tmp_path: Path, bound: str, word: object, says: str) -> None:
    """An index shifts when a step is inserted, and a class name is no contract."""
    with pytest.raises(ConfigError, match=says):
        _dry_run(_StubProject(tmp_path), **{bound: word})


def test_a_window_that_starts_after_it_ends_is_refused(tmp_path: Path) -> None:
    """``--from build_mesh --until resolve`` executes nothing; say so."""
    with pytest.raises(ConfigError, match="is past until_step"):
        _dry_run(_StubProject(tmp_path), from_step="build_mesh", until_step="resolve")


def test_a_pipeline_without_a_process_step_claims_no_model_phase(tmp_path: Path) -> None:
    """An ad-hoc step list names no ``setup_process``; answer 0, do not raise.

    Index 0 makes every window reach the model phase, which is what the
    canonical pipeline did before the bound existed. Test doubles in
    ``tests/unit/results`` monkeypatch ``standard_steps`` to such a list.
    """
    from hydromodpy.workflow import window as runner_mod
    from hydromodpy.workflow.steps.sequence import standard_steps

    assert runner_mod.model_phase_index(()) == 0
    assert runner_mod.model_phase_index((SimpleNamespace(name="alpha"),)) == 0
    assert runner_mod.model_phase_index(standard_steps()) == 5


def test_a_head_only_window_refuses_to_resume(tmp_path: Path) -> None:
    """A window that writes no journal cannot be resumed from one."""
    with pytest.raises(ConfigError, match="keeps no journal"):
        _dry_run(_StubProject(tmp_path), resume="earlier", until_step="build_geographic")


def test_the_workspace_is_resolved_without_a_built_model_phase(tmp_path: Path) -> None:
    """The declared project root answers when the runtime workspace does not exist."""
    project = _StubProject(tmp_path)

    resolved = ProjectRunner(project)._resolve_workspace_path()  # type: ignore[arg-type]

    assert resolved == tmp_path


def test_delineating_alone_loads_no_data_and_builds_no_mesh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real thing, on the cheapest committed project: the geographic step alone."""
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


def test_the_partial_run_hands_its_work_to_the_next_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the window built stays built: the Project adopts it instead of redoing it.

    Without the adoption the phase marker stays ``"uninitialized"`` while the
    Pipeline has already populated the very ``ctx`` the Project holds, so the
    next call runs ``setup_workspace`` again - documented as resetting
    workspace, geographic and domain - and throws the delineation away.
    """
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


def test_a_partial_run_leaves_the_record_of_a_real_run_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A window that can register no simulation owns no run record.

    ``[simulation] name`` is fixed per config, so a partial run shares the
    run_id of the completed run before it. Writing a truncated manifest under
    that id, and invalidating that id's journal, destroys the record of a run
    that did finish.
    """
    from hydromodpy.project.facade import Project
    from hydromodpy.workflow.record.manifest import ResolvedRunManifest
    from hydromodpy.workflow.state import PipelineState
    from hydromodpy.workflow.steps.sequence import standard_steps

    _isolate_workspace(monkeypatch, tmp_path)

    run_id = "getting_started_dupuit"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    finished = PipelineState(run_id=run_id, step_index=12, step_name="seal", data={})
    ResolvedRunManifest.from_state(finished, standard_steps(), tmp_path).write_atomic(run_dir)
    before = ResolvedRunManifest.read(run_dir)
    assert before is not None and len(before.steps) == 13

    project = Project(SYNTHETIC_PROJECT, headless=True, no_display=True)
    try:
        project.simulate(name=run_id, until_step="build_geographic")
    finally:
        project.close()

    after = ResolvedRunManifest.read(run_dir)
    assert after is not None
    assert after.steps == before.steps, "the partial window rewrote a manifest it does not own"
    assert after.updated_at == before.updated_at
    assert not (run_dir / "outcome.json").exists(), "a head-only window claims no directory"


UNTIL_CASE = "until_extract"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return project


def _runner_of(project: Path, monkeypatch: pytest.MonkeyPatch, *, write_facts: bool):
    """Return a runner whose ``execute`` closes a partial attempt of *UNTIL_CASE*."""
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


def test_a_partial_run_is_read_from_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    runner, owner, sealed = _runner_of(project, monkeypatch, write_facts=True)

    assert effective_status(sealed.run_dir) == "partial"
    run = runner.run(until_step="extract")

    assert run is not None
    assert run.sim_id == sealed.sim_id
    assert run.name == UNTIL_CASE
    assert run.status == "partial"
    assert owner._run_history == [run]


def test_a_partial_run_without_facts_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    runner, owner, _ = _runner_of(project, monkeypatch, write_facts=False)

    assert runner.run(until_step="extract") is None
    assert owner._run_history == []


@pytest.fixture
def captured_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PipelineState:
    """Return the state ``ProjectRunner.run`` hands to the Pipeline."""
    from hydromodpy.project.facade import Project

    config_path = tmp_path / "project.toml"
    config_path.write_text(
        PROJECT_TOML.format(root=tmp_path.as_posix(), dem=DEM.as_posix()),
        encoding="utf-8",
    )

    seen: list[PipelineState] = []

    class _Pipeline:
        def __init__(self, steps, *, workspace, run_dir) -> None:
            self.steps = steps
            self.workspace = workspace
            self.run_dir = run_dir

        def run(
            self, state, *, resume_from=None, parallel=True, model_phase_ready=False, heartbeat=None
        ):
            seen.append(state)
            return state

    monkeypatch.setattr("hydromodpy.workflow.runner.Pipeline", _Pipeline)

    project = Project(config_path, no_display=True)
    project._execute(name="asked_name")

    assert len(seen) == 1
    return seen[0]


def test_the_state_carries_the_declared_mesh_section(captured_state: PipelineState) -> None:
    """``[mesh]`` reaches the step that builds the mesh, through the run configuration."""
    mesh = captured_state.data["cfg"].mesh

    assert mesh is not None, "the pipeline would mesh as if no section were declared"
    assert (mesh.engine, mesh.cell_size) == ("triangle", 350.0)


def test_the_state_carries_the_name_the_caller_asked_for(captured_state: PipelineState) -> None:
    """``step_setup`` derives a name from the config; the caller's name wins.

    ``[simulation] name`` says ``declared_name`` here and the caller asked for
    ``asked_name``. Letting the config win would register the run under a name
    its journal does not carry.
    """
    assert captured_state.data["run_name"] == "asked_name"
    assert captured_state.run_id == "asked_name"


LAST_WORDS = "stress period 51: the solver is about to give up"


@pytest.mark.parametrize(
    ("signal_error", "status", "number"),
    [
        (KeyboardInterrupt, "aborted", int(signal.SIGINT)),
        (TerminationRequested, "aborted", int(signal.SIGTERM)),
        (RuntimeError, "failed", None),
    ],
)
def test_an_interrupted_run_closes_its_outcome(
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
    """A pipeline double that journals its first step for real and records what it was asked."""

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


def test_a_window_that_stops_before_the_seal_keeps_its_attempt_state_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


# --- The claim comes first, and what the attempt asks for is told once it has it ---


class _Claimed:
    """A real claimed attempt in a real project, with the data layer and the keys doubled."""

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
    """Leave a completed run of *name* that answers the key *key*."""
    import hydromodpy.results.storage.sealing as sealing
    import hydromodpy.workflow.replay_checks as replay_checks

    run_dir, _ = seal_demo_run(root, name)
    monkeypatch.setattr(
        sealing, "sealed_solution_key", lambda directory: key if directory == run_dir else None
    )
    monkeypatch.setattr(replay_checks, "api_inputs_intact", lambda directory, project: True)
    return run_dir


def test_the_claim_writes_the_request_then_the_request_id_into_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)

    with claimed.attempt("demo") as handle:
        key, identical = claimed.claim(handle)
        run_dir = handle.run_dir

    assert (key, identical) == ("key:rid-1", None)
    assert claimed.ctx.inputs == "RESOLVED"
    assert read_outcome(run_dir).request_id == "rid-1"
    assert (run_dir / "request.json").is_file(), "a request given as a mapping is written whole"
    assert (run_dir / "config.toml").is_file()
    assert claimed.written == ["demo"]


def test_a_request_given_as_a_built_configuration_writes_no_request_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)

    with claimed.attempt("demo") as handle:
        claimed.claim(handle, form_of="object")
        run_dir = handle.run_dir

    assert not (run_dir / "request.json").exists()
    assert (run_dir / "config.toml").is_file()


def test_a_run_identical_to_a_completed_one_undoes_its_claim_and_gives_that_run_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_a_run_that_may_not_be_skipped_keeps_its_claim_beside_an_identical_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)
    _identical(monkeypatch, claimed.root, "key:rid-1")

    with claimed.attempt("demo") as handle:
        _, identical = claimed.claim(handle, skip=False)
        run_dir = handle.run_dir

    assert identical is None
    assert run_dir.name == "demo.v2"
    assert read_outcome(run_dir).status == "completed"


def test_a_run_that_is_forced_computes_beside_an_identical_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)
    _identical(monkeypatch, claimed.root, "key:rid-1")

    with claimed.attempt("demo") as handle:
        _, identical = claimed.claim(handle, force=True)

    assert identical is None


def test_if_exists_fail_is_read_after_the_search_for_an_identical_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_if_exists_fail_takes_a_name_nobody_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = _Claimed(tmp_path, monkeypatch, if_exists="fail")

    with claimed.attempt("demo") as handle:
        _, identical = claimed.claim(handle)
        run_dir = handle.run_dir

    assert identical is None
    assert run_dir.name == "demo"


def test_a_retry_that_asks_for_something_else_starts_over_and_keeps_its_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_a_retry_that_asks_the_same_thing_resumes_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = _Claimed(tmp_path, monkeypatch)
    claimed.requests = iter(["same", "same"])
    with pytest.raises(RuntimeError, match="boom"), claimed.attempt("demo") as handle:
        claimed.claim(handle)
        (handle.run_dir / "partial.dat").write_text("x")
        raise RuntimeError("boom")

    with claimed.attempt("demo") as handle:
        claimed.claim(handle)
        run_dir = handle.run_dir

    assert (run_dir / "partial.dat").is_file()
    assert read_outcome(run_dir).attempt == 2


def test_a_resume_asked_on_a_request_that_changed_is_refused_and_gives_the_stop_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_a_resume_asked_on_the_same_request_continues_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_the_state_a_window_starts_from_enters_the_request_id_by_its_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_a_failed_resolution_leaves_the_outcome_of_a_claimed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim precedes the inputs, so a download that fails is told by ``status``."""
    import hydromodpy.data.loading.inputs as inputs

    claimed = _Claimed(tmp_path, monkeypatch)

    def refuse(cfg, **kwargs):
        raise ConfigError("no network")

    monkeypatch.setattr(inputs, "resolve_inputs", refuse)
    with pytest.raises(ConfigError, match="no network"), claimed.attempt("demo") as handle:
        claimed.claim(handle)

    outcome = read_outcome(claimed.root / "runs" / "demo")
    assert outcome is not None and outcome.status == "failed"


def test_the_request_of_a_project_carries_its_document_and_refuses_a_name_that_breaks_the_rule(
    tmp_path: Path,
) -> None:
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
