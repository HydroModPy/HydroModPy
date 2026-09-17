"""A partial run pays for the steps it asks for, and for nothing else.

``Project.simulate`` used to build the whole model phase - geographic, data,
mesh - before the Pipeline was even constructed, so ``until_step`` could only
ever make a run *shorter*, never *cheaper*: asking for a catchment outline still
downloaded the forcings and meshed the domain. The eager build now happens only
when the requested window reaches ``setup_process``, the first step that
consumes the shared model phase.

Two levels are covered here: the decision itself, through a dry run that
executes no step, and its effect on a real synthetic project run in process.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.project.runner import ProjectRunner

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_PROJECT = REPO_ROOT / "examples" / "projects" / "00_getting_started" / "project.toml"


class _StubProject:
    """The narrow slice of ``Project`` that a dry run reads."""

    def __init__(self, root: Path, *, model_phase_ready: bool = False) -> None:
        self.built = 0
        self._run_counter = 0
        self._no_display = True
        self._config_path = root / "project.toml"
        self._cfg = SimpleNamespace(workspace=SimpleNamespace(project_root=root))
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


def _dry_run(project: _StubProject, **kwargs) -> None:
    ProjectRunner(project).run(dry_run=True, **kwargs)  # type: ignore[arg-type]


def _isolate_workspace(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Bind project root and data workspace to ``root``.

    Both are needed: leaving the data workspace on the repository's own
    ``examples/`` makes these tests take the lock on the shared
    ``cache.duckdb``, which deadlocks the tier under xdist.
    """
    monkeypatch.setenv("HMP_PROJECT_ROOT", str(root))
    monkeypatch.setenv("HMP_WORKSPACE", str(root))
    monkeypatch.setenv("MPLBACKEND", "Agg")


@pytest.mark.parametrize(
    ("until_step", "expected_steps"),
    [("validate", 1), ("resolve", 2), ("build_geographic", 3), ("load_data", 4), ("build_mesh", 5)],
)
def test_a_window_below_the_process_phase_builds_no_model_phase(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    until_step: str,
    expected_steps: int,
) -> None:
    """Every head step can be asked for on its own, without the model phase."""
    project = _StubProject(tmp_path)

    _dry_run(project, until_step=until_step)

    assert project.built == 0
    plan = capsys.readouterr().out
    assert "resume_from" not in plan
    assert len([line for line in plan.splitlines() if line.startswith("  ")]) == expected_steps


@pytest.mark.parametrize("until_step", [None, "setup_process", "run_solver", "export", 11])
def test_a_window_reaching_the_process_phase_still_builds_it(
    tmp_path: Path, until_step: str | int | None
) -> None:
    """The reuse path is untouched: anything that consumes the model phase gets it."""
    project = _StubProject(tmp_path)

    _dry_run(project, until_step=until_step)

    assert project.built == 1


def test_an_already_built_project_reruns_the_head_steps_it_is_asked_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A model phase left over from an earlier run does not swallow the window.

    ``_is_model_phase_ready`` skips the Pipeline forward to ``setup_process``.
    Applied to a window that stops before it, that skip would leave the run with
    nothing to execute while still reporting success.
    """
    project = _StubProject(tmp_path, model_phase_ready=True)

    _dry_run(project, until_step="build_geographic")

    assert project.built == 0
    assert "resume_from" not in capsys.readouterr().out


def test_a_model_phase_ready_project_still_skips_forward_on_a_full_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reuse shortcut itself is intact: it is the window that gates it."""
    project = _StubProject(tmp_path, model_phase_ready=True)

    _dry_run(project, until_step=None)

    assert "resume_from: 5" in capsys.readouterr().out


@pytest.mark.parametrize("bound", ["until_step", "from_step"])
def test_a_step_outside_the_pipeline_is_refused(tmp_path: Path, bound: str) -> None:
    """An index past either end names no step, and no longer runs an empty plan."""
    for out_of_range in (-1, 12, 99):
        with pytest.raises(ConfigError, match="outside the"):
            _dry_run(_StubProject(tmp_path), **{bound: out_of_range})


def test_a_window_that_starts_after_it_ends_is_refused(tmp_path: Path) -> None:
    """``--from build_mesh --until resolve`` executes nothing; say so."""
    with pytest.raises(ConfigError, match="the window is empty"):
        _dry_run(_StubProject(tmp_path), from_step="build_mesh", until_step="resolve")


def test_a_pipeline_without_a_process_step_claims_no_model_phase(tmp_path: Path) -> None:
    """An ad-hoc step list names no ``setup_process``; answer 0, do not raise.

    Index 0 makes every window reach the model phase, which is what the
    canonical pipeline did before the bound existed. Test doubles in
    ``tests/unit/simulation`` monkeypatch ``standard_steps`` to such a list.
    """
    from hydromodpy.project import runner as runner_mod
    from hydromodpy.workflow.orchestrator import standard_steps

    assert runner_mod._model_phase_index(()) == 0
    assert runner_mod._model_phase_index((SimpleNamespace(name="alpha"),)) == 0
    assert runner_mod._model_phase_index(standard_steps()) == 5


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
        assert setup.mesh_bundle is None, "build_mesh ran although the window excluded it"
        assert setup.mesh_planar is None
        assert project._ctx.loaded_data.loaded_plan_types is None, "load_data ran unasked"
    finally:
        project.close()


def test_the_partial_run_hands_its_work_to_the_next_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
        capsys.readouterr()
        project.simulate(dry_run=True)

        assert project._ctx.setup.geographic is delineated, "the delineation was thrown away"
        assert "resume_from: 5" in capsys.readouterr().out
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
    from hydromodpy.workflow.internals.manifest import ResolvedRunManifest
    from hydromodpy.workflow.internals.state import PipelineState
    from hydromodpy.workflow.orchestrator import standard_steps

    _isolate_workspace(monkeypatch, tmp_path)

    run_id = "getting_started_dupuit"
    finished = PipelineState(run_id=run_id, step_index=11, step_name="export", data={})
    ResolvedRunManifest.from_state(finished, standard_steps(), tmp_path).write_atomic(tmp_path)
    before = ResolvedRunManifest.read(tmp_path, run_id)
    assert before is not None and len(before.steps) == 12

    project = Project(SYNTHETIC_PROJECT, headless=True, no_display=True)
    try:
        project.simulate(name=run_id, until_step="build_geographic")
    finally:
        project.close()

    after = ResolvedRunManifest.read(tmp_path, run_id)
    assert after is not None
    assert after.steps == before.steps, "the partial window rewrote a manifest it does not own"
    assert after.updated_at == before.updated_at
