"""The fifteen public verbs of HydroModPy, the ones ``hydromodpy`` and ``hmp`` expose.

Each verb resolves its source or its reference, calls the function of the
package that does the work, and returns a typed value. A parameter is text, a
number, a boolean, a path, a mapping or a sequence of those, plus three Python
conveniences: a :class:`~hydromodpy.config.hydromodpy_config.HydroModPyConfig` or a
:class:`~hydromodpy.project.request.RunRequest` as a source, the object itself
as a reference, and the :class:`~hydromodpy.project.environment.Environment`
a server builds. A value returned carries ``to_dict()``, or is a path, a list
of paths or a list of diagnostics, so a server sends it as JSON.

A reference (``Ref``) is a directory, a name read in ``workspace``, or the
object itself. The library never looks for a project above the working
directory: with ``workspace=None`` a reference is a path. The command line
passes ``-w``, or the project of its working directory.

The module imports at its top the five objects its signatures take and return,
which the facade reads here, and everything else inside the verbs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, overload

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.config.loading import MEMORY_NEEDS_BASE
from hydromodpy.core.diagnostic import Diagnostic
from hydromodpy.core.exceptions import CommandUsageError, ConfigError, NothingThereError
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, SESSIONS_DIRNAME
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.project.check_source import check_document, check_file
from hydromodpy.project.environment import Environment
from hydromodpy.project.facade import Project
from hydromodpy.project.launch.plan import PlanDraft
from hydromodpy.project.request import (
    RunOutcome,
    RunRequest,
    held,
    is_a_path,
    refuse_a_calibration,
    refuse_a_sites_project,
    report_identical_run,
)
from hydromodpy.project.show import ShowWhat, render, shown
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.run.view import Run
from hydromodpy.results.session.view import Session

if TYPE_CHECKING:
    import pandas as pd
    import xarray as xr
    from matplotlib.figure import Figure

    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.model.initial_config import SpinupConfig
    from hydromodpy.project.accessors import Workspace
    from hydromodpy.project.calibrate import CalibrationPlan
    from hydromodpy.project.compare import Comparison
    from hydromodpy.project.doctor import DoctorReport
    from hydromodpy.project.examples.install import InstallReport
    from hydromodpy.project.examples.manifest import ExampleEntry
    from hydromodpy.project.launch.status import StatusReport
    from hydromodpy.project.spinup import SpinupResult
    from hydromodpy.results.export.publish import PublishedProject
    from hydromodpy.results.publication import PublishedLine
    from hydromodpy.workflow.overview import OverviewResult

PathLike = str | os.PathLike[str]
"""A file or a folder, as text or as a path object."""

Source = PathLike | Mapping[str, Any] | HydroModPyConfig | RunRequest
"""A configuration: a TOML or JSON path, a document as a mapping, JSON text, the
validated object, or a run request."""

Ref = PathLike | Run | Session | RunSet | Project
"""A run, a session, a set of runs or a project: a directory, a name read in
``workspace``, or the object itself."""

__all__ = [
    "open",
    "run",
    "check",
    "calibrate",
    "spinup",
    "replay",
    "stop",
    "status",
    "trash",
    "compare",
    "show",
    "export",
    "publish",
    "example",
    "doctor",
]


def open(path: PathLike) -> Project | Run | Session | Workspace:
    """Open what a path stands for: a project, a run, a session or a workspace.

    - a project directory, its ``project.toml`` or any folder inside it gives a
      :class:`~hydromodpy.project.facade.Project`, read only;
    - a sealed run directory (``runs/<name>`` or a kept trial) gives a
      :class:`~hydromodpy.results.run.view.Run` read from its own files;
    - a session directory (``sessions/<name>``) gives a
      :class:`~hydromodpy.results.session.view.Session`;
    - a workspace root (``workspace.toml`` or ``projects/``) gives a
      :class:`~hydromodpy.project.accessors.Workspace`.

    A run and a session are given :func:`hydromodpy.project.show.render`, so
    ``run.figure(name)`` draws. They are opened by
    ``open_run_dir(path, *, read_config, render)`` and
    ``Session(path, *, read_config, render)``.

    Parameters
    ----------
    path
        The directory or file.

    Returns
    -------
    Project or Run or Session or Workspace
        What the path stands for.

    Raises
    ------
    FileNotFoundError
        If the path does not exist, or stands for none of the above.
    hydromodpy.results.errors.RunNotSealedError
        If the path is a run directory that never completed.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> proj = hmp.open("~/ws/projects/bretagne_k")  # doctest: +SKIP
    >>> run = hmp.open("~/ws/projects/bretagne_k/runs/J0014010-base")  # doctest: +SKIP
    """
    from hydromodpy.core.state.layout import is_workspace_root, runs_dir_for, sessions_dir_for
    from hydromodpy.project.accessors import Workspace
    from hydromodpy.project.facade import open_project, read_sealed_config
    from hydromodpy.results.run.view import open_run_dir
    from hydromodpy.results.session.descriptor import session_descriptor_path
    from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME

    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist")
    if target.is_dir():
        # A session carries an outcome.json of its own, so it is told first.
        if session_descriptor_path(target).is_file():
            return Session(target, read_config=read_sealed_config, render=render)
        holds_a_run = any(
            (target / name).is_file() for name in (RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME)
        )
        if holds_a_run:
            # A run copied out of its project reads from its own seal and files.
            return open_run_dir(target, read_config=read_sealed_config, render=render)
        if not (target / PROJECT_MARKER_FILENAME).is_file() and is_workspace_root(target):
            return Workspace(target)
    root = resolve_project_root(target.parent if target.is_file() else target)
    anchors = (root / PROJECT_MARKER_FILENAME, runs_dir_for(root), sessions_dir_for(root))
    if not any(anchor.exists() for anchor in anchors):
        raise FileNotFoundError(
            f"{target} is no project (no {PROJECT_MARKER_FILENAME} at or above it), no run, "
            "no session and no workspace." + _projects_hint(target)
        )
    return open_project(root)


def run(
    source: Source,
    *,
    base: PathLike | None = None,
    set: Mapping[str, Any] | None = None,  # noqa: A002 - the name of `--set`
    name: str | None = None,
    force: bool = False,
    fresh: bool = False,
    resume: str | None = None,
    from_step: str | None = None,
    until_step: str | None = None,
    dry_run: bool = False,
    frozen: bool = False,
    no_display: bool = False,
    headless: bool = False,
    environment: Environment | None = None,
) -> RunOutcome | PlanDraft | OverviewResult | None:
    """Run a simulation or an overview.

    What comes back follows the workflow of the configuration:

    - a simulation gives its :class:`~hydromodpy.project.request.RunOutcome`,
      whose ``open()`` gives the run, or ``None`` when no directory was claimed;
    - an overview gives a :class:`~hydromodpy.workflow.overview.OverviewResult`;
    - ``dry_run=True`` gives a :class:`~hydromodpy.project.launch.plan.PlanDraft`,
      with nothing run and nothing written.

    A calibration is refused, :func:`calibrate` runs it. A ``[sites]`` project
    is refused too, ``Project.launch`` runs it. A simulation identical to a
    completed run of the project (same resolved configuration, same name) is
    not computed again: its outcome names the completed run in
    ``identical_to`` and a warning says so. ``force=True`` computes it anyway.

    Parameters
    ----------
    source
        A TOML file, a JSON run request, a document as a mapping or JSON text,
        a :class:`~hydromodpy.config.hydromodpy_config.HydroModPyConfig`, or a
        :class:`~hydromodpy.project.request.RunRequest`.
    base
        The folder the relative paths of the document are read from, and the
        project the run is written in. A file reads them from the project root
        above it. A mapping, JSON text or a request object is refused without one.
    set
        Changes of the configuration, by dotted path (``--set``) or by a name
        of ``hmp config targets``. Sealed in ``lineage.overrides``.
    name
        Name of the run.
    force
        Compute a run identical to a completed one, and claim a stale case.
    fresh
        File what a previous attempt left under ``attempts/<k>/`` and start over.
    resume
        Name of an interrupted case to continue in place, ``<chain>_w<N>`` for a
        window of a chain.
    from_step, until_step
        Bounds of a partial run, names of pipeline steps.
    dry_run
        Say what this configuration would run, and run nothing.
    frozen
        Require frozen input data references: a project TOML answers to its
        lockfile, the ``config.toml`` of a run to the record of that run.
    no_display, headless
        Draw no figure. Neither enters the identity of the run.
    environment
        The environment of the call. ``None`` builds the default of the machine.

    Returns
    -------
    RunOutcome or PlanDraft or OverviewResult or None
        See above.

    Raises
    ------
    FileNotFoundError
        If the TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the document fails validation, declares a calibration or a
        ``[sites]`` project, takes an option its workflow refuses, or comes in
        memory without ``base``.
    hydromodpy.core.exceptions.PipelineError
        If a step raises.
    hydromodpy.core.exceptions.SolverError
        If the solver fails.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> outcome = hmp.run("run_transient_nwt.toml", name="baseline")  # doctest: +SKIP
    >>> run = outcome.open()  # doctest: +SKIP
    >>> plan = hmp.run("run_transient_nwt.toml", dry_run=True)  # doctest: +SKIP
    """
    from hydromodpy.config.loading import REQUEST_SUFFIX
    from hydromodpy.config.sites import is_sites_project
    from hydromodpy.project.dispatch.workflow import (
        draft_of_a_file_or_config,
        run_overview,
        run_simulation,
    )
    from hydromodpy.project.request import (
        _refuse_combinations,
        base_of,
        read_request,
        request_of,
        workflow_of,
    )

    is_path = is_a_path(source)
    given = Path(source).expanduser().resolve() if is_path else source
    # The request is read once, whatever the workflow, as a draft with no option
    # refused: this verb tells in its own words what a workflow does not take.
    request = request_of(
        given,
        base=base,
        set=set,
        name=name,
        force=force,
        fresh=fresh,
        resume=resume,
        from_step=from_step,
        until_step=until_step,
        frozen=frozen,
        no_display=no_display,
        headless=headless,
        dry_run=True,
    )
    workflow = workflow_of(request)
    run_base = base_of(given, base)
    file = given if is_path else None
    # A request object or a request in JSON may ask for a dry run itself.
    if isinstance(source, RunRequest):
        dry_run = dry_run or source.dry_run
    elif file is not None and file.suffix == REQUEST_SUFFIX:
        dry_run = dry_run or read_request(file).dry_run

    if workflow == "calibration":
        refuse_a_calibration(file.name if file is not None else "This configuration")
    if dry_run:
        document = held(source, base)
        changes = set
        if isinstance(document, RunRequest):
            document, changes = document.config, {**document.set, **(set or {})}
        return draft_of_a_file_or_config(
            given if is_path else document,
            workflow=workflow,
            base=base,
            set_changes=changes,
            name=request.name,
            resume=request.resume,
            from_step=request.from_step,
            until_step=request.until_step,
        )
    request = request.model_copy(update={"dry_run": False})
    if is_sites_project(request.config):
        refuse_a_sites_project(file)
    if workflow == "overview":
        asked = {
            "set": request.set,
            "name": request.name,
            "force": request.force,
            "fresh": request.fresh,
            "resume": request.resume,
            "from_step": request.from_step,
            "until_step": request.until_step,
            "frozen": request.frozen,
        }
        written = sorted(key for key, value in asked.items() if value)
        if written:
            raise ConfigError(
                f"An overview takes none of {', '.join(written)}: they steer a simulation."
            )
        return run_overview(request, base=run_base, environment=environment)

    _refuse_combinations(request)
    outcome = run_simulation(request, base=run_base, environment=environment)
    if outcome is None:
        return None
    if outcome.sim_id:
        from hydromodpy.results.catalog.indexer import index_after_run

        # The worker never opens the index; it is brought up to date here, for
        # the readers that list runs.
        index_after_run(outcome.project_root)
    if outcome.identical_to is not None:
        report_identical_run(outcome.identical_to, str(outcome.sim_id))
    return outcome


def check(
    source: PathLike | Mapping[str, Any],
    *,
    base: PathLike | None = None,
    partial: bool = True,
    inputs: bool = False,
    environment: Environment | None = None,
) -> list[Diagnostic]:
    """Check a configuration, a draft or a file, and return every diagnostic it holds.

    A mapping is checked as it stands, as a form being filled would be, against
    the ``base`` its relative paths are read from: a mapping without one is
    refused, as :func:`~hydromodpy.config.loading.load` refuses it. A path is
    read as ``hmp run`` reads it: the ``base_config`` chain, the project root,
    the name of the workflow. A ``[sites]`` project is expanded case by case,
    and each issue comes back at the key it reaches. A calibration with nothing
    to fix and nothing to fill is also read by its preflight.

    Parameters
    ----------
    source
        A path to a TOML file, or the document as a mapping of sections.
    base
        The folder relative paths are read from. A mapping needs it.
    partial
        True reports a required key not written yet as ``to_fill``, which stops
        nothing. False reports it as an ``error``, what ``hmp run`` refuses.
    inputs
        True also reads the header of each input file the document names, and
        downloads nothing.
    environment
        The bounds an input header may be read within. The default is the
        bounds of a bare ``Environment``.

    Returns
    -------
    list of Diagnostic
        Empty when the document loads and every rule passes. A diagnostic of a
        file carries ``line_number``.

    Raises
    ------
    TypeError
        When *source* is neither a mapping nor a path.
    """
    if not isinstance(source, (str, os.PathLike, Mapping)):
        raise TypeError(
            f"check takes a path or a mapping of sections, not {type(source).__name__}."
        )
    bounds = (environment or Environment()).bounds
    folder = None if base is None else Path(base).expanduser().resolve()
    try:
        if isinstance(source, Mapping):
            if folder is None:
                return [
                    Diagnostic(
                        path="", code="refused_value", severity="error", detail=MEMORY_NEEDS_BASE
                    )
                ]
            return check_document(
                source, partial=partial, inputs=inputs, base=folder, bounds=bounds
            )
        return check_file(
            Path(source).expanduser().resolve(),
            partial=partial,
            inputs=inputs,
            bounds=bounds,
            base=folder,
        )
    except Exception as exc:  # noqa: BLE001 - a check reports, an unexpected error is a finding too
        return [
            Diagnostic(
                path="",
                code="refused_value",
                severity="error",
                detail=f"Config check failed: {exc}",
            )
        ]


def calibrate(
    source: Source,
    *,
    base: PathLike | None = None,
    phase: str | None = None,
    dry_run: bool = False,
    preflight: bool = True,
    case: str | None = None,
    method: str | None = None,
    max_trials: int | None = None,
    seed: int | None = None,
    save_runs: str | None = None,
    objective: str | None = None,
    project: str | None = None,
    workspace: PathLike | None = None,
    resume: bool = False,
    force: bool = False,
    report: bool = True,
    headless: bool = True,
    environment: Environment | None = None,
) -> CalibrationReport | CalibrationPlan:
    """Run the calibration a configuration declares, or say what it would run.

    A path with no ``base`` goes to ``calibrate_a_file`` and builds no project.
    A document in memory, or a path read against ``base``, opens a
    :class:`~hydromodpy.project.facade.Project` and runs
    ``Project.calibrate``. A configuration that declares
    ``[[calibration.phases]]`` runs each phase in turn. A script that
    calibrates with ``parallel`` above 1 needs the ``if __name__ ==
    "__main__":`` guard, because the workers start in spawn.

    ``dry_run=True`` runs nothing and writes nothing: it returns the
    :class:`~hydromodpy.project.calibrate.CalibrationPlan` of
    ``calibration_plan(source, *, workspace=None, check=False) -> CalibrationPlan``,
    whose ``phases``, ``calibration``, ``protocol`` and ``plan`` say what the
    configuration declares and what a launch would write.

    Parameters
    ----------
    source
        A calibration TOML file, a document as a mapping or JSON text, or a
        validated :class:`~hydromodpy.config.hydromodpy_config.HydroModPyConfig`.
    base
        The folder the relative paths of the document are read from, and the
        project the sessions are written in.
    phase
        Run only the named phase of a staged calibration.
    dry_run
        Say what would run, and run nothing.
    preflight
        With ``dry_run``, run first the checks a launch runs, so a file they
        refuse raises. False reads the declaration only.
    case
        Name of the session of a calibration held in memory. A file names its
        case with ``[simulation] name``.
    method, max_trials, seed, save_runs
        The search of a calibration held in memory, over its ``[calibration]``.
    objective
        Name of the objective block to optimize.
    project
        Label of the project in the session record.
    workspace
        The project root a file calibration writes in, over the folder of the file.
    resume
        Continue an interrupted session.
    force
        Run again a session identical to a completed one.
    report
        Write the report of each session once the search is over.
    headless
        Draw no figure while the calibration runs.
    environment
        The environment of the call. ``None`` builds the default of the machine.

    Returns
    -------
    CalibrationReport or CalibrationPlan
        What the calibration found, or with ``dry_run`` what it would run.

    Raises
    ------
    FileNotFoundError
        If the calibration TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the configuration cannot be read, the preflight refuses it, or an
        option of a calibration held in memory is given for a file.
    hydromodpy.core.exceptions.CalibrationError
        If a phase is unknown, or the search fails.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> report = hmp.calibrate("calibration.toml")  # doctest: +SKIP
    >>> plan = hmp.calibrate("calibration.toml", dry_run=True)  # doctest: +SKIP
    """
    from hydromodpy.core.exceptions import CalibrationError
    from hydromodpy.project.dispatch.workflow import no_such_phase

    in_memory = {
        "case": case,
        "method": method,
        "max_trials": max_trials,
        "seed": seed,
        "save_runs": save_runs,
    }
    from_a_file = is_a_path(source) and base is None
    if dry_run:
        from hydromodpy.project.calibrate import calibration_plan

        target = Path(source).expanduser().resolve() if from_a_file else held(source, base)
        root = None if workspace is None else Path(workspace).expanduser().resolve()
        plan = calibration_plan(target, workspace=root, check=preflight)
        declared = [item.get("name") for item in plan.phases]
        if phase is not None and phase not in declared:
            raise CalibrationError(f"unknown phase {phase!r}; the calibration declares {declared}.")
        return plan
    if from_a_file:
        from hydromodpy.project.calibrate import calibrate_a_file

        given = sorted(key for key, value in in_memory.items() if value is not None)
        if given:
            raise ConfigError(
                f"{', '.join(given)} steer a calibration held in memory; a file writes "
                "them in its [calibration] section and names its case with "
                "[simulation] name."
            )
        return calibrate_a_file(
            source,
            phase=phase,
            workspace=workspace,
            project=project,
            objective=objective,
            resume=resume,
            force=force,
            environment=environment,
            report=report,
        )

    config = held(source, base)
    section = getattr(config, "calibration", None)
    if not getattr(section, "phases", None) and phase is not None:
        raise CalibrationError(no_such_phase("this configuration", phase))
    options: dict[str, Any] = {key: value for key, value in in_memory.items() if value is not None}
    options.update(
        {
            key: value
            for key, value in {
                "phase": phase,
                "objective": objective,
                "project": project,
                "workspace": workspace,
            }.items()
            if value is not None
        }
    )
    if resume:
        options["resume"] = True
    if force:
        options["force"] = True
    if not report:
        options["report"] = False
    with Project(config, headless=headless, environment=environment) as opened:
        return opened.calibrate(**options)


def spinup(
    source: Source,
    *,
    base: PathLike | None = None,
    spinup: SpinupConfig | Mapping[str, Any] | None = None,
    name_prefix: str = "spinup",
    then_run: bool = False,
    headless: bool = True,
    environment: Environment | None = None,
) -> SpinupResult:
    """Run a cyclic spin-up, and a production run from its state when asked.

    Repeats the representative window (``[spinup] window_*``, else
    ``[simulation.time]``), each cycle from the state of the one before, until
    the heads and the lake stage converge. One project is kept so the mesh is
    the same across cycles.

    Parameters
    ----------
    source
        A TOML file, a document as a mapping or JSON text, or a validated
        :class:`~hydromodpy.config.hydromodpy_config.HydroModPyConfig`.
    base
        The folder the relative paths of the document are read from.
    spinup
        Settings that replace the ``[spinup]`` section, as a mapping or as a
        :class:`~hydromodpy.model.initial_config.SpinupConfig`.
    name_prefix
        Prefix of the run name of each cycle.
    then_run
        Chain a production run from the converged state, over ``[simulation.time]``.
    headless
        Draw no figure.
    environment
        The environment of the call. ``None`` builds the default of the machine.

    Returns
    -------
    SpinupResult
        The outcome of the loop, ``restart_from`` included, and the ``sim_id``
        of the production run when one was chained.
    """
    import copy
    import dataclasses

    from hydromodpy.model.initial_config import SpinupConfig
    from hydromodpy.project.spinup import run_spinup
    from hydromodpy.results.storage.run_log import project_log

    settings = SpinupConfig.model_validate(spinup) if isinstance(spinup, Mapping) else spinup
    loaded = held(source, base)
    if isinstance(loaded, Path) and loaded.is_file():
        from hydromodpy.config.sites import is_sites_project
        from hydromodpy.workflow.dispatch import load_raw_toml

        if is_sites_project(load_raw_toml(loaded)):
            refuse_a_sites_project(loaded)

    # A clean production configuration, taken before the spin-up changes the
    # model (cycle window, restart_from, initial condition).
    production_config = None
    if then_run:
        if isinstance(loaded, Path):
            from hydromodpy.config.loading import load

            production_config = load(loaded)
        else:
            production_config = copy.deepcopy(loaded)

    with (
        Project(loaded, headless=headless, no_display=True, environment=environment) as opened,
        project_log(opened.root),
    ):
        result = run_spinup(opened, spinup=settings, name_prefix=name_prefix)

    if not then_run or not result.restart_from:
        return result

    # A generated mesh is read back from the product store, so the production
    # run reproduces the spin-up mesh.
    warning = result.antecedent_warning()
    if warning is not None:
        from hydromodpy.core.logging import get_logger

        get_logger(__name__).warning("chaining a production run: %s", warning)
    production_config.flow.restart_from = result.restart_from
    production = run(production_config, headless=headless, environment=environment)
    return dataclasses.replace(result, production_sim_id=getattr(production, "sim_id", None))


def replay(
    ref: Ref,
    *,
    workspace: PathLike | None = None,
    strict: bool = False,
    environment: Environment | None = None,
) -> RunOutcome:
    """Play a sealed run, or a published copy, again, and class the values it computes.

    Parameters
    ----------
    ref
        The run directory or copy, a run named in ``workspace``, or the run.
    workspace
        The project the replay is written in. A copy outside any project needs it.
    strict
        Refuse a replay whose values are not equal to the bit.
    environment
        The environment of the call. ``None`` builds the default of the machine.

    Returns
    -------
    RunOutcome
        The outcome of the directory the replay wrote.

    Raises
    ------
    hydromodpy.core.exceptions.ConfigError
        If the reference is no sealed run, or a copy that carries no inputs.
    """
    from hydromodpy.project.replay import replay as play_again

    target: PathLike = ref.dir if isinstance(ref, Run) else _path_of(ref, workspace)
    base = None if workspace is None else Path(workspace).expanduser().resolve()
    played = play_again(target, strict=strict, base=base, environment=environment)
    return RunOutcome.read(played.dir, project_root=_project_of(played.dir))


def stop(ref: Ref, *, workspace: PathLike | None = None) -> Path:
    """Ask a running run or calibration session to stop, and return its flag.

    The call writes ``<run or session>/.hmp/stop.json`` and returns at once. A
    run reads the flag between two steps, between two runs of its plan and,
    through ``libmf6`` or Boussinesq, between two time steps; it ends
    ``aborted`` and ``hmp.run(..., resume=ref)`` takes it up again. A session
    reads it between two batches of trials.

    Parameters
    ----------
    ref
        A run or a session: its directory, its name in ``workspace``
        (``<name>[.vN]``, ``runs/<name>``, ``sessions/<case>[.vN]``; a bare name
        is looked for among the runs first), or the object.
    workspace
        The project directory, or a folder inside it.

    Returns
    -------
    pathlib.Path
        The flag written, ``<dir>/.hmp/stop.json``.

    Raises
    ------
    hydromodpy.core.exceptions.NothingThereError
        If ``ref`` names no run and no session, or one that is not running.
    """
    from hydromodpy.core.exceptions import ConfigMissingError
    from hydromodpy.core.state.layout import RUNS_DIRNAME
    from hydromodpy.results.session.descriptor import resolve_session_dir
    from hydromodpy.results.storage.attempt import request_stop, run_dir_for_name

    if isinstance(ref, (Run, Session)):
        return request_stop(ref.dir)
    if workspace is None:
        return request_stop(_existing(ref))
    root = _root_of(workspace)
    text = os.fspath(ref)
    prefix = f"{RUNS_DIRNAME}/"
    name = text[len(prefix) :] if text.startswith(prefix) else text
    directory = None if "/" in name else run_dir_for_name(root, name)
    if directory is None and not text.startswith(prefix):
        try:
            directory = resolve_session_dir(root, text)
        except ConfigMissingError:
            directory = None
    if directory is None:
        raise NothingThereError(
            f"{text!r} names no run and no calibration session under {root}, "
            "there is nothing to stop."
        )
    return request_stop(directory)


def status(
    ref: Ref | None = None,
    *,
    workspace: PathLike | None = None,
    plan: bool = False,
    stale_after_s: float | None = None,
) -> RunOutcome | list[RunOutcome] | StatusReport:
    """Say where runs and sessions stand, read from the disk and never from the index.

    Without a reference, one :class:`~hydromodpy.project.request.RunOutcome`
    per directory of ``runs/`` and ``sessions/`` of the project, sorted by
    name. With a reference, the outcome of that one, with its deliveries. With
    ``plan=True``, where each case of the plan of a ``[sites]`` project stands,
    the :class:`~hydromodpy.project.launch.status.StatusReport` of
    ``project_status``, whose ``to_dict()`` is what ``hmp ls --plan
    --format json`` prints.

    Parameters
    ----------
    ref
        A run or a session (a directory, a name in ``workspace``, the object),
        or a project (its directory, ``"."`` in ``workspace``, the object).
    workspace
        The project directory, or a folder inside it.
    plan
        Read the plan of the project instead of its directories.
    stale_after_s
        Seconds after which a live run that stopped writing is called stale.
        ``None`` keeps the default.

    Returns
    -------
    RunOutcome or list of RunOutcome or StatusReport
        See above.

    Raises
    ------
    hydromodpy.core.exceptions.CommandUsageError
        If neither a reference nor ``workspace`` names the project.
    hydromodpy.results.catalog.discovery.SimulationNotFoundError
        If the reference names nothing.
    """
    from hydromodpy.project.request import outcome_of_directory, outcomes_under

    if ref is None and workspace is None:
        raise CommandUsageError(
            "status needs the project: give workspace=, or a reference that is a path."
        )
    if isinstance(ref, RunSet):
        raise CommandUsageError(
            "A set of runs has no directory: give a run, a session or a project."
        )
    directory = _root_of(workspace) if ref is None else _directory_of(ref, workspace)
    root = _project_of(directory)
    if plan:
        from hydromodpy.project.launch.status import project_status

        if stale_after_s is None:
            return project_status(root)
        return project_status(root, stale_after_s=stale_after_s)
    if directory == root:
        return outcomes_under(root, stale_after_s=stale_after_s)
    kind = "session" if directory.parent.name == SESSIONS_DIRNAME else "run"
    return outcome_of_directory(
        directory, project_root=root, kind=kind, stale_after_s=stale_after_s
    )


def trash(
    ref: Ref,
    *,
    workspace: PathLike | None = None,
    restore: bool = False,
    force: bool = False,
) -> list[Path]:
    """Move a run or a session to ``trash/``, or bring a trashed one back.

    A trashed directory keeps its name taken until the trash is emptied. The
    index, when the project has one, is brought up to date.

    Parameters
    ----------
    ref
        What to move: a run or a session (a directory, a name in ``workspace``,
        the object). With ``restore``, a trashed entry as ``hmp catalog trash``
        lists it, or the directory it came from.
    workspace
        The project directory, or a folder inside it.
    restore
        Bring the trashed entry back where it came from.
    force
        Move a protected directory, or one a stale attempt holds.

    Returns
    -------
    list of pathlib.Path
        The directories moved, where they now are.

    Raises
    ------
    hydromodpy.core.exceptions.WriteConflictError
        If the directory is running, or protected without ``force``.
    hydromodpy.results.catalog.discovery.SimulationNotFoundError
        If the reference names nothing.
    """
    from datetime import UTC, datetime

    from hydromodpy.results.catalog.indexer import reindex_if_indexed
    from hydromodpy.results.trash import restore as bring_back
    from hydromodpy.results.trash import trash_run

    if restore:
        from hydromodpy.results.catalog.discovery import resolve_trashed

        if workspace is None:
            raise CommandUsageError("trash(restore=True) needs workspace=, the project.")
        root = _root_of(workspace)
        moved = bring_back(root, resolve_trashed(root, os.fspath(ref)).name)
    else:
        directory = _directory_of(ref, workspace, unambiguous=True)
        root = _project_of(directory)
        rel_dir = directory.relative_to(root).as_posix()
        moved = trash_run(root, rel_dir, now=datetime.now(UTC), force=force)
    reindex_if_indexed(root)
    return [moved]


def compare(
    refs: Sequence[Ref],
    *,
    variables: Sequence[str] | None = None,
    out: PathLike | None = None,
    by: Literal["run", "site"] = "run",
    workspace: PathLike | None = None,
) -> Comparison | Path:
    """Compare sealed runs, the first one as the reference.

    A reference is a run directory, a run name or a recipe of the project
    (its latest run of each case), or the run. ``Comparison.table`` sets the
    parameters and the metrics of the runs side by side.

    Parameters
    ----------
    refs
        The runs to compare, the reference first.
    variables
        The variables to compare. ``None`` takes those the runs share.
    out
        Write the comparison to this folder.
    by
        ``"site"`` compares the runs of each site the references hold and
        joins their scores; it needs ``out`` and returns the folder written.
    workspace
        The project directory, or a folder inside it.

    Returns
    -------
    Comparison or pathlib.Path
        The comparison, or the folder written with ``by="site"``.

    Raises
    ------
    hydromodpy.project.compare.ComparisonReferenceError
        If a reference names no sealed run.
    hydromodpy.project.compare.ComparisonCaseError
        If the runs cannot be compared.
    """
    from hydromodpy.project.compare import compare_by_site, compare_references

    root = None if workspace is None else _root_of(workspace)
    named = [
        str(each.dir) if isinstance(each, (Run, Session)) else os.fspath(each) for each in refs
    ]
    if by == "site":
        if out is None:
            raise CommandUsageError("compare(by='site') writes a folder: give out=.")
        return compare_by_site(named, Path(out), project_root=root, variables=variables)
    comparison = compare_references(named, project_root=root, variables=variables)
    if out is not None:
        comparison.write(Path(out))
    return comparison


@overload
def show(ref: Ref, *, what: Literal["field"], **options: Any) -> xr.DataArray: ...
@overload
def show(ref: Ref, *, what: Literal["series"], **options: Any) -> pd.Series: ...
@overload
def show(ref: Ref, *, what: Literal["table", "point", "rank"], **options: Any) -> pd.DataFrame: ...
@overload
def show(ref: Ref, *, what: Literal["figure"], **options: Any) -> Figure | Path: ...
@overload
def show(ref: Ref, *, what: Literal["report"], **options: Any) -> Path: ...
@overload
def show(
    ref: Ref, *, what: Literal["summary", "profile"] = "summary", **options: Any
) -> dict[str, Any] | pd.DataFrame: ...
def show(
    ref: Ref,
    *,
    what: ShowWhat = "summary",
    workspace: PathLike | None = None,
    name: str | Sequence[str] | None = None,
    metric: str | None = None,
    limit: int | None = None,
    best: bool = True,
    time: str | int | None = None,
    layer: int | None = None,
    point: Mapping[str, Any] | None = None,
    sel: Mapping[str, Any] | None = None,
    bbox: Sequence[float] | None = None,
    station: str | None = None,
    preset: str | None = None,
    lang: str | None = None,
    strict: bool = False,
    detail: bool = False,
    mixed_windows: bool = False,
    dpi: int | None = None,
    options: Mapping[str, Any] | None = None,
    save: PathLike | None = None,
) -> Any:
    """Read one thing of a run, a session, a set of runs or a project.

    ``what`` names a line of :data:`hydromodpy.project.show.SHOWN`:

    ``summary`` (run, session, project) a dict of facts; ``profile`` (run,
    session) where the time went; ``table`` (run, session, set) the sealed
    table ``name``; ``field`` and ``series`` (run) the variable ``name`` at
    ``time``, ``layer``, ``sel``, ``bbox``; ``point`` (run) the variables
    ``name`` in the cell ``point`` (``x``, ``y``, ``cell``, ``depth``, ``label``)
    at ``layer`` and the time step ``time``; ``rank`` (project) the ``limit``
    best runs on ``metric`` at ``station``, the worst with ``best=False``;
    ``figure`` (run, session, set) the figure ``name`` with ``dpi``, ``time`` and
    the figure's ``options``; ``report`` (run, session) the report, with
    ``preset``, ``lang``, ``station``, ``strict``.

    A bare name that a session and a run both carry is read as the session for
    ``summary``, and as the run for the other values of ``what``. ``runs/<name>``
    names the run for ``summary``.

    With ``save`` the value is written to that file, by its suffix, and its
    path comes back; a figure is written as PNG, a report where reports go.
    A server always calls ``show`` with ``save``.

    Parameters
    ----------
    ref
        A run, a session, a set of runs or a project: a path, a name in
        ``workspace`` (``"."`` is the project), or the object.
    what
        What to read.
    workspace
        The project directory, or a folder inside it.

    Returns
    -------
    dict or DataFrame or Series or DataArray or Figure or Path
        What ``what`` reads, or the file written with ``save``.

    Raises
    ------
    hydromodpy.core.exceptions.CommandUsageError
        If ``what`` is not one the subject has; the message names those it has.
    """
    subject = _subject(ref, workspace, session_first=what == "summary")
    return shown(
        subject,
        what,
        {
            "name": name,
            "metric": metric,
            "limit": limit,
            "best": best,
            "time": time,
            "layer": layer,
            "point": point,
            "sel": None if sel is None else dict(sel),
            "bbox": None if bbox is None else tuple(bbox),
            "station": station,
            "preset": preset,
            "lang": lang,
            "strict": strict,
            "detail": detail,
            "mixed_windows": mixed_windows,
            "dpi": dpi,
            "options": options,
            "save": save,
        },
    )


@overload
def export(
    ref: Ref,
    variables: str | list[str] | None = None,
    *,
    deliver: Literal[False] = False,
    **options: Any,
) -> list[Path]: ...
@overload
def export(
    ref: Ref, variables: None = None, *, deliver: Literal[True], **options: Any
) -> tuple[PublishedLine, ...]: ...
def export(
    ref: Ref,
    variables: str | list[str] | None = None,
    *,
    time: str | int | list[str | int] | None = None,
    period: tuple[str, str] | None = None,
    format: str | None = None,  # noqa: A002 - the name of `--format`
    folder: PathLike | None = None,
    file: PathLike | None = None,
    crs: str | None = None,
    resolution: float | None = None,
    layer: int | None = None,
    nodata: float = -9999.0,
    deliver: bool = False,
    workspace: PathLike | None = None,
    environment: Environment | None = None,
) -> list[Path] | tuple[PublishedLine, ...]:
    """Export data of a run to files, or deliver what its ``[[export]]`` blocks name.

    The words of an ``[[export]]`` block and of ``hmp export``: ``variables``
    says what (a name, a list, or ``"all"``), ``time`` or ``period`` when,
    ``folder`` or ``file`` where. The format follows the data unless ``format``
    or the extension of ``file`` names one. Files land in
    ``runs/<run>/exports/`` and are recorded in ``exports/index.json``.

    Parameters
    ----------
    ref
        The run: its directory, its name in ``workspace``, or the run.
    variables
        What to export.
    deliver
        Send what the ``[[export]]`` blocks of the run name, and take no other word.
    workspace
        The project directory, or a folder inside it.
    environment
        A ``folder`` or ``file`` must sit under the roots its bounds allow.
        ``None`` keeps the default of the machine, which checks nothing.

    Returns
    -------
    list of pathlib.Path or tuple of PublishedLine
        The files written, or with ``deliver`` the delivery lines.

    Raises
    ------
    hydromodpy.core.exceptions.ExportError
        If ``variables`` is missing, or ``deliver`` comes with another word.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.export("runs/transient_nwt", "all", workspace="~/ws/p")  # doctest: +SKIP
    >>> hmp.export(run, deliver=True)  # doctest: +SKIP
    """
    from hydromodpy.core.exceptions import ExportError

    subject = _subject(ref, workspace)
    if not isinstance(subject, Run):
        raise TypeError(
            f"export reads a run, not a {type(subject).__name__}: give a run directory, "
            "a run named in workspace=, or a Run."
        )
    if deliver:
        others = (variables, time, period, format, folder, file, crs, resolution, layer)
        if any(value is not None for value in others) or nodata != -9999.0:
            raise ExportError(
                "deliver=True sends what the [[export]] blocks of the run name and takes "
                "no other word."
            )
        from hydromodpy.project.deliver import deliver_pending
        from hydromodpy.results.run.view import project_root_of

        located = project_root_of(subject.dir)
        return deliver_pending(
            subject.dir,
            environment or Environment.default(),
            project_root=located[0] if located is not None else subject.dir,
        )
    if variables is None:
        raise ExportError(
            'variables is missing: name what to export, e.g. variables = "head", '
            'variables = ["head", "discharge"], or variables = "all". '
            "deliver=True sends what the [[export]] blocks of the run name instead."
        )
    if environment is not None:
        # A folder or a file the caller names must sit under the roots the
        # bounds of the call allow before anything is written.
        if folder is not None:
            environment.bounds.require_path(folder, why="exporting to a folder")
        if file is not None:
            environment.bounds.require_path(file, why="exporting to a file")
    return subject.export(
        variables,
        time=time,
        period=period,
        format=format,
        folder=folder,
        file=file,
        crs=crs,
        resolution=resolution,
        layer=layer,
        nodata=nodata,
    )


def publish(
    ref: Ref,
    *,
    to: PathLike,
    format: Literal["dir", "tar"] = "dir",  # noqa: A002 - the name of `--format`
    with_: Sequence[Literal["results", "inputs"]] | None = None,
    public: bool = False,
    dry_run: bool = False,
    workspace: PathLike | None = None,
) -> Path | PublishedProject:
    """Copy a sealed run, the summary or every sealed run of a project out of the tree.

    A copy carries what a reader needs to read it, and with ``"inputs"`` to run
    it again. A project gives one folder per run and one for the summary, and
    the runs it left out with the reason; ``PublishedProject.to_dict()`` says it.

    Parameters
    ----------
    ref
        A run (its directory, its name in ``workspace``, the run), ``"summary"``
        in ``workspace``, or the project (its directory, ``"."`` in
        ``workspace``, the object).
    to
        Where the copy goes: a folder absent or empty, or the archive file.
    format
        ``"dir"`` or ``"tar"``.
    with_
        What the copy carries beyond the run record: ``"results"`` and
        ``"inputs"``, both by default.
    public
        Warn when the project declares no licence; the copy is written either way.
    dry_run
        Run every check, say where the copy would land and write nothing.
    workspace
        The project directory, or a folder inside it.

    Returns
    -------
    pathlib.Path or PublishedProject
        The copy, or for a project every copy and what was left out.

    Raises
    ------
    hydromodpy.core.exceptions.ExportError
        An unsealed run, a destination that holds something, an input that
        cannot be carried.
    FileNotFoundError
        If ``"summary"`` is asked before the summary was written.
    """
    from hydromodpy.core.state.layout import SUMMARY_DIRNAME, summary_dir_for
    from hydromodpy.project.exchange.share import inputs_of
    from hydromodpy.results.export.publish import DEFAULT_EXTRAS, publish_project
    from hydromodpy.results.export.publish import publish as publish_one

    if isinstance(ref, Project):
        root, source = ref.root, None
    elif workspace is not None and isinstance(ref, (str, os.PathLike)):
        root = _root_of(workspace)
        text = os.fspath(ref)
        if text == ".":
            source = None
        elif text == SUMMARY_DIRNAME:
            source = summary_dir_for(root)
            if not source.is_dir():
                raise FileNotFoundError(
                    f"{source} does not exist: write it with Project.collect() first."
                )
        else:
            source = _directory_of(text, workspace)
    else:
        directory = _directory_of(ref, None)
        root = _project_of(directory)
        source = None if directory == root else directory
    extras = DEFAULT_EXTRAS if with_ is None else tuple(with_)
    if source is None:
        return publish_project(
            root,
            Path(to).expanduser(),
            format=format,
            with_=extras,
            public=public,
            inputs=inputs_of(root),
            dry_run=dry_run,
        )
    return publish_one(
        source,
        Path(to).expanduser(),
        project_root=root,
        format=format,
        with_=extras,
        public=public,
        inputs=inputs_of(root),
        dry_run=dry_run,
    )


def example(
    name: str | None = None,
    *,
    add: bool = False,
    workspace: PathLike | None = None,
    ref: str | None = None,
    force: bool = False,
) -> tuple[ExampleEntry, ...] | ExampleEntry | InstallReport:
    """List the examples this build ships, show one, or install one.

    Parameters
    ----------
    name
        The example id. Without it, every example.
    add
        Install the example: fetch what is missing from the content-addressed
        cache, check every file against its sha256, and write the configs under
        ``projects/<directory>/`` and the data under ``data/<variable>/``.
    workspace
        Workspace root an example is installed in. Defaults to ``~/hydromodpy``.
    ref
        Git ref to fetch from. Defaults to ``v`` plus the installed version.
    force
        Overwrite a file whose content differs from the manifest.

    Returns
    -------
    tuple of ExampleEntry or ExampleEntry or InstallReport
        Every example, the one named, or what the install wrote.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> [entry.id for entry in hmp.example()]  # doctest: +SKIP
    >>> hmp.example("04", add=True).project_dir  # doctest: +SKIP
    """
    from hydromodpy.project.examples.manifest import find_entry, load_catalog

    if name is None:
        if add:
            raise CommandUsageError("example(add=True) installs one example: name it.")
        return load_catalog()
    entry = find_entry(name, load_catalog())
    if not add:
        return entry
    from hydromodpy.data.workspace.scaffold import DEFAULT_ROOT
    from hydromodpy.project.examples.blobs import resolve_source
    from hydromodpy.project.examples.install import install_example

    root = Path(workspace).expanduser().resolve() if workspace is not None else DEFAULT_ROOT
    return install_example(entry, workspace=root, source=resolve_source(ref), force=force)


def doctor() -> DoctorReport:
    """Say what this machine runs: Python, HydroModPy, the packages and the solvers.

    No solver is started. The report is ``doctor_report() -> DoctorReport`` of
    :mod:`hydromodpy.project.doctor`; its ``to_dict()`` gives ``python``,
    ``hydromodpy``, ``optional`` (each package and its version, ``None`` when
    missing) and ``solvers`` (each executable and its path, ``None`` when missing).

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.doctor().to_dict()["hydromodpy"]  # doctest: +SKIP
    """
    from hydromodpy.project.doctor import doctor_report

    return doctor_report()


# -- What the verbs share ------------------------------------------------------


def _root_of(workspace: PathLike) -> Path:
    """Return the project root of a folder the caller named."""
    return resolve_project_root(Path(workspace).expanduser().resolve())


def _project_of(directory: Path) -> Path:
    """Return the project a run, a session or a project root belongs to."""
    from hydromodpy.results.run.view import project_root_of

    located = project_root_of(directory)
    if located is not None:
        return located[0]
    if directory.parent.name == SESSIONS_DIRNAME:
        return directory.parent.parent
    return resolve_project_root(directory)


def _existing(ref: PathLike) -> Path:
    """Return the directory a path names, or refuse it when nothing is there."""
    target = Path(ref).expanduser().resolve()
    if not target.exists():
        raise NothingThereError(
            f"{target} does not exist. A name is read in a project: give workspace=."
        )
    return target


def _path_of(ref: Ref, workspace: PathLike | None) -> Path:
    """Return the path a reference that is text names: as it is, or in the project."""
    if workspace is None:
        return _existing(os.fspath(ref))
    return _directory_of(ref, workspace)


def _directory_of(
    ref: Ref,
    workspace: PathLike | None,
    *,
    unambiguous: bool = False,
    session_first: bool = False,
) -> Path:
    """Return the directory a reference names: a run, a session, or a project root.

    A bare name is a run, its latest version when it carries none, then a
    session; ``session_first`` reads the session before the run, for a name both
    carry. ``unambiguous`` refuses a bare run name that has several versions.
    Anything else (``runs/x``, ``sessions/x``, an id, a selector) is read by
    ``resolve_rel_dir``.
    """
    from hydromodpy.core.exceptions import ConfigMissingError
    from hydromodpy.results.catalog.discovery import SimulationNotFoundError, resolve_rel_dir
    from hydromodpy.results.session.descriptor import resolve_session_dir
    from hydromodpy.results.storage.attempt import run_dir_for_name

    if isinstance(ref, (Run, Session)):
        return ref.dir
    if isinstance(ref, Project):
        return ref.root
    if isinstance(ref, RunSet):
        raise CommandUsageError("A set of runs has no directory: give a run or a session.")
    if workspace is None:
        return _existing(ref)
    root = _root_of(workspace)
    text = os.fspath(ref).strip()
    if text in ("", "."):
        return root
    given = Path(text).expanduser()
    if given.is_absolute():
        return given.resolve()
    no_session = None
    if "/" not in text and not text.startswith("@"):
        found = None if unambiguous else run_dir_for_name(root, text)
        if found is not None and not session_first:
            return found
        try:
            return resolve_session_dir(root, text)
        except ConfigMissingError as exc:
            no_session = exc
        if found is not None:
            return found
    try:
        return root / resolve_rel_dir(root, text, unambiguous=unambiguous)
    except SimulationNotFoundError as exc:
        if no_session is None:
            raise
        raise SimulationNotFoundError(f"{exc} {no_session}") from exc


def _subject(ref: Ref, workspace: PathLike | None, *, session_first: bool = False) -> Any:
    """Return the object a reference names, opened by :func:`open` when it is not one."""
    if isinstance(ref, (Run, Session, RunSet, Project)):
        return ref
    return open(_directory_of(ref, workspace, session_first=session_first))


def _projects_hint(folder: Path) -> str:
    """Name the projects one or two levels under ``folder``, when it holds some."""
    if not folder.is_dir():
        return ""
    markers = [
        *folder.glob(f"*/{PROJECT_MARKER_FILENAME}"),
        *folder.glob(f"*/*/{PROJECT_MARKER_FILENAME}"),
    ]
    roots = sorted({marker.parent for marker in markers if marker.is_file()})
    if not roots:
        return ""
    names = ", ".join(str(r) for r in roots[:5])
    more = f" and {len(roots) - 5} more" if len(roots) > 5 else ""
    return f" This folder holds projects: {names}{more}. Open one of them."
