"""Workflow dispatch adapters that bind launchers to ``Project``.

Wires the user-facing entry points (``run_simulation``, ``run_overview``,
``run_calibration``) to the matching workflow launchers. Each takes a
:class:`~hydromodpy.project.request.RunRequest` and the ``base`` its relative
paths are read from, and loads it through :func:`hydromodpy.config.loading.load`.
Lives under :mod:`hydromodpy.project.dispatch` because it depends on
:class:`hydromodpy.project.facade.Project`; the lower ``hydromodpy.workflow`` package
stays independent from that facade.

The order of a run is the one of the request: load the configuration, check the
environment and the name, claim ``runs/<name>/``, write ``request.json`` and
``config.toml``, resolve the inputs, write the request id into ``outcome.json``,
start over when the previous attempt asked for something else, then look for a
completed run with the same solution key and, when one answers, undo the claim
and give that run back (:func:`run_simulation`).

It also owns the staged-calibration routing question
(:func:`declared_calibration_phases`, :func:`calibration_phases_or_raise`),
which every calibration entry point asks before choosing a runner.

``completed_identical_run`` tells whether a plain run was already sealed with the same
resolved config, so that ``hmp run`` gives it back instead of computing it again.
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.project.environment import Environment
    from hydromodpy.project.launch.plan import PlanDraft
    from hydromodpy.project.request import RunOutcome, RunRequest
    from hydromodpy.results.exporters.export_spec import ExportRequest
    from hydromodpy.results.publication import PublishedLine
    from hydromodpy.results.run.view import Run
    from hydromodpy.workflow.overview import OverviewResult
    from hydromodpy.workflow.steps.prepare_solver.restart import WindowSource


def run_overview(
    request: RunRequest, *, base: str | Path, environment: Environment | None = None
) -> OverviewResult:
    """Generate a watershed identity card from a request, as a run of the project.

    The overview claims ``runs/<name>/`` through the attempt protocol like any
    run (``<name>`` is ``[site] name``, else ``[overview] name``): outcome,
    pulse and run log from the first act, its panels and pages in the run
    directory, a seal without solver tables, and a completed outcome. A run
    of the same name already sealed takes the next version. ``environment`` is the
    Environment of the call, ``None`` the default of the machine: it is checked
    against *base*, and its bounds reach the launcher. An overview is never
    skipped, so its key is only what the seal records.
    """
    from hydromodpy.core.config_kit.written import log_experimental_keys
    from hydromodpy.core.state.names import check_name
    from hydromodpy.core.state.result_dirs import refuse_a_sealed_run_as_project
    from hydromodpy.display.overview.location import overview_name
    from hydromodpy.project.request import write_request_file
    from hydromodpy.results.storage.attempt import record_request_id
    from hydromodpy.workflow.overview import DataOverviewLauncher
    from hydromodpy.workflow.record.attempt import run_attempt

    root = Path(base).expanduser().resolve()
    environment = _checked_environment(environment, root)
    cfg = _changed(_loaded(request, root), request.set)
    launcher = DataOverviewLauncher(
        cfg, base=root, source=_source_path(request, root), bounds=environment.bounds
    )
    site = cfg.site.name if getattr(cfg, "site", None) is not None else None
    overview = getattr(cfg, "overview", None)
    name = request.name or overview_name(
        site, getattr(overview, "name", None) if overview is not None else None
    )
    check_name(name, what="run")
    project_root = Path(cfg.workspace.project_root)
    refuse_a_sealed_run_as_project(project_root)
    request_id, key = _overview_identity(cfg)
    simulation = getattr(cfg, "simulation", None)
    log_experimental_keys(cfg)
    with run_attempt(
        project_root,
        name,
        case_id=name,
        project=project_root.name,
        site=site,
        if_exists=getattr(simulation, "if_exists", "version"),
    ) as handle:
        write_request_file(handle.run_dir, request)
        record_request_id(handle.run_dir, request_id)
        return launcher.run(handle.claim, solution_key=key)


def declared_calibration_phases(config_path: str | Path) -> list[str]:
    """Names of the ``[[calibration.phases]]`` a calibration TOML declares.

    Non-fatal on purpose: this answers the routing question and nothing else. A
    file that cannot be read declares no phase here, and its real error is
    raised by the runner that reads it next, with its context. Callers whose
    answer depends on reading the file use :func:`calibration_phases_or_raise`
    instead.
    """
    from hydromodpy.calibration.runners.document import load_toml_calibration
    from hydromodpy.core.exceptions import HydroModPyError

    try:
        cfg, _raw = load_toml_calibration(Path(config_path).expanduser().resolve())
    except (HydroModPyError, ValueError, OSError):
        return []
    return [decl.name for decl in (cfg.phases or [])]


def calibration_phases_or_raise(config_path: str | Path) -> list[str]:
    """Names of the declared phases, reporting a file that cannot be read.

    The raising sibling of :func:`declared_calibration_phases`, for the caller
    that reaches no runner afterwards: selecting a phase by name answers from
    the file itself, so a file that fails to validate must be reported as such
    and not as a file declaring no phase.
    """
    from hydromodpy.calibration.runners.document import load_toml_calibration
    from hydromodpy.core.exceptions import ConfigError, HydroModPyError

    target = Path(config_path).expanduser().resolve()
    try:
        cfg, _raw = load_toml_calibration(target)
    except (HydroModPyError, ValueError, OSError) as exc:
        raise ConfigError(f"{target} cannot be read: {exc}") from exc
    return [decl.name for decl in (cfg.phases or [])]


def no_such_phase(source: str, phase: str) -> str:
    """Message refusing a phase that ``source`` does not declare."""
    return f"{source} declares no [[calibration.phases]], so there is no phase {phase!r} to run."


def _checked_environment(environment: Environment | None, project_root: Path) -> Environment:
    """Return the Environment of a file verb, checked once before it runs."""
    from hydromodpy.core.workspace.resolve import find_data_workspace
    from hydromodpy.project.environment import Environment

    if environment is None:
        environment = Environment.default()
    environment.check(
        project_root=project_root,
        workspace_root=find_data_workspace(project_root) or project_root,
    )
    return environment


def run_calibration(
    request: RunRequest, *, base: str | Path, environment: Environment | None = None
) -> dict[str, Any]:
    """Run a parameter calibration campaign from a request.

    Routes to the staged runner when the document declares
    ``[[calibration.phases]]``, so a phased configuration is never flattened
    into a single calibration over the union of its parameters. The report is
    summarized as a mapping, because every caller of this dispatcher expects one.
    ``environment`` is the Environment of the call, ``None`` the default of the
    machine: it is checked against *base* before anything runs, and its bounds
    reach the trials.

    A request that is a plain TOML file, with no ``set``, no overlay and no case of its
    own, reaches the runners by the path of the file. Any other
    (a request in JSON, a mapping, a file with changes, ``--case``) is loaded and runs
    as a project held in memory, under the case the request names, else the case of
    its TOML file, else its ``[simulation] name``. A completed session
    of the same case and the same solution key is given back as its report instead of
    searching again, unless the request asks to ``force``, to resume or to run one
    ``phase``.
    """
    from hydromodpy.project.calibrate import route_calibration

    root = Path(base).expanduser().resolve()
    path = _source_path(request, root)
    held = bool(request.form != "toml" or request.set or request.overlays or request.name)
    if path is None or held:
        from hydromodpy.project.trial_pipeline import fill_trial_pipeline

        # The project that runs the calibration reads its files through the pipeline.
        fill_trial_pipeline()
        return _calibrate_in_memory(request, root, _checked_environment(environment, root))
    route = route_calibration(path, phase=request.phase, environment=environment, project_root=root)
    target, environment = route.target, route.environment
    runner_options: dict[str, Any] = {"bounds": environment.bounds}
    if request.resume is not None:
        runner_options["resume"] = True
    export_requests = _export_requests_of(target)
    if _delivery_asked(export_requests):
        # Before the trials: a refused destination costs no solver time. The
        # destination is checked once, and only the promoted run is delivered.
        from hydromodpy.project.deliver import preflight

        preflight(export_requests, environment, project_root=root)
    if request.phase is None and request.resume is None and not request.force:
        done = _completed_session(target)
        if done is not None:
            return _with_deliveries(done, export_requests, environment, project_root=root)
    if route.staged:
        from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

        result = run_staged_calibration(target, phase=request.phase, **runner_options)
    else:
        from hydromodpy.calibration.runners.cli_runner import run_calibration_cli

        result = run_calibration_cli(target, **runner_options)
    return _with_deliveries(result.to_dict(), export_requests, environment, project_root=root)


def _calibrate_in_memory(
    request: RunRequest, base: Path, environment: Environment
) -> dict[str, Any]:
    """Run the ``[calibration]`` a request carries as a project held in memory.

    The project never keeps the file of the request. Its configuration holds the
    changes, and a runner handed the file would read it from disk without them, or
    read a request in JSON as TOML. So the case is passed by name: the one the
    request names (``--case``), else the case a TOML file declares, else the
    ``[simulation] name`` of the document.
    """
    from hydromodpy.calibration.runners.session import calibration_case_name
    from hydromodpy.project.facade import Project

    cfg = _changed(_loaded(request, base), request.set)
    # The project root of the configuration, which its sessions/ lives under: a
    # project held in memory has no file to find it from.
    project_root = Path(cfg.workspace.project_root)
    requests = cfg.export
    if _delivery_asked(requests):
        # This path has no file of its own: the destinations are read from the
        # configuration the request already loaded.
        from hydromodpy.project.deliver import preflight

        preflight(requests, environment, project_root=project_root)
    options: dict[str, Any] = {
        "phase": request.phase,
        "resume": request.resume is not None,
        "workspace": project_root,
    }
    if request.force:
        options["force"] = True
    path = _source_path(request, base)
    case = request.name
    if case is None and request.form == "toml" and path is not None:
        case = calibration_case_name(path)
    if case is not None:
        options["case"] = case
    with Project(
        cfg,
        base=base,
        document=request.config,
        source=None,
        environment=environment,
    ) as project:
        report = project.calibrate(**options)
    return _with_deliveries(report.to_dict(), requests, environment, project_root=project_root)


def _completed_session(target: Path) -> dict[str, Any] | None:
    """Return the report of the completed session that answers the file *target*, as a mapping."""
    report = identical_session_of_file(target)
    return None if report is None else report.to_dict()


def identical_session_of_file(target: Path) -> Any:
    """Return the report of the completed session that answers the calibration file *target*, or None.

    A session answers when it carries the case of the file and the solution key of
    its configuration, search kept. The key is told offline: an input that needs the
    network leaves the case to run. A file that does not load as a project (a
    ``[calibration]`` section alone, an evaluator that runs no model) has no key a
    session could hold, so nothing answers it and the runner reads it as before.
    """
    from pydantic import ValidationError

    from hydromodpy.calibration.runners.document import identical_session
    from hydromodpy.config.loading import load
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.workflow.solution_key import planned_solution_key

    try:
        cfg = load(target)
    except (HydroModPyError, ValidationError, ValueError):
        return None
    return identical_session(
        planned_solution_key(cfg, search=True),
        project_root=Path(cfg.workspace.project_root),
        source=target,
    )


def completed_identical_run(project_root: Path, name: str, key: str | None) -> Path | None:
    """Return the directory of a completed run of *name* sealed with the solution key *key*, or None.

    Identical means the same solution key
    (:func:`~hydromodpy.results.record.request_identity.solution_key`): the request, the
    digest and state of every input it reads, the fingerprint of the code that
    computes, the solver binaries and the numeric packages. It is the
    ``identity.solution_key`` a run seals, so two runs of an unchanged file on
    unchanged data match. The run must carry the name ``name`` or be a
    version of it (``name.v2``): every version is looked at, newest first,
    because the user asks for this request and any sealed run of it
    answers, whichever version last ran it. Read from the manifests under
    ``runs/``, never from the index; a directory without a seal, or whose
    seal cannot be read, never matches. A run that read a file of an API whose
    extent came from the catchment (declared, not resolved before the key) is given
    back only when each such file is still in the cache with the digest the run
    recorded: a provider that refreshed it leaves the run to compute again.
    """
    from hydromodpy.core.state.layout import runs_dir_for
    from hydromodpy.results.catalog.registration import split_stem_version
    from hydromodpy.results.retention import level_at
    from hydromodpy.results.storage.kept import at_least
    from hydromodpy.results.storage.sealing import sealed_solution_key
    from hydromodpy.workflow.replay_checks import api_inputs_intact

    if key is None:
        return None
    runs = runs_dir_for(Path(project_root))
    if not runs.is_dir():
        return None
    versions: list[tuple[int, Path]] = []
    for entry in runs.iterdir():
        if not entry.is_dir():
            continue
        stem, version = split_stem_version(entry.name)
        if stem == split_stem_version(name)[0]:
            versions.append((1 if version is None else version, entry))
    for _version, run_dir in sorted(versions, reverse=True):
        if sealed_solution_key(run_dir) != key:
            continue
        if not api_inputs_intact(run_dir, Path(project_root)):
            continue
        try:
            level = level_at(run_dir)
        except (ValueError, OSError):
            continue
        if not at_least(level, "result"):
            continue
        return run_dir
    return None


def identical_run_message(name: str | None, sim_id: str) -> str:
    """The line that says an identical completed run made this one unnecessary."""
    label = name or sim_id[:8]
    return f"Config identical to completed run '{label}' [{sim_id[:8]}]; nothing to do."


def _overview_identity(cfg: HydroModPyConfig) -> tuple[str, str]:
    """Return the request id and the key an overview of *cfg* records."""
    from hydromodpy.data.loading.inputs import ResolvedInputs
    from hydromodpy.workflow.solution_key import (
        planned_request_id,
        request_id_of,
        solution_key_of,
    )

    request_id = planned_request_id(cfg, search=True)
    if request_id is None:
        request_id = request_id_of(cfg, ResolvedInputs(), search=True)
    return request_id, solution_key_of(cfg, request_id, binaries={})


def _source_path(request: RunRequest, base: Path) -> Path | None:
    """Return the file *request* was read from, absolute, or ``None`` when it has none."""
    if request.source is None:
        return None
    named = Path(request.source)
    return named if named.is_absolute() else Path(base) / named


def _loaded(request: RunRequest, base: Path) -> HydroModPyConfig:
    """Return the configuration of *request*, its document read against *base*."""
    from hydromodpy.config.loading import load

    return load(request.config, base, source_path=_source_path(request, base))


def _changed(cfg: HydroModPyConfig, overrides: Mapping[str, Any]) -> HydroModPyConfig:
    """Return *cfg* with the ``set`` of a request applied, the way a run applies it."""
    from hydromodpy.project.run_overrides import override_changes

    changes = override_changes(cfg, overrides)
    return cfg.with_changes(changes) if changes else cfg


def _export_requests_of(target: Path) -> list[ExportRequest]:
    """Return the ``[[export]]`` blocks a calibration file declares, validated."""
    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.config.loading import read_document
    from hydromodpy.results.exporters.export_spec import load_export_requests

    return load_export_requests(read_document(target, root=ROOT_CONFIG).get("export", []))


def _delivery_asked(blocks: Any) -> bool:
    """Whether one block of an export table names ``deliver_to``.

    *blocks* is the raw table of a document, whose blocks are mappings, or the
    validated ``cfg.export``, whose blocks are requests.
    """
    from hydromodpy.results.exporters.destination import DELIVER_TO_KEY

    if not isinstance(blocks, list | tuple):
        return False
    for block in blocks:
        if isinstance(block, Mapping):
            if DELIVER_TO_KEY in block:
                return True
        elif block.deliver_to:
            return True
    return False


def _delivered(
    outcome: RunOutcome,
    requests: Sequence[ExportRequest],
    environment: Environment | None,
) -> RunOutcome:
    """Deliver the files of a sealed run to the destinations of *requests*.

    A refusal is a ``failed`` line, never an exception: the run is sealed. A
    delivery reason never changes the outcome, which keeps its status and its
    ``identical_to``.
    """
    from hydromodpy.project.deliver import deliver_run
    from hydromodpy.project.environment import Environment as CallEnvironment

    lines = deliver_run(
        outcome.run_dir,
        requests,
        environment or CallEnvironment.default(),
        project_root=outcome.project_root,
    )
    return dataclasses.replace(outcome, deliveries=lines)


def _with_deliveries(
    summary: dict[str, Any],
    requests: Sequence[ExportRequest],
    environment: Environment | None,
    *,
    project_root: Path,
) -> dict[str, Any]:
    """Deliver the promoted runs of a completed calibration and add their lines to *summary*.

    The run of each case of ``best_cases`` is delivered, or the one
    ``best_rel_dir`` names, never a trial. A session that did not complete,
    or that promoted no run, delivers nothing and says so. A document whose
    blocks name no ``deliver_to`` leaves *summary* untouched.
    """
    if not _delivery_asked(requests):
        return summary
    from hydromodpy.core.logging import get_logger
    from hydromodpy.project.deliver import deliver_run
    from hydromodpy.project.environment import Environment as CallEnvironment

    logger = get_logger(__name__)
    lines: list[PublishedLine] = []
    status = summary.get("status")
    rel_dirs = _promoted_rel_dirs(summary)
    if status != "completed":
        logger.warning("the calibration closed as %s: nothing is delivered.", status)
    elif not rel_dirs:
        logger.warning("the calibration promoted no run: nothing is delivered.")
    else:
        workspace = Path(summary.get("workspace") or project_root)
        for rel_dir in rel_dirs:
            lines.extend(
                deliver_run(
                    workspace / rel_dir,
                    requests,
                    environment or CallEnvironment.default(),
                    project_root=project_root,
                )
            )
    summary["deliveries"] = [line.model_dump(mode="json", exclude_none=True) for line in lines]
    return summary


def _promoted_rel_dirs(summary: Mapping[str, Any]) -> list[str]:
    """Return the run folder of each case a calibration summary names, once each."""
    best = summary.get("best_rel_dir")
    if best:
        return [best]
    found: list[str] = []
    for case in (summary.get("best_cases") or {}).values():
        rel_dir = case.get("rel_dir") if isinstance(case, Mapping) else None
        if rel_dir and rel_dir not in found:
            found.append(rel_dir)
    return found


def run_simulation(
    request: RunRequest,
    *,
    base: str | Path,
    environment: Environment | None = None,
    lineage: Any = None,
    calibrated_by: Any = None,
    replay_of: Path | None = None,
    strict: bool = False,
) -> RunOutcome | None:
    """Execute a case, the worker verb: one run, or the windows of a chain one after the other.

    A document with ``[simulation.time] window_length`` is cut into windows, each a run
    of its own that :func:`run_single_simulation` plays
    (:func:`hydromodpy.project.windows.run_windows`); the outcome of the last window
    played comes back. The windows are counted with the ``set`` of the request
    applied, as the runs solve them. The configuration of a sealed run, and a
    published copy, replay as one run: a window ``k > 1`` replays from the source its
    ``inputs.json`` names. Every other document is one run, and the rest of this
    docstring is about it.

    A document whose ``[[export]]`` blocks name ``deliver_to`` has every
    destination checked before the claim, unless the call replays a run. The
    checked environment reaches the probe, so an address off the allowed hosts is
    refused there.
    """
    from hydromodpy.workflow.replay_checks import sealed_run_of

    root = Path(base).expanduser().resolve()
    environment = _checked_environment(environment, root)
    cfg = _loaded(request, root)
    config_path = _source_path(request, root)
    if replay_of is None and _delivery_asked(cfg.export):
        # Before the claim and before the windows are cut: a refused destination
        # leaves nothing on the disk, and one probe covers every window.
        from hydromodpy.project.deliver import preflight

        preflight(cfg.export, environment, project_root=root)
    cut = getattr(getattr(cfg.simulation, "time", None), "window_length", None) is not None
    window_source = None
    if cut:
        source_run = replay_of or (None if config_path is None else sealed_run_of(config_path))
        if source_run is None:
            from hydromodpy.project.windows import run_windows

            return run_windows(
                request,
                cfg=_changed(cfg, request.set),
                base=root,
                environment=environment,
                play=functools.partial(
                    run_single_simulation,
                    base=root,
                    environment=environment,
                    lineage=lineage,
                    calibrated_by=calibrated_by,
                ),
            )
        from hydromodpy.project.windows import recorded_window_source

        window_source = recorded_window_source(source_run, Path(cfg.workspace.project_root))
    return run_single_simulation(
        request,
        base=root,
        environment=environment,
        lineage=lineage,
        calibrated_by=calibrated_by,
        replay_of=replay_of,
        strict=strict,
        window_source=window_source,
        cfg=cfg,
    )


def run_single_simulation(
    request: RunRequest,
    *,
    base: str | Path,
    environment: Environment | None = None,
    lineage: Any = None,
    calibrated_by: Any = None,
    replay_of: Path | None = None,
    strict: bool = False,
    window_source: WindowSource | None = None,
    cfg: HydroModPyConfig | None = None,
) -> RunOutcome | None:
    """Execute one attempt of a case, the worker of one run.

    *request* carries the document of the case and the options that steer the run;
    *base* is the folder its relative paths are read from. The run is named by
    ``request.name``, else ``[simulation] name`` (which a TOML file defaults to its
    own stem). The order is the one of the module: load, environment, name, claim of
    ``runs/<name>/``, ``request.json`` and ``config.toml``, resolved inputs, request id
    in ``outcome.json``, restart over when the previous attempt asked for something
    else, then the search for a completed run of the same solution key. A plain run
    that one answers is not computed: its claim is undone and the outcome of the
    completed run comes back with ``identical_to`` naming it, unless ``force`` is set.
    ``if_exists = "fail"`` is checked after that, so an identical run is still given
    back. Resume and partial runs always proceed, and so does a replay: it is
    identical to the run it replays by construction.

    The index is never opened here: the outcome comes from the run directory, and the
    caller indexes it afterwards. ``replay_of`` names the run or published copy a
    replay plays again: its inputs are pinned at the digests of the record
    (:mod:`hydromodpy.workflow.replay_checks`), what the build decided otherwise and
    the producer entries that differ enter the lineage of the new run, and ``strict``
    refuses a value that did not reproduce the source, at the seal. ``lineage`` and
    ``calibrated_by`` are the blocks a promotion seals its run with. ``environment``
    is the Environment of the call: only its bounds cross into the setup context, and
    ``None`` keeps the default of the machine. ``window_source`` is the run window
    ``k - 1`` of a chain left, which window ``k > 1`` starts from. ``cfg`` is the
    document of *request* when the caller loaded it and checked the environment
    already. Returns ``None`` for a window that owns no run record.

    A completed run whose document names ``deliver_to`` is delivered once it is
    sealed, and so is a run given back for an identical one. A replay delivers
    nothing, and a delivery failure leaves the outcome ``completed``.
    """
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.core.state.names import check_name
    from hydromodpy.project.facade import Project

    root = Path(base).expanduser().resolve()
    if cfg is None:
        environment = _checked_environment(environment, root)
        cfg = _loaded(request, root)
    config_path = _source_path(request, root)
    run_name = request.resume or request.name or cfg.simulation.name
    if request.resume == "":
        # A bare resume continues the run the request names: its case, else the
        # [simulation] name, which a TOML file folds from its own stem.
        if not run_name:
            raise ConfigError(
                "A bare --resume continues the run the request names, and this request "
                "names none. Pass --resume NAME, or name the run with --case."
            )
        request = request.model_copy(update={"resume": run_name})
    if run_name:
        check_name(run_name, what="run")
    with Project(
        cfg,
        base=root,
        document=request.config,
        source=config_path,
        no_display=request.no_display,
        environment=environment,
    ) as project:
        source_run = replay_of
        frozen = request.frozen
        if source_run is not None:
            frozen = False
        plain_run = (
            not request.force
            and bool(run_name)
            and request.resume is None
            and request.from_step is None
            and request.until_step is None
            and source_run is None
        )
        result = project._runner.execute(
            request,
            lineage=lineage,
            calibrated_by=calibrated_by,
            frozen=frozen,
            skip_identical=plain_run,
            window_source=window_source,
            replay_of=source_run,
            strict=strict,
        )
        if result is None:
            return None
        if result.identical_to is not None:
            # A run given back is already sealed: the document's destinations
            # still receive it, because deliver_to is not part of the request id.
            if replay_of is None and _delivery_asked(cfg.export):
                return _delivered(result, cfg.export, environment)
            return result
        mesh_summary = mesh_summary_of(project)
        if mesh_summary:
            result = dataclasses.replace(result, mesh_summary=mesh_summary)
        if replay_of is None and result.status == "completed" and _delivery_asked(cfg.export):
            result = _delivered(result, cfg.export, environment)
        return result


def mesh_summary_of(project: Any) -> dict[str, Any]:
    """The mesh summary of a project whose plan runs a mesh process, else nothing."""
    project_ctx = getattr(project, "_ctx", None)
    project_setup = getattr(project_ctx, "setup", None)
    project_plan = getattr(getattr(project_ctx, "execution", None), "simulation_plan", None)
    mesh_summary = getattr(project_setup, "mesh_summary", None)
    has_mesh_process = any(
        getattr(run, "process_type", None) == "mesh"
        for run in getattr(project_plan, "runs", ()) or ()
    )
    if has_mesh_process and isinstance(mesh_summary, Mapping):
        return dict(mesh_summary)
    return {}


def completed_run_view(outcome: RunOutcome) -> Run | None:
    """Return the run an outcome of :func:`run_simulation` names, with the index up to date.

    The worker never opens the index, so it is refreshed here, for the readers that list
    runs. The run itself is read from its directory: an index handle opened earlier in
    this process keeps the snapshot it opened on, so a run indexed since is not found
    through it.
    """
    from hydromodpy.project.runner import run_view_of
    from hydromodpy.results.catalog.indexer import index_after_run

    index_after_run(outcome.project_root)
    return run_view_of(
        outcome.run_dir, project_root=outcome.project_root, sim_id=str(outcome.sim_id)
    )


def draft_of_a_file_or_config(
    source: Any,
    *,
    workflow: str,
    base: str | Path | None = None,
    set_changes: Mapping[str, Any] | None = None,
    name: str | None = None,
    resume: str | None = None,
    from_step: str | None = None,
    until_step: str | None = None,
) -> PlanDraft:
    """Return the plan of a TOML file or a configuration, with nothing run or written.

    A ``[sites]`` file gives every case of its plan. Any other gives one case: the
    steps of a simulation, none for an overview, which is one piece. *base* is the
    folder the relative paths of a file are read from, the project root above it when
    not given.
    """
    from hydromodpy.config.sites import is_sites_project
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.core.toml_io.paths import assign, parse
    from hydromodpy.project.facade import Project
    from hydromodpy.project.launch.plan import expand_plan, single_case_draft
    from hydromodpy.workflow.dispatch import load_raw_toml

    path = Path(source) if isinstance(source, (str, Path)) else None
    if path is not None and is_sites_project(load_raw_toml(path)):
        payload: dict[str, Any] = {}
        for dotted, value in (set_changes or {}).items():
            assign(payload, parse(dotted), value)
        return expand_plan(resolve_project_root(path.parent), path, set_overrides=payload)
    if workflow == "overview":
        from hydromodpy.config.hydromodpy_config import HydroModPyConfig
        from hydromodpy.display.overview.location import overview_name

        cfg = HydroModPyConfig.from_toml(path) if path is not None else source
        site = cfg.site.name if getattr(cfg, "site", None) is not None else None
        overview = getattr(cfg, "overview", None)
        label = overview_name(site, getattr(overview, "name", None))
        return single_case_draft(cfg, name=label, config_path=path, steps=(), kind="overview")
    with Project(source, base=base) as project:
        return project.simulate(
            dry_run=True,
            set=set_changes,
            name=name,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
        )


DISPATCH: dict[str, Callable[..., Any]] = {
    "simulation": run_simulation,
    "overview": run_overview,
    "calibration": run_calibration,
}


def dispatch_workflow(
    workflow: str, request: RunRequest, *, base: str | Path, **kwargs: Any
) -> Any:
    """Dispatch *request* to the adapter for a resolved workflow name."""
    runner = DISPATCH[workflow]
    return runner(request, base=base, **kwargs)


__all__ = [
    "DISPATCH",
    "calibration_phases_or_raise",
    "completed_identical_run",
    "identical_session_of_file",
    "completed_run_view",
    "declared_calibration_phases",
    "dispatch_workflow",
    "draft_of_a_file_or_config",
    "identical_run_message",
    "mesh_summary_of",
    "no_such_phase",
    "run_calibration",
    "run_overview",
    "run_simulation",
]
