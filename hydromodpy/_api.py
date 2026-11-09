"""Top-level functional API for HydroModPy.

Mirrors the CLI verbs so ``hmp run config.toml`` and ``hmp.run("config.toml")``
execute the same workflow. Kept as a private module so the package facade
stays minimal.

The run-management CLI verbs (``hmp catalog delete/restore/trash/tag/note/
rename/rerun/diff/reindex/gc/watch``) are intentionally not mirrored as
top-level ``hmp.*`` symbols. :func:`open` hands back the object a path
stands for: a :class:`~hydromodpy.project.Project` (its cases, sites, runs,
sessions, and ``plan``, ``launch``, ``collect``, ``publish``), a
:class:`~hydromodpy.results.run.Run`, a calibration
:class:`~hydromodpy.results.session.view.Session`, or a
:class:`~hydromodpy.project.accessors.Workspace`; ``proj.store`` is the index
:class:`Catalog` (``diff``, ``sql``...). A run
directory is changed by the run itself (``Run.tag``, ``Run.note``,
``Run.delete``) or by :mod:`hydromodpy.results.trash` and
:mod:`hydromodpy.results.annotations`, and the index is rebuilt by
:func:`hydromodpy.results.catalog.indexer.rebuild_index`. The code behind
the other CLI verbs sits in the package each verb serves, and is not part of
the top-level API.
"""

from __future__ import annotations

import importlib
import platform
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.version import __version__

if TYPE_CHECKING:
    import os
    from collections.abc import Iterator, Mapping, Sequence
    from datetime import date

    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import xarray as xr
    from matplotlib.figure import Figure

    from hydromodpy.calibration import CalibrationReport
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.model.initial_config import SpinupConfig
    from hydromodpy.project.accessors import Workspace
    from hydromodpy.project.compare import Comparison
    from hydromodpy.project.environment import Environment
    from hydromodpy.project.examples.install import InstallReport
    from hydromodpy.project.examples.manifest import ExampleEntry
    from hydromodpy.project.facade import Project
    from hydromodpy.project.launch.sites.expansion import PlanDraft
    from hydromodpy.project.spinup import SpinupResult
    from hydromodpy.results.run import Run
    from hydromodpy.results.session.view import Session
    from hydromodpy.workflow.overview import OverviewResult

    # A file or folder path, as text or as a pathlib.Path.
    PathLike = str | os.PathLike[str]
    # A configuration: the path of its TOML file, or the validated object.
    ConfigLike = str | os.PathLike[str] | HydroModPyConfig
    Readable = xr.DataArray | pd.Series | pd.DataFrame | gpd.GeoDataFrame


def open(path: PathLike) -> Project | Run | Session | Workspace:
    """Open what a path stands for: a project, a run, a session or a workspace.

    The single door to read results from Python, with the words of the CLI:

    - a project directory, its ``project.toml`` or any folder inside it gives
      a :class:`~hydromodpy.project.Project`, read only: ``proj.cases``,
      ``proj.sites``, ``proj.best_runs("nse", by="site")``,
      ``proj.runs(site=...)``, ``proj.sessions[...]``, ``proj[ref]``, and
      ``proj.plan()``, ``proj.launch(parallel=, only=)``, ``proj.collect()``,
      ``proj.publish(to=)``. Its index is brought up to date with the run
      directories when it is read;
    - a sealed run directory (``runs/<name>`` or a kept trial) gives a
      :class:`~hydromodpy.results.run.Run` read from its own files, without
      the index;
    - a session directory (``sessions/<name>``) gives a
      :class:`~hydromodpy.results.session.view.Session`;
    - a workspace root (``workspace.toml`` or ``projects/``) gives a
      :class:`~hydromodpy.project.accessors.Workspace`.

    Parameters
    ----------
    path
        The directory or file, as a ``str`` or a :class:`pathlib.Path`.

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
    >>> proj.best_runs("nse", by="site")  # doctest: +SKIP
    >>> run = proj["J0014010-base"]  # doctest: +SKIP
    >>> run = hmp.open("~/ws/projects/bretagne_k/runs/J0014010-base")  # doctest: +SKIP

    See Also
    --------
    index
        The sealed runs of every project of a workspace.
    """
    from hydromodpy.core.state.layout import (
        PROJECT_MARKER_FILENAME,
        is_workspace_root,
        runs_dir_for,
        sessions_dir_for,
    )
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.project.accessors import Workspace
    from hydromodpy.project.facade import open_project, read_sealed_config
    from hydromodpy.results.run.view import open_run_dir
    from hydromodpy.results.session.descriptor import session_descriptor_path
    from hydromodpy.results.session.view import Session
    from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME

    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"{target} does not exist")
    if target.is_dir():
        # A session carries an outcome.json of its own, so it is told first.
        if session_descriptor_path(target).is_file():
            return Session(target, read_config=read_sealed_config)
        holds_a_run = any(
            (target / name).is_file() for name in (RUN_MANIFEST_FILENAME, RUN_OUTCOME_FILENAME)
        )
        if holds_a_run:
            # A run copied out of its project reads from its own seal and files.
            return open_run_dir(target, read_config=read_sealed_config)
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


def index(workspace: PathLike | None = None) -> Workspace:
    """Read the sealed runs of every project of a workspace, without any index.

    ``hmp.index().runs(site="nancon")`` lists the runs of one site across the
    projects of the workspace, from the ``simulation.parquet`` row each
    sealed run carries.

    Parameters
    ----------
    workspace
        The workspace root, or any folder inside it. Defaults to the nearest
        workspace root at or above the working directory; there is no other
        default.

    Returns
    -------
    hydromodpy.project.accessors.Workspace
        The workspace, read only.

    Raises
    ------
    FileNotFoundError
        If no workspace root (``workspace.toml`` or ``projects/``) is found.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.index("~/ws").runs(site="nancon")  # doctest: +SKIP
    """
    from hydromodpy.core.state.layout import is_workspace_root
    from hydromodpy.project.accessors import Workspace

    start = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd()
    for folder in (start, *start.parents):
        if is_workspace_root(folder):
            return Workspace(folder)
    raise FileNotFoundError(
        f"No workspace at or above {start} (no workspace.toml, no projects/). "
        "Name it: hmp.index('<workspace root>')."
    )


def _projects_hint(folder: Path) -> str:
    """Name the projects one or two levels under ``folder``, when it holds some."""
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME

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


@contextmanager
def _materialized_config(config: HydroModPyConfig) -> Iterator[Path]:
    """Write a resolved config to a temp TOML in its project_root and yield it.

    Lets a config object reach the path-based overview launcher. The temp file lives
    inside ``project_root`` so relative paths resolve identically; it is removed
    afterwards.
    """
    import uuid

    root = Path(config.workspace.project_root).expanduser().resolve()
    materialized = root / f".hmp_effective_{uuid.uuid4().hex[:8]}.toml"
    config.to_toml(materialized)
    try:
        yield materialized
    finally:
        materialized.unlink(missing_ok=True)


def _report_identical_run(name: str | None, sim_id: str) -> None:
    """Say on the log that a run was skipped for an identical completed one."""
    from hydromodpy.core.logging import get_logger
    from hydromodpy.project.dispatch.workflow import identical_run_message

    get_logger(__name__).warning(
        "%s Pass force=True to run it again.", identical_run_message(name, sim_id)
    )


def _refuse_a_calibration(source: str) -> None:
    """Refuse a calibration at the door of :func:`run`, saying which verb runs it."""
    from hydromodpy.core.exceptions import ConfigError

    raise ConfigError(
        f"{source} declares a calibration: run it with hmp.calibrate, which returns a "
        "CalibrationReport. To simulate this file once, set workflow.mode to simulation."
    )


def _refuse_a_sites_project(source: Path) -> None:
    """Refuse a ``[sites]`` project at the door of :func:`run`, saying what launches it."""
    from hydromodpy.core.exceptions import ConfigError

    raise ConfigError(
        f"{source} declares [sites]: its cases are launched one process each, by "
        f"hmp.open({str(source.parent)!r}).launch(). hmp.run(..., dry_run=True) shows its plan."
    )


def run(
    config: ConfigLike,
    *,
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
) -> Run | OverviewResult | PlanDraft | None:
    """Run a simulation or an overview from Python.

    What comes back follows the workflow of the configuration:

    - a simulation gives a :class:`~hydromodpy.results.run.Run`, or ``None`` when it
      keeps nothing to read: a window that stops before ``setup_process``, or
      ``save_catalog = false``;
    - an overview gives a :class:`~hydromodpy.workflow.overview.OverviewResult`;
    - ``dry_run=True`` gives a :class:`~hydromodpy.project.launch.sites.expansion.PlanDraft`,
      with nothing run and nothing written.

    A calibration is refused: :func:`calibrate` runs it. A ``[sites]`` project is
    refused too, :meth:`~hydromodpy.project.Project.launch` runs it.

    A simulation is named ``name=`` when given, else ``[simulation] name``
    of the configuration (a TOML file defaults it to its own stem). Like
    ``hmp run``, a simulation identical to a completed run of the project (same
    resolved configuration, same name) is not computed again: the completed run is
    returned and a warning names it. Pass ``force=True`` to compute it anyway. A run
    that is not identical follows ``[simulation] if_exists``.

    Parameters
    ----------
    config
        Path of the TOML file (``str`` or :class:`pathlib.Path`), or a
        validated :class:`~hydromodpy.config.HydroModPyConfig`.
    set
        Changes of the configuration of this run. A key is a dotted path, the grammar
        of ``--set`` (``{"flow.param.K.field.value": 2e-5}``), or a name of ``hmp config
        targets`` (``{"K": 2e-5}``). They are applied before the plan is built, sealed
        with the run and recorded in ``lineage.overrides``. Simulation only.
    name
        Name of the run.
    force
        Compute a run identical to a completed one, and claim a stale case whose
        process cannot be proven dead.
    fresh
        File everything a previous attempt left under ``attempts/<k>/`` and start over.
    resume
        Name of an interrupted case to continue in place from its journal.
    from_step, until_step
        Bounds of a partial run: names of pipeline steps, listed in
        :data:`~hydromodpy.core.pipeline_steps.STEP_NAMES`.
    dry_run
        Say what this configuration would run, and run nothing.
    frozen
        Require frozen input-data references: a project TOML answers to its lockfile,
        the ``config.toml`` of a run to the record of that run.
    no_display, headless
        Draw no figure. Neither enters the identity of the run or its sealed configuration.
    environment
        The :class:`~hydromodpy.project.environment.Environment` of the call:
        the credentials file it names, and the hosts, roots, byte ceiling and
        delay it bounds. ``None`` builds the default of the machine.

    Returns
    -------
    Run or OverviewResult or PlanDraft or None
        See above.

    Raises
    ------
    FileNotFoundError
        If the TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the TOML payload fails validation, or if the configuration declares a
        calibration or a ``[sites]`` project, or if an option does not go with its workflow.
    hydromodpy.core.exceptions.PipelineError
        If a workflow step raises during execution.
    hydromodpy.core.exceptions.SolverError
        If the configured solver fails to converge or crashes.
    hydromodpy.core.exceptions.CatalogError
        If a simulation finished but its catalog cannot be opened to return
        the run.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> run = hmp.run("run_transient_nwt.toml", name="baseline")  # doctest: +SKIP
    >>> again = hmp.run(
    ...     "run_transient_nwt.toml", name="baseline"
    ... )  # skipped  # doctest: +SKIP
    >>> sweep = hmp.run(
    ...     "run_transient_nwt.toml", name="k_low", set={"K": 1e-5}
    ... )  # doctest: +SKIP
    >>> plan = hmp.run("run_transient_nwt.toml", dry_run=True)  # doctest: +SKIP

    See Also
    --------
    calibrate
        Runs a calibration.
    hydromodpy.project.Project.simulate
        Object-oriented form for repeated runs from one project.
    """
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.dispatch.workflow import (
        completed_run_view,
        draft_of_a_file_or_config,
        run_overview,
        run_simulation,
    )

    is_path = isinstance(config, (str, Path))
    source: Any = Path(config).expanduser().resolve() if is_path else config
    if is_path:
        from hydromodpy.config.sites import is_sites_project
        from hydromodpy.workflow.dispatch import load_raw_toml, resolve_workflow

        workflow = resolve_workflow(source, cli_workflow=None)
        sites = is_sites_project(load_raw_toml(source))
    else:
        workflow, sites = _workflow_of_config(config), False

    if workflow == "calibration":
        _refuse_a_calibration(source.name if is_path else "This configuration")
    if dry_run:
        return draft_of_a_file_or_config(
            source,
            workflow=workflow,
            set_changes=set,
            name=name,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
        )
    if sites:
        _refuse_a_sites_project(source)
    if workflow == "overview":
        asked = {
            "set": set,
            "name": name,
            "force": force,
            "fresh": fresh,
            "resume": resume,
            "from_step": from_step,
            "until_step": until_step,
            "frozen": frozen,
        }
        written = sorted(key for key, value in asked.items() if value)
        if written:
            raise ConfigError(
                f"An overview takes none of {', '.join(written)}: they steer a simulation."
            )
        if is_path:
            return run_overview(source, environment=environment)
        with _materialized_config(config) as materialized_path:
            return run_overview(materialized_path, environment=environment)

    summary = run_simulation(
        source,
        changes=set,
        name=name,
        force=force,
        fresh=fresh,
        resume=resume,
        from_step=from_step,
        until_step=until_step,
        frozen=frozen,
        no_display=no_display,
        headless=headless,
        environment=environment,
    )
    if not summary.get("sim_id"):
        return None
    run_view = completed_run_view(summary)
    if summary.get("skipped"):
        _report_identical_run(summary.get("name"), str(summary["sim_id"]))
    return run_view


def _workflow_of_config(config: Any) -> str:
    """Return the workflow a config object runs: its mode, or what its sections imply."""
    from hydromodpy.workflow.dispatch import infer_workflow

    declared = getattr(getattr(config, "workflow", None), "mode", None)
    if declared:
        return str(declared)
    written = set(getattr(config, "model_fields_set", ()))
    return infer_workflow(
        calibration=getattr(config, "calibration", None) is not None,
        overview=getattr(config, "overview", None) is not None,
        simulation="simulation" in written,
    )


def calibrate(
    config: ConfigLike,
    *,
    phase: str | None = None,
    environment: Environment | None = None,
    **kwargs: Any,
) -> CalibrationReport:
    """Run a calibration workflow from a TOML file or config object.

    A path builds no project and goes to ``calibrate_a_file``; in-memory config
    objects open a lazy :class:`~hydromodpy.project.Project` so
    :func:`hydromodpy.calibration.runners.programmatic_runner.run_calibration_programmatic`
    has the project context it requires.

    A TOML declaring ``[[calibration.phases]]`` **routes** to
    :func:`~hydromodpy.calibration.runners.staged_runner.run_staged_calibration`:
    each phase calibrates its own parameters and freezes them for the next. The
    same declaration carried by an in-memory config object routes there too:
    :meth:`~hydromodpy.project.Project.calibrate` writes the document a staged
    run needs next to the project's ``sessions/`` and runs it from there.

    To read what a file declares without running anything, use
    :func:`~hydromodpy._api.calibration_phases` (``hmp.calibration_phases``).

    A script that calibrates with ``parallel`` above 1 needs the
    ``if __name__ == "__main__":`` guard, because the workers start in spawn.

    Parameters
    ----------
    config
        Path of the calibration TOML file (``str`` or :class:`pathlib.Path`),
        or a validated :class:`~hydromodpy.config.HydroModPyConfig`.
    phase
        Run only the named phase of a staged calibration.
    environment
        The :class:`~hydromodpy.project.environment.Environment` of the call:
        the credentials file it names is read once, and its bounds ride on the
        workflow context. ``None`` builds the default of the machine, which
        allows every host and checks nothing.
    **kwargs
        Options of the route, the same keys ``hmp calibrate`` takes.

    Returns
    -------
    hydromodpy.calibration.CalibrationReport
        What the calibration found, with or without phases, whatever the
        source of the configuration.

    Raises
    ------
    FileNotFoundError
        If the calibration TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the configuration cannot be read and the answer depends on reading
        it (``phase``), or if the preflight, the checks of ``hmp config check``,
        refuses the calibration a run would start. Every error is named, before
        anything is prepared.
    hydromodpy.core.exceptions.ConfigMissingError
        If neither ``config_path`` nor ``parameters`` is supplied.
    hydromodpy.core.exceptions.CalibrationError
        If a staged calibration cannot be run as declared, if ``phase`` names a
        phase the configuration does not declare, or if the optimizer or
        objective evaluation fails.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> report = hmp.calibrate("calibration.toml")  # doctest: +SKIP

    See Also
    --------
    hydromodpy.calibration.runners.cli_runner.run_calibration_cli
        TOML entry point used by the path branch.
    hydromodpy.calibration.runners.staged_runner.run_staged_calibration
        Staged entry point used when the TOML declares phases.
    hydromodpy.calibration.runners.programmatic_runner.run_calibration_programmatic
        Python entry point used by the config-object branch.
    hydromodpy.calibration.CalibrationReport
        Structured calibration result.
    """
    from hydromodpy.core.exceptions import CalibrationError
    from hydromodpy.project import Project
    from hydromodpy.project.calibrate import calibrate_a_file
    from hydromodpy.project.dispatch.workflow import no_such_phase

    if isinstance(config, (str, Path)):
        kwargs.pop("headless", None)
        return calibrate_a_file(config, phase=phase, environment=environment, **kwargs)

    calibration = getattr(config, "calibration", None)
    declared = getattr(calibration, "phases", None)
    if not declared and phase is not None:
        raise CalibrationError(no_such_phase("this configuration", phase))

    headless = bool(kwargs.pop("headless", True))
    if phase is not None:
        kwargs["phase"] = phase
    with Project(config, headless=headless, environment=environment) as project:
        return project.calibrate(**kwargs)


def calibration_phases(
    config: ConfigLike,
    *,
    workspace: str | Path | None = None,
    check: bool = False,
) -> dict[str, Any]:
    """Return what a calibration declares, with nothing run and nothing written.

    Parameters
    ----------
    config
        Path of the calibration TOML file (``str`` or :class:`pathlib.Path`),
        or a validated :class:`~hydromodpy.config.HydroModPyConfig`.
    workspace
        Override the project root the ``plan`` of a TOML path names.
    check
        Run the checks of ``hmp config check`` first, as a launch does. A file
        they refuse raises.

    Returns
    -------
    dict
        ``"phases"``: the declared phases, empty for a file with one search.
        Each names the method it runs; a phase that names none gets the one
        its criteria call for, and ``method_reason`` says why. ``interval_width``
        gives the width the phase reads its interval with and where it comes
        from. A phase that moves again a parameter an earlier phase passes on
        also names that phase, and says whether its engine starts from the
        passed value.

        ``"calibration"``: the whole ``[calibration]`` section a protocol
        unfolds into, without the ``protocol`` key, so it can be pasted in its
        place. A file naming no protocol gets its own section back. A config
        object gets its section as it stands.

        ``"protocol"``: ``None`` for a file naming no protocol, else a ``dict``
        with ``"name"``, ``"version"``, ``"citation"`` (the first reference,
        short form) and ``"inherited"`` (true when the protocol comes from the
        ``base_config``).

        ``"plan"``: for a TOML path, what a launch would write: its ``case``,
        ``session_dir``, ``run_dir``, ``version``, ``phases``,
        ``solves_in_parallel`` and ``save_runs``. ``None`` for a config object.

    Raises
    ------
    FileNotFoundError
        If the calibration TOML path does not exist.
    hydromodpy.core.exceptions.ConfigError
        If the configuration cannot be read, or if ``check`` refuses it.
    """
    from hydromodpy.calibration.runners.staged_runner import phase_summaries
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    # A calibration reads its files through the trial pipeline, the one global
    # the library keeps. Fill it before anything here reads a file.
    fill_trial_pipeline()

    if not isinstance(config, (str, Path)):
        section = getattr(config, "calibration", None)
        return {
            "phases": phase_summaries(section),
            "calibration": section.model_dump(mode="json", exclude_none=True),
            "protocol": _protocol_of_section(section),
            "plan": None,
        }
    from hydromodpy.calibration.preflight import preflight_launch
    from hydromodpy.calibration.runners.document import describe_dry_run, load_toml_calibration

    target = Path(config).expanduser().resolve()
    expanded = _expand_calibration_section(target)
    try:
        cfg, _raw = load_toml_calibration(target)
    except Exception as exc:
        raise ConfigError(f"{target} cannot be read: {exc}") from exc
    if check:
        preflight_launch(target)
    return {
        "phases": phase_summaries(cfg),
        **expanded,
        "plan": describe_dry_run(cfg, target, workspace=workspace),
    }


def _protocol_of_section(section: Any) -> dict[str, Any] | None:
    """Return the protocol a validated ``[calibration]`` section names, or ``None``.

    The same keys as the protocol of a file. A section belongs to a config object,
    so the protocol is its own: ``inherited`` is false.
    """
    from hydromodpy.calibration.protocols import get_protocol

    declared = getattr(section, "protocol", None)
    if declared is None:
        return None
    protocol = get_protocol(declared.name)
    citation = None
    if protocol.references:
        reference = protocol.references[0]
        citation = (
            f"{reference.authors.split(',')[0].strip()} et al. {reference.year}, {reference.doi}"
        )
    pinned = getattr(declared, "version", None)
    return {
        "name": protocol.name,
        "version": protocol.version if pinned is None else str(pinned),
        "citation": citation,
        "inherited": False,
    }


def _expand_calibration_section(target: Path) -> dict[str, Any]:
    """Return what a protocol unfolds ``target``'s ``[calibration]`` section into.

    Reads through the same ``base_config`` chain :func:`load_toml_calibration`
    resolves, then hands the document to
    :func:`hydromodpy.calibration.protocols.expand_calibration_protocol`. A
    file naming no protocol gets its own section back, ``protocol`` key
    aside: nothing was unfolded, so there is nothing else to say. A file
    naming one gets the whole section the protocol unfolds into, ``protocol``
    key aside: parameters, outputs, the blocks and phases it writes, and every
    other key the file or its ``base_config`` set. Pasted in place of the
    protocol, it runs the same stages.

    ``protocol["inherited"]`` says whether the protocol comes from the
    ``base_config`` rather than from ``target`` itself. A file that pastes the
    section under that same base then has to drop the inherited protocol.
    """
    import tomllib

    from hydromodpy.calibration.protocols import expand_calibration_protocol, get_protocol
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    try:
        raw = load_toml_with_base_config(target, root=ROOT_CONFIG)
    except Exception as exc:
        raise ConfigError(f"{target} cannot be read: {exc}") from exc
    calibration = raw.get("calibration")
    if not isinstance(calibration, dict):
        raise ConfigError(f"No [calibration] section in {target}")

    declaration = calibration.get("protocol")
    if declaration is None:
        section = {key: value for key, value in calibration.items() if key != "protocol"}
        return {"calibration": section, "protocol": None}

    try:
        expanded = expand_calibration_protocol(raw)
    except ValueError as exc:
        raise ConfigError(f"{target}: {exc}") from exc

    name = declaration if isinstance(declaration, str) else declaration.get("name")
    protocol = get_protocol(str(name))
    expanded_calibration = expanded.get("calibration") or {}
    section = {key: value for key, value in expanded_calibration.items() if key != "protocol"}
    try:
        own = tomllib.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{target} cannot be read: {exc}") from exc
    own_calibration = own.get("calibration")
    inherited = not (isinstance(own_calibration, dict) and "protocol" in own_calibration)
    citation = None
    if protocol.references:
        reference = protocol.references[0]
        citation = (
            f"{reference.authors.split(',')[0].strip()} et al. {reference.year}, {reference.doi}"
        )
    pinned = declaration.get("version") if isinstance(declaration, dict) else None
    return {
        "calibration": section,
        "protocol": {
            "name": protocol.name,
            "version": protocol.version if pinned is None else str(pinned),
            "citation": citation,
            "inherited": inherited,
        },
    }


def spinup(
    config: ConfigLike,
    *,
    spinup: SpinupConfig | None = None,
    name_prefix: str = "spinup",
    then_run: bool = False,
    headless: bool = True,
    environment: Environment | None = None,
) -> SpinupResult:
    """Run a cyclic spin-up from a TOML file or config object.

    Repeats the representative window (``[spinup] window_*``, else
    ``[simulation.time]``), restarting each cycle from the previous cycle's state,
    until the aquifer heads and the lake stage converge. One :class:`Project` is
    reused so the mesh is identical across cycles.

    Parameters
    ----------
    config
        Path of the TOML file (``str`` or :class:`pathlib.Path`), or a
        validated :class:`~hydromodpy.config.HydroModPyConfig`.
    spinup
        Settings that replace the ``[spinup]`` section of the configuration.
    name_prefix
        Prefix of the run name of each cycle.
    then_run
        Chain a production run from the converged state, over ``[simulation.time]``.
    headless
        Draw no figure.
    environment
        The :class:`~hydromodpy.project.environment.Environment` of the call:
        the credentials file it names, and the bounds it carries.
        ``None`` builds the default of the machine.

    Returns
    -------
    hydromodpy.project.spinup.SpinupResult
        The loop outcome. Feed ``result.restart_from`` to a production run's
        ``[flow] restart_from`` (a triangle or voronoi mesh is read back from the
        project mesh cache, so that run reproduces this mesh).

    See Also
    --------
    hydromodpy.project.spinup.run_spinup
        The underlying driver, callable on an existing Project.
    """
    import copy
    import dataclasses

    from hydromodpy.project import Project
    from hydromodpy.project.facade import resolve_config
    from hydromodpy.project.spinup import run_spinup

    source = Path(config).expanduser().resolve() if isinstance(config, (str, Path)) else config
    if isinstance(source, Path) and source.is_file():
        from hydromodpy.config.sites import is_sites_project
        from hydromodpy.workflow.dispatch import load_raw_toml

        if is_sites_project(load_raw_toml(source)):
            _refuse_a_sites_project(source)

    # Snapshot a clean production config before the spin-up mutates the model's
    # (cycle window, restart_from, IC).
    prod_cfg = None
    if then_run:
        if isinstance(source, Path):
            from hydromodpy.config import HydroModPyConfig

            prod_cfg = HydroModPyConfig.from_toml(source)
        else:
            prod_cfg = copy.deepcopy(resolve_config(source))

    with Project(source, headless=headless, no_display=True, environment=environment) as project:
        result = run_spinup(project, spinup=spinup, name_prefix=name_prefix)

    if not then_run or not result.restart_from:
        return result

    # Production run: a fresh project over the full [simulation.time] window,
    # seeded from the converged state. Its mesh must reproduce the spin-up mesh:
    # a generated mesh is read back from the project mesh cache.
    warning = result.antecedent_warning()
    if warning is not None:
        from hydromodpy.core.logging import get_logger

        get_logger(__name__).warning("chaining a production run: %s", warning)
    prod_cfg.flow.restart_from = result.restart_from
    production = run(prod_cfg, headless=headless, environment=environment)
    return dataclasses.replace(result, production_sim_id=getattr(production, "sim_id", None))


def compare_pair(ref_a: str, ref_b: str, *, workspace: PathLike | None = None) -> pd.DataFrame:
    """Compare the metrics of two runs side by side.

    Parameters
    ----------
    ref_a, ref_b
        Run references, as ``hmp catalog ls`` prints them: an id, a unique id
        prefix, a name or a selector such as ``@latest``.
    workspace
        Project directory whose catalog resolves the references. Defaults to
        the project around the working directory (the folder holding
        ``project.toml``).

    Returns
    -------
    pandas.DataFrame
        One row per metric and station, one column per run (``A`` for
        ``ref_a``, ``B`` for ``ref_b``). Empty when neither run has a metric.

    Raises
    ------
    FileNotFoundError
        If no catalog is found from ``workspace``.
    hydromodpy.results.catalog.SimulationNotFoundError
        If a reference matches no run of the catalog.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> table = hmp.compare_pair(
    ...     "ab12cd34", "ef56gh78", workspace="~/hmp_workspace"
    ... )  # doctest: +SKIP

    See Also
    --------
    hydromodpy.results.catalog.Catalog.diff
        The same two runs as a dictionary of what differs.
    """
    from hydromodpy.results.catalog.facade import compare_pair as _compare_pair

    return _compare_pair(ref_a, ref_b, workspace=workspace)


def compare(
    refs: Sequence[str],
    *,
    variables: Sequence[str] | None = None,
    out: PathLike | None = None,
    workspace: PathLike | None = None,
) -> Comparison:
    """Compare sealed runs of one site, the first one as the reference.

    Two series are compared on the dates they share and two maps at the last of
    those dates. Runs with no date in common are refused.

    Parameters
    ----------
    refs
        Run directories, run names under ``runs/`` (``base.v2``) or recipes (the
        latest run of each of their cases).
    variables
        Fields to map. Defaults to the head and the depth to the water table,
        when every run has them.
    out
        Folder to write the tables, the figures and the README into. By default
        nothing is written, and ``Comparison.write`` can do it later.
    workspace
        Project directory the references are read from. Defaults to the project
        around the working directory.

    Returns
    -------
    hydromodpy.project.compare.Comparison
        ``tables`` holds the data frames ``runs``, ``parameters``, ``scores``,
        ``budget``, ``network``, ``series`` and ``maps``.

    Raises
    ------
    hydromodpy.project.compare.ComparisonReferenceError
        If a reference names no sealed run.
    hydromodpy.project.compare.ComparisonCaseError
        If the runs model different sites or share no date.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> result = hmp.compare(["k_mid", "k_low"])  # doctest: +SKIP
    >>> result.tables["series"]  # doctest: +SKIP
    >>> result.write("../study")  # doctest: +SKIP
    """
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.project.compare import compare_references

    start = Path(workspace or Path.cwd()).expanduser().resolve()
    root = resolve_project_root(start)
    comparison = compare_references(refs, project_root=root, variables=variables)
    if out is not None:
        comparison.write(Path(out))
    return comparison


def report(session: str | None = None, *, workspace: PathLike | None = None) -> Path:
    """Render the HTML report of a calibration session.

    ``session`` names one session of the project by its directory:
    ``<case>[.vN]`` or ``sessions/<case>[.vN]``. ``None`` selects the session
    that started last. The report reads the session directory alone, never
    the index, and is written to ``sessions/<session>/report/index.html``.

    Parameters
    ----------
    session
        Directory name of the session, or ``None`` for the latest one.
    workspace
        The project directory, or a folder inside it. Defaults to the
        current working directory.

    Returns
    -------
    pathlib.Path
        The ``report/index.html`` written for the session.

    Raises
    ------
    hydromodpy.core.exceptions.ConfigMissingError
        If no calibration session matches ``session``.
    hydromodpy.core.exceptions.DisplayError
        If the report template or one of its figures fails to render.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.report()  # latest session of the current project  # doctest: +SKIP
    >>> hmp.report(
    ...     "calibration.v2", workspace="~/ws/projects/my_project"
    ... )  # doctest: +SKIP
    """
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.results.session.descriptor import resolve_session_dir
    from hydromodpy.workflow.steps.calibration import step_render_calibration_report

    start = Path(workspace).expanduser().resolve() if workspace is not None else Path.cwd()
    session_dir = resolve_session_dir(resolve_project_root(start), session)
    return step_render_calibration_report(session_dir=session_dir)


def read(
    run: Run,
    variable: str,
    *,
    time: int | str | date | np.datetime64 | np.integer | slice | None = None,
    layer: int | None = None,
    sel: dict | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> Readable:
    """Read a variable from a simulation Run.

    Single entry point for reads on a :class:`~hydromodpy.results.run.Run`. Each nature
    of variable gives one type, and ``time=`` never changes it:

    - field -> ``xarray.DataArray``: dimensions ``time``, ``layer``, ``cell`` as far as the field has them. One period in ``time`` removes the ``time`` dimension.
    - time series -> ``pandas.Series``: indexed by date. Takes ``sel`` and no ``time``.
    - geographic feature -> ``geopandas.GeoDataFrame``: one row per shape. Takes no ``time``.
    - ``"particles"`` -> ``pandas.DataFrame``: one row per recorded position. Takes no ``time``.

    Every registered field a run reports through ``has_field`` reads back
    here; an array a later version added, with no registered name, reads
    through ``Run.field``. A stored field is lazy when dask is installed. Fields rebuilt
    on the fly (water-table elevation/depth, seepage mask, drain outflow) are loaded
    eagerly, and ``time`` is ignored for a field with no time dimension. ``Run.field``
    gives one period as a bare array.

    To read by reference (id / unique prefix / name) instead of a ``Run``, use
    ``proj.store.read(ref, variable)`` on the :class:`hydromodpy.results.catalog.Catalog`
    of a project.

    Parameters
    ----------
    run
        A :class:`~hydromodpy.results.run.Run` (e.g. ``proj[ref]`` or
        ``hmp.open(<run dir>)``).
    variable
        Variable name, resolved against the field registry, then the
        ``timeseries`` table, then the geographic features.
    time
        The period of a field: an index (``int``, negative counts from the
        end), a date (``"2002-10-15"``, ``datetime.date``) that resolves to
        the stress period ``(start, end]`` holding it, ``"first"`` or ``"last"``; or a
        ``slice`` of indexes. ``None`` keeps every persisted period. A
        series or a feature refuses ``time``; window a series with
        ``sel={"period": (start, end)}``.
    layer
        Optional layer index for three-dimensional fields, 0 for the top layer.
    sel
        Optional selectors forwarded to the reader: ``{"station": ...}`` for
        timeseries, ``{"period": ...}`` for a window of dates.
    bbox
        Optional ``(xmin, ymin, xmax, ymax)`` in the simulation CRS;
        restricts a field to the cells whose center lies in the box.

    Returns
    -------
    xarray.DataArray or pandas.Series or geopandas.GeoDataFrame or pandas.DataFrame
        See the rule above.

    Raises
    ------
    TypeError
        If ``run`` is not a :class:`Run` instance, or ``time`` is of no
        accepted kind.
    ValueError
        If ``time`` names a date outside the run, or is given for a series or
        a feature.
    IndexError
        If ``time`` is an index outside the run.
    hydromodpy.results.errors.FieldNotFoundError
        If ``variable`` could not be resolved by any backend.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> proj = hmp.open("~/ws/projects/my_project")  # doctest: +SKIP
    >>> run = proj["baseline"]  # doctest: +SKIP
    >>> head = hmp.read(run, "head")  # every period  # doctest: +SKIP
    >>> last = hmp.read(run, "head", time=-1, layer=0)  # one period  # doctest: +SKIP
    >>> oct02 = hmp.read(run, "head", time="2002-10-15")  # doctest: +SKIP
    >>> ts = hmp.read(run, "discharge", sel={"station": "outlet"})  # doctest: +SKIP
    >>> gdf = hmp.read(run, "watershed")  # doctest: +SKIP
    >>> paths = hmp.read(run, "particles")  # doctest: +SKIP
    """
    from hydromodpy.results.derive.reading import read_variable

    return read_variable(run, variable, time=time, layer=layer, sel=sel, bbox=bbox)


def figure(
    run: Run,
    name: str,
    *,
    save: PathLike | None = None,
    dpi: int = 150,
    time: str | date | None = None,
    **opts: Any,
) -> Figure:
    """Render one registered figure for a simulation Run.

    The Python counterpart of ``[display].figures``: the same registry, the
    same names, the same options, so a figure produced by ``hmp run`` can be
    reproduced (or re-styled) from a script without importing anything from
    the display internals. List the names with
    :func:`hydromodpy.display.list_figures`. The options are the figure's
    own; the run's ``[display]`` is not applied (``hmp viz show`` applies it).

    Parameters
    ----------
    run
        A :class:`~hydromodpy.results.run.Run` (e.g. ``proj[ref]``).
    name
        Registered figure name, for example ``"piezometric_map"``.
    save
        Optional output path. A directory (or an extension-less path) gets
        ``<name>.png`` appended.
    dpi
        Raster resolution used when saving.
    time
        The instant a figure that draws one instant shows: a date
        (``"2002-10-15"``, or a ``datetime.date``), ``"first"`` or ``"last"``.
        The figure draws the stress period that holds the date. ``None``
        leaves the figure its own default, usually the last period.
    **opts
        Figure-specific options, identical to the ``[display.overrides]``
        entries (``overlays``, ``cmap``, ``orientation``, ...). A key the
        figure does not take is refused with the list of the keys it takes.

    Returns
    -------
    matplotlib.figure.Figure
        The rendered figure.

    Raises
    ------
    KeyError
        If ``name`` is not registered.
    ValueError
        If an option is not one the figure takes, if the run does not carry
        what the figure needs, or if ``time`` names no period of the run.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> proj = hmp.open("~/ws/projects/my_project")  # doctest: +SKIP
    >>> run = proj["baseline"]  # doctest: +SKIP
    >>> hmp.figure(run, "cross_section", orientation="sn")  # doctest: +SKIP
    >>> hmp.figure(run, "seepage_map", time="2002-10-15")  # doctest: +SKIP
    """
    from hydromodpy.display.runs import render_figure

    if time is not None:
        opts["time"] = time
    return render_figure(
        name, run, save=save, dpi=dpi, run_dir=run.dir if save is not None else None, **opts
    )


def export(
    run: Run,
    variables: str | list[str],
    *,
    time: str | int | list[str | int] | None = None,
    period: tuple[str, str] | None = None,
    format: str | None = None,
    folder: PathLike | None = None,
    file: PathLike | None = None,
    crs: str | None = None,
    resolution: float | None = None,
    layer: int | None = None,
    nodata: float = -9999.0,
    environment: Environment | None = None,
) -> list[Path]:
    """Export data of a simulation to files; return the files written.

    The words of an ``[[export]]`` block and of ``hmp export``: ``variables``
    says what (a name, a list, or ``"all"``: ``hmp export <run> --list``
    prints what a run holds), ``time`` or ``period`` when, ``folder`` or
    ``file`` where. The format follows the data unless ``format`` or the
    extension of ``file`` names one: a field at one date goes to GeoTIFF, one
    file per variable; over several dates to one NetCDF; a series or the
    budget to CSV; a vector layer (``watershed``, a network) to GeoPackage; a
    raster layer (``watershed_dem``) to GeoTIFF. Files land in
    ``runs/<run>/exports/`` and are recorded in ``exports/index.json``; a run
    leaves the tree by ``hmp publish``.

    ``run`` must be a :class:`~hydromodpy.results.run.Run`, as returned by
    ``hmp.open(project)[ref]`` or ``hmp.open(<run dir>)``.

    ``environment`` is the :class:`~hydromodpy.project.environment.Environment`
    of the call: a ``folder`` or ``file`` it names must sit under the roots its
    bounds allow. ``None`` keeps the default of the machine, which checks
    nothing.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> run = hmp.open("~/ws/projects/my_project")["transient_nwt"]  # doctest: +SKIP
    >>> hmp.export(run, "all")  # doctest: +SKIP
    >>> hmp.export(
    ...     run, ["head", "watertable_depth"], time="2001-08-15"
    ... )  # doctest: +SKIP
    >>> hmp.export(
    ...     run, "discharge", period=("2001-01-01", "2002-12-31")
    ... )  # doctest: +SKIP
    """
    from hydromodpy.results.run import Run

    if not isinstance(run, Run):
        raise TypeError(
            f"hmp.export expects a Run object as first argument, got {type(run).__name__}. "
            f"Obtain one with hmp.open(project)[ref] or hmp.open(<run dir>)."
        )
    if environment is not None:
        # A folder or a file the caller names must sit under the roots the
        # bounds of the call allow before anything is written.
        if folder is not None:
            environment.bounds.require_path(folder, why="exporting to a folder")
        if file is not None:
            environment.bounds.require_path(file, why="exporting to a file")
    return run.export(
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


def doctor() -> dict:
    """Lightweight environment diagnostic.

    Returns a dict describing Python, hydromodpy, and solver versions. Quick
    by design (no actual solver invocation) and safe to call at import probing
    time.

    Returns
    -------
    dict
        Diagnostic payload with Python, HydroModPy, optional package, and solver
        executable information.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.doctor()["hydromodpy"]  # doctest: +SKIP
    """
    info: dict = {
        "python": platform.python_version(),
        "hydromodpy": __version__,
        "solvers": {},
        "optional": {},
    }
    for pkg in (
        "numpy",
        "pandas",
        "scipy",
        "duckdb",
        "zarr",
        "pyproj",
        "rasterio",
        "shapely",
        "xarray",
        "flopy",
        "pydantic",
        "pint",
        "matplotlib",
        "gmsh",
        "whitebox_workflows",
        "geopandas",
    ):
        try:
            mod = importlib.import_module(pkg)
            info["optional"][pkg] = getattr(mod, "__version__", "?")
        except Exception:
            info["optional"][pkg] = None
    for exe in ("mf2005", "mfnwt", "mf6", "mp6", "mp7", "mt3dusgs"):
        info["solvers"][exe] = shutil.which(exe)
    return info


def example_list() -> tuple[ExampleEntry, ...]:
    """List the examples this build ships.

    Read from ``hydromodpy/project/examples/catalog.toml`` inside the wheel,
    so it answers offline and cannot promise what the installed version does
    not know about.

    Returns
    -------
    tuple of ExampleEntry
        One entry per cataloged example, in catalog order.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> [entry.id for entry in hmp.example_list()]  # doctest: +SKIP
    ['04']
    """
    from hydromodpy.project.examples.manifest import load_catalog

    return load_catalog()


def example_show(example_id: str) -> ExampleEntry:
    """Return one cataloged example, file by file.

    Parameters
    ----------
    example_id:
        Example id as listed by :func:`example_list`.

    Raises
    ------
    FileNotFoundError
        When no entry carries that id. The message names the ids that exist.
    """
    from hydromodpy.project.examples.manifest import find_entry, load_catalog

    return find_entry(example_id, load_catalog())


def example_add(
    example_id: str,
    *,
    workspace: PathLike | None = None,
    ref: str | None = None,
    force: bool = False,
) -> InstallReport:
    """Install one shipped example into a workspace.

    Fetches whatever is missing from the content-addressed cache, verifies
    every file against the sha256 the manifest declares, and writes the
    authored configs under ``projects/<directory>/`` and the data under
    ``data/<variable>/``.

    Parameters
    ----------
    example_id:
        Example id as listed by :func:`example_list`.
    workspace:
        Workspace root. Defaults to ``~/hydromodpy``.
    ref:
        Git ref to fetch from. Defaults to ``v`` plus the installed version.
        Ignored when ``HMP_EXAMPLES_SOURCE`` names another source.
    force:
        Overwrite destination files whose content differs from the manifest.
        Without it such a file is kept, so a local edit survives a re-install.

    Returns
    -------
    InstallReport
        What was written, what was already there, and what was downloaded.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> hmp.example_add("04").project_dir  # doctest: +SKIP
    PosixPath('/home/user/hydromodpy/projects/04_streamflow_intermittence_in_transient')
    """
    from hydromodpy.data.workspace.scaffold import DEFAULT_ROOT
    from hydromodpy.project.examples.blobs import resolve_source
    from hydromodpy.project.examples.install import install_example

    root = Path(workspace).expanduser().resolve() if workspace else DEFAULT_ROOT
    return install_example(
        example_show(example_id),
        workspace=root,
        source=resolve_source(ref),
        force=force,
    )
