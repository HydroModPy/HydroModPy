"""Build a model step by step in memory, look at it, change it and solve it again.

A ``Lab`` holds a ``Project`` and plays the steps of a run one by one, from
``validate`` to ``run_solver``, on the context of that project. Each step is the
same step object a run plays, so the lab adds no engine and writes no run folder.
The lab keeps the changes asked by ``lab.set`` and the index of the last step it
built. A change makes the first step that reads it stale, and the next
``advance`` or ``solve`` plays again from there. ``lab.force`` replaces an object
of the state the configuration cannot describe, and puts it back each time its
step plays. ``lab.run`` keeps the result as a sealed run of the project, and hands
over the solve of the lab when it is up to date. ``Lab(run)`` opens the project of
a run with the configuration the run kept, and builds it again in memory.
``Lab(dict, base=folder)`` reads the dict as ``Project(dict)`` does, and keeps it as a
draft when a run lacks content. ``lab.set`` completes a draft, and plays all its steps
again. A step refuses to play while a section it reads is missing, and so does a run.
"""

from __future__ import annotations

import copy
import os
import shutil
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.config_kit.base import frozen_copy
from hydromodpy.core.config_kit.written import written_as_a_file, written_payload
from hydromodpy.core.exceptions import CommandUsageError, ConfigError, ConfigMissingError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.run_state import LoadedDataContext
from hydromodpy.core.state.scratch import inherit_run_scratch, scratch_root_for
from hydromodpy.core.toml_io.paths import assign
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.project import phases
from hydromodpy.project.facade import Project
from hydromodpy.project.run_overrides import override_changes

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.catchment.preprocess.catchment_delineation import CatchmentDelineation
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
    from hydromodpy.model.domain.domain import Domain
    from hydromodpy.model.flow import Flow
    from hydromodpy.model.model import Model
    from hydromodpy.project.environment import Environment
    from hydromodpy.results.run.view import Run
    from hydromodpy.solver.base.plan import SimulationPlan, SolverRun

logger = get_logger(__name__)

FILLED_BY: dict[str, str] = {
    "geographic": "build_geographic",
    "domain": "build_geographic",
    "flow": "build_geographic",
    "data": "load_data",
    "mesh": "build_mesh",
    "model": "prepare_solver",
}
"""The step that computes each object of the state a user may force."""


@dataclass(frozen=True)
class LabState:
    """The objects the engine holds, by a stable name. A stale object stays until its step plays."""

    config: HydroModPyConfig  # the configuration of the lab, its changes applied
    geographic: CatchmentDelineation  # contour, DEM, outlet (build_geographic)
    domain: Domain  # top, base, layers, zones (build_geographic)
    flow: Flow  # parameters, boundaries, wells (build_geographic, load_data)
    data: LoadedDataContext  # each loaded data family (load_data)
    mesh: PlanarCellMesh  # the cell mesh (build_mesh)
    model: Model  # what the solver reads, frozen (prepare_solver)
    plan: SimulationPlan  # the solver runs and their order
    solves: Mapping[str, SolverRun]  # one solved run per run of the plan (run_solver)


class Lab:
    """Build, look at, change and solve a model in memory, one step at a time."""

    def __init__(
        self,
        source: str | Path | dict | HydroModPyConfig | Run,
        *,
        base: str | Path | None = None,
        environment: Environment | None = None,
    ) -> None:
        """Open the project of ``source`` and build nothing yet.

        ``source`` may be a run opened by ``hmp.open``, sealed or with its facts. The
        lab opens the project of the run with the configuration the run kept, so
        ``lab.set`` starts from it and ``lab.run`` writes a new run beside it. A mapping is
        read against ``base`` as ``Project(dict)`` does, or kept as a draft when it lacks a section.
        """
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig
        from hydromodpy.results.run.view import Run
        from hydromodpy.workflow.steps.sequence import standard_steps

        self._base, self._environment = base, environment
        self._document = copy.deepcopy(dict(source)) if isinstance(source, Mapping) else None
        if isinstance(source, Run):
            source = HydroModPyConfig.from_snapshot(source.config_snapshot)
        if self._document is None:
            self._project = Project(source, base=base, environment=environment)
        else:
            self._project = self._open(self._document)
        self._steps = standard_steps()
        self._names = [step.name for step in self._steps]
        self._last = self._names.index("run_solver")
        self._built = -1
        self._seconds: dict[str, float] = {}
        self._changes: dict[str, Any] = {}
        self._forced: dict[str, Any] = {}
        # Put on the context once per change: a built flow compares its section by identity.
        self._loaded = False
        # Two labs of one project, or of one process, each work in their own folder.
        root = scratch_root_for(Path(self._project._cfg.workspace.project_root))
        self._scratch_key = f"lab_{uuid.uuid4().hex[:8]}.p{os.getpid()}"
        self._scratch = root / self._scratch_key

    @property
    def project(self) -> Project:
        """The project the lab works on. A calibration or a spin-up goes through it."""
        return self._project

    @property
    def config(self) -> HydroModPyConfig:
        """A frozen copy of the configuration of the project with the changes of the lab."""
        return frozen_copy(self._config_of(self._changes))

    def set(self, changes: Mapping[str, Any] | None = None, /, **named: Any) -> tuple[str, ...]:
        """Change the configuration of the lab and return the built steps that became stale.

        A key is a name of ``hmp config targets`` (``K=5e-5``), a dotted path of the
        TOML (``{"flow.param.K.field.value": 5e-5}``) or a whole section
        (``data={...}``). The new configuration is checked at once. Changes that
        bring the configuration back to the file are forgotten, so a run seals none.
        """
        from hydromodpy.workflow.steps.dependencies import earliest_affected_step

        paths = override_changes(self._config_of(self._changes), {**(changes or {}), **named})
        if self._project._cfg.read_as_draft:
            return self._set_in_the_draft(paths)
        merged = {}
        for path, value in self._changes.items():
            if not any(path == new or path.startswith(f"{new}.") for new in paths):
                merged[path] = value
        merged.update(paths)
        after = written_payload(self._config_of(merged))
        if after == written_payload(self._project._cfg):
            merged = {}
        before = written_payload(self._config_of(self._changes))
        moved = _changed_paths(before, after, "")
        first = earliest_affected_step(moved, self._steps) if moved else len(self._names)
        self._changes = merged
        self._loaded = False
        if self._forced:
            names = ", ".join(self._forced)
            logger.warning("%s stays forced in the lab, so this change does not reach it.", names)
        stale = tuple(self._names[first : self._built + 1])
        self._built = min(self._built, first - 1)
        return stale

    def advance(self, to: str | None = None) -> LabState:
        """Play in memory the steps that are missing or stale, up to ``to`` included.

        Without ``to`` the lab plays the next step. The steps after ``run_solver``
        belong to a run, so ``lab.run`` plays them. A draft is refused while a
        step up to ``to`` reads a section it lacks.
        """
        from hydromodpy.workflow.runner import Pipeline

        target = self._built + 1 if to is None else self._index_of(to)
        if target <= self._built:
            return self.state
        # validate and resolve read the configuration to check it, and build nothing from it.
        for section, detail in self._missing():
            for step in self._steps[self._names.index("build_geographic") : target + 1]:
                if section in step.config_sections:
                    raise ConfigMissingError(
                        f"{step.name} reads [{section}], and the lab does not have it yet. "
                        f"{detail} Add it with lab.set({section}={{...}})."
                    )
        ctx = self._project._ctx
        with inherit_run_scratch(self._scratch_key):
            state = self._first_state(ctx)
            for index in range(self._built + 1, target + 1):
                name = self._names[index]
                ctx.execution.lightweight = index >= self._names.index("setup_process")
                start = time.perf_counter()
                state = Pipeline([self._steps[index]]).run(state)
                self._seconds[name] = time.perf_counter() - start
                for forced in self._forced:
                    if FILLED_BY[forced] == name:
                        _put(ctx, forced, self._forced[forced])
                self._built = index
        ctx.execution.lightweight = False
        phases.adopt_pipeline_phase(self._project, tuple(self._names[: target + 1]))
        return self.state

    @property
    def steps(self) -> pd.DataFrame:
        """One row per step of a run: its status, its last duration in s, what it reads."""
        import pandas as pd

        rows = []
        for index, step in enumerate(self._steps):
            if index <= self._built:
                status = "built"
            elif step.name in self._seconds:
                status = "stale"
            else:
                status = "pending"
            forced = tuple(name for name in self._forced if FILLED_BY[name] == step.name)
            seconds = self._seconds.get(step.name)
            rows.append((step.name, status, seconds, tuple(step.config_sections), forced))
        return pd.DataFrame(rows, columns=["step", "status", "seconds", "sections", "forced"])

    @property
    def state(self) -> LabState:
        """The objects the engine holds now. Reading them computes nothing."""
        ctx = self._project._ctx
        return LabState(
            config=ctx.cfg,
            geographic=ctx.setup.geographic,
            domain=ctx.setup.domain,
            flow=ctx.setup.flow,
            data=ctx.loaded_data,
            mesh=ctx.setup.cell_mesh,
            model=ctx.setup.model,
            plan=ctx.execution.simulation_plan,
            solves=dict(ctx.execution.solver_runs),
        )

    def force(self, name: str, value: object) -> None:
        """Replace the object ``name`` of the state by ``value`` until ``lab.release(name)``.

        The steps after the one that computes it become stale. A run is refused meanwhile.
        """
        if name not in FILLED_BY:
            raise CommandUsageError(
                f"The lab cannot force {name!r}. Force one of {', '.join(FILLED_BY)}."
            )
        self._forced[name] = value
        index = self._names.index(FILLED_BY[name])
        if index <= self._built:
            _put(self._project._ctx, name, value)
            self._built = index

    def release(self, name: str) -> None:
        """Forget the forced value of ``name``, so its step builds it again."""
        if name not in self._forced:
            raise CommandUsageError(f"{name!r} is not forced, so lab.release has nothing to do.")
        del self._forced[name]
        _put(self._project._ctx, name, LoadedDataContext() if name == "data" else None)
        self._built = min(self._built, self._names.index(FILLED_BY[name]) - 1)

    @contextmanager
    def capture(self, *targets: str) -> Iterator[dict[str, list[dict[str, Any]]]]:
        """Record the local variables and the return value of each target as it returns.

        A target is ``"path/file.py:function"`` or ``"path/file.py:Class.method"``,
        the file matched by the end of its path. The block gives a dict that maps
        each target to the list of its calls, each call ``{"locals": ..., "returned": ...}``.
        """
        wanted = [tuple(target.rsplit(":", 1)) for target in targets]
        seen: dict[str, list[dict[str, Any]]] = {target: [] for target in targets}

        def on_event(frame: Any, event: str, value: Any) -> None:
            if event != "return":
                return
            for file, name in wanted:
                if frame.f_code.co_qualname == name and frame.f_code.co_filename.endswith(file):
                    seen[f"{file}:{name}"].append(
                        {"locals": dict(frame.f_locals), "returned": value}
                    )

        previous = sys.getprofile()
        sys.setprofile(on_event)
        try:
            yield seen
        finally:
            sys.setprofile(previous)

    def solve(
        self, built: Mapping[str, SolverRun] | None = None, *, build_only: bool = False
    ) -> dict[str, SolverRun]:
        """Solve the model and return one solved run per run of the plan.

        ``build_only=True`` builds each flow run of the plan without solving it,
        and keeps nothing in the state. ``lab.solve(built)`` then solves these
        runs and keeps them as the result of ``run_solver``. That path plays no
        transport run.
        """
        if build_only:
            self.advance("prepare_solver")
            return _build_flow_runs(self._project._ctx)
        if built is None:
            return dict(self.advance("run_solver").solves)
        if self._built < self._names.index("prepare_solver"):
            raise CommandUsageError("The model changed. Call lab.solve(build_only=True) again.")
        from hydromodpy.solver.base.registry import solvers

        ctx = self._project._ctx
        start = time.perf_counter()
        ctx.execution.solver_runs.clear()
        for run in ctx.execution.simulation_plan.runs:
            if run.id in built:
                adapter = solvers.create(run.process_type, run.solver)
                ctx.execution.solver_runs[run.id] = adapter.run(built[run.id])
        self._seconds["run_solver"] = time.perf_counter() - start
        self._built = self._last
        return dict(self.state.solves)

    def run(self, name: str | None = None, *, until_step: str | None = None) -> Run | None:
        """Keep the model of the lab as a sealed run of the project, as ``simulate`` does.

        The run is the run of the configuration of the lab, so it is refused while
        an object is forced. When ``run_solver`` is built and the configuration
        does not keep solver files, the run takes the solve of the lab instead of solving again. It returns what ``simulate`` returns.
        """
        if self._forced:
            raise CommandUsageError(
                f"{', '.join(self._forced)} is forced in the lab, and a run keeps only what "
                "its configuration says. Call lab.release() on it, or say the change with lab.set()."
            )
        self._refuse_a_draft("run")
        from hydromodpy.calibration.runners.kept_solves import KeptSolve, KeptSolveLauncher

        solves = self._project._ctx.execution.solver_runs
        plan = self._project._ctx.execution.simulation_plan
        launcher = None
        keeps_files = self.config.simulation.results.keep_solver_files
        if (
            not keeps_files
            and self._built == self._last
            and all(run.id in solves for run in plan.runs)
        ):
            # The solve of a lab is no calibration trial, so its id and cost are zero.
            solve = KeptSolve(trial_id=0, cost=0.0, folders=(), results=dict(solves))
            launcher = KeptSolveLauncher(solve)
        self._loaded = False
        try:
            with self._project._run_scratch(name, None):
                return self._project._runner.run(
                    set=self._changes or None, name=name, until_step=until_step, launcher=launcher
                )
        finally:
            # The run cleaned the solver files, so the lab builds and solves them again.
            self._built = min(self._built, self._names.index("prepare_solver") - 1)

    def write_config(self, path: str | Path) -> Path:
        """Write the configuration of the lab, its changes applied, as a TOML file."""
        self._refuse_a_draft("write_config")
        path = Path(path)
        path.write_text(dumps(written_as_a_file(self.config)), encoding="utf-8")
        return path

    def close(self) -> None:
        """Close the project and remove the scratch folder of the lab."""
        self._project.close()
        if self._scratch.exists():
            shutil.rmtree(self._scratch)

    def __enter__(self) -> Lab:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        built = self._names[self._built] if self._built >= 0 else "no step"
        return f"Lab({self._project!r}, built through {built})"

    def _config_of(self, changes: Mapping[str, Any]) -> HydroModPyConfig:
        """Return the configuration of the project with ``changes``, checked."""
        return self._project._cfg.with_changes(changes) if changes else self._project._cfg

    def _first_state(self, ctx: Any) -> Any:
        """Put the configuration of the lab on the context, and return the state of the steps."""
        runner = self._project._runner
        if not self._loaded:
            runner._load_run_context("lab", self._changes)
            self._loaded = True
            for name in self._forced:
                if self._names.index(FILLED_BY[name]) <= self._built:
                    _put(ctx, name, self._forced[name])
        ctx.run_dir = None
        if ctx.setup.workspace is not None:
            # A run moves the solver to its own folder, so the lab takes it back.
            ctx.setup.workspace.solver_scratch_folder = self._scratch
        changes = self._changes or None
        return runner._initial_state(
            "lab", ctx.cfg, True, changes, None, None, None, None, None, None, False
        )

    def _open(self, document: dict[str, Any]) -> Project:
        """Open ``document`` as ``Project(dict)`` does, or as a draft when a section is missing."""
        from hydromodpy.config.loading import load

        base, environment = self._base, self._environment
        try:
            return Project(document, base=base, environment=environment)
        except ConfigError as refused:
            try:
                config = load(document, base, draft=True)
            except ConfigError:
                raise refused from None
            return Project(config, base=base, environment=environment, document=document)

    def _set_in_the_draft(self, paths: Mapping[str, Any]) -> tuple[str, ...]:
        """Read the draft again with ``paths`` set, and make every step play again."""
        document = copy.deepcopy(self._document)
        for path, value in paths.items():
            assign(document, path, value)
        previous, self._project, self._document = self._project, self._open(document), document
        previous.close()
        stale, self._built, self._loaded = tuple(self._names[: self._built + 1]), -1, False
        return stale

    def _missing(self) -> list[tuple[str, str]]:
        """Return each section a run needs and the draft lacks, with what the check says of it."""
        from hydromodpy.config.check import check

        config = self.config
        if not config.read_as_draft:
            return []
        missing = []
        if not config.simulation.has_processes():
            missing.append(("simulation", "[simulation] declares no process to solve."))
        root = Path(config.workspace.project_root)
        for diagnostic in check(written_as_a_file(config), base=root, partial=False):
            if diagnostic.severity == "error":
                missing.append((diagnostic.path.split(".")[0], diagnostic.detail))
        return missing

    def _refuse_a_draft(self, verb: str) -> None:
        """Refuse ``lab.<verb>`` while the draft lacks what a run needs, and list it."""
        missing = self._missing()
        if missing:
            listed = " ".join(detail for _, detail in missing)
            raise ConfigMissingError(
                f"The configuration of the lab is not complete, so lab.{verb} cannot keep it. "
                f"{listed} Add what is missing with lab.set()."
            )

    def _index_of(self, step: str) -> int:
        """Return the index of a step the lab plays, or refuse the name."""
        if step not in self._names[: self._last + 1]:
            played = ", ".join(self._names[: self._last + 1])
            raise CommandUsageError(
                f"The lab plays {played}, and not {step!r}. A step after run_solver belongs "
                "to a run, so call lab.run() to play it."
            )
        return self._names.index(step)


def _put(ctx: Any, name: str, value: object) -> None:
    """Put the forced object ``name`` on the context where its step leaves it."""
    if name == "data":
        ctx.loaded_data = value
    else:
        setattr(ctx.setup, "cell_mesh" if name == "mesh" else name, value)


def _changed_paths(before: Mapping[str, Any], after: Mapping[str, Any], prefix: str) -> list[str]:
    """Return the dotted paths of the values that differ between two TOML documents."""
    paths = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}.{key}" if prefix else key
        old, new = before.get(key), after.get(key)
        if isinstance(old, dict) and isinstance(new, dict):
            paths.extend(_changed_paths(old, new, path))
        elif old != new:
            paths.append(path)
    return paths


def _build_flow_runs(ctx: Any) -> dict[str, SolverRun]:
    """Build each flow run of the plan in its slot, without solving it."""
    from hydromodpy.solver.base.registry import solvers
    from hydromodpy.solver.base.runner import options_for, slot_for, solve_one

    plan = ctx.execution.simulation_plan
    built = {}
    for run in plan.runs:
        if run.process_type == "flow":
            adapter = solvers.create(run.process_type, run.solver)
            options = options_for(adapter, run, ctx.cfg)
            slot = replace(slot_for(plan, run, ctx.setup), stop_before_solve=True)
            built[run.id] = solve_one(adapter, ctx.setup.model, options, slot)
    return built
