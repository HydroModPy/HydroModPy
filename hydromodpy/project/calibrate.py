"""The routing of a calibration: which runner a declaration goes to.

:meth:`Project.calibrate <hydromodpy.project.facade.Project.calibrate>` and
``hmp.calibrate`` on a path end here. A TOML file goes to the staged runner when
it declares ``[[calibration.phases]]``, to the CLI runner otherwise
(:func:`calibrate_a_file`). A declaration held in memory (``parameters=``, a
``protocol=``, or the ``[calibration]`` section of the project config) goes to the
programmatic runner, on the project itself (:func:`calibrate_project`). A dry run
says what a declaration holds and writes nothing (:func:`calibration_plan`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.project.environment import Environment
    from hydromodpy.project.facade import Project

FROM_FILE = (
    "case= names the session of a calibration held in memory; a file names its "
    "case with [simulation] name."
)


@dataclass(frozen=True, slots=True)
class CalibrationPlan:
    """What a calibration declares, with nothing run and nothing written.

    Attributes
    ----------
    phases
        The declared phases, empty for a file with one search. Each names the
        method it runs, and a phase that names none gets the one its criteria
        call for, with ``method_reason`` saying why. ``interval_width`` gives the
        width the phase reads its interval with and where it comes from. A phase
        that moves again a parameter an earlier phase passes on also names that
        phase, and says whether its engine starts from the passed value.
    calibration
        The whole ``[calibration]`` section a protocol unfolds into, without
        the ``protocol`` key, so it can be pasted in its place. A file naming no
        protocol gets its own section back, a configuration its section as it is.
    protocol
        ``None`` for a declaration naming no protocol, else ``name``, ``version``,
        ``citation`` (the first reference, short form) and ``inherited`` (true
        when the protocol comes from the ``base_config``).
    plan
        For a file, what a launch would write: its ``case``, ``session_dir``,
        ``run_dir``, ``version``, ``phases``, ``solves_in_parallel`` and
        ``save_runs``. ``None`` for a configuration object.
    """

    phases: list[dict[str, Any]]
    calibration: dict[str, Any]
    protocol: dict[str, Any] | None
    plan: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        """Return the four members as JSON: a path as text, a date as ISO text."""
        return _plain(
            {
                "phases": self.phases,
                "calibration": self.calibration,
                "protocol": self.protocol,
                "plan": self.plan,
            }
        )


def _plain(value: Any) -> Any:
    """Return *value* with only what JSON holds: mappings, lists, text, numbers and ``None``."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def calibration_plan(
    config: str | Path | HydroModPyConfig,
    *,
    workspace: str | Path | None = None,
    check: bool = False,
) -> CalibrationPlan:
    """Return what a calibration declares, with nothing run and nothing written.

    Parameters
    ----------
    config
        The calibration TOML file, or a validated
        :class:`~hydromodpy.config.HydroModPyConfig`.
    workspace
        Overrides the project root the ``plan`` of a file names.
    check
        Run the checks of ``hmp check`` first, as a launch does. A file they
        refuse raises.

    Raises
    ------
    FileNotFoundError
        If the calibration file does not exist.
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
        return CalibrationPlan(
            phases=phase_summaries(section),
            calibration=section.model_dump(mode="json", exclude_none=True),
            protocol=_protocol_of_section(section),
            plan=None,
        )
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
    return CalibrationPlan(
        phases=phase_summaries(cfg),
        calibration=expanded["calibration"],
        protocol=expanded["protocol"],
        plan=describe_dry_run(cfg, target, workspace=workspace),
    )


def calibrate_a_file(
    config_path: str | Path,
    *,
    phase: str | None = None,
    dry_run: bool = False,
    workspace: str | Path | None = None,
    project: str | None = None,
    metric_fn: Any = None,
    objective: str | None = None,
    resume: bool = False,
    force: bool = False,
    environment: Environment | None = None,
    report: bool = True,
):
    """Run the calibration a TOML file declares. It needs no :class:`Project`.

    ``report=False`` skips the session report written once the search is over.

    ``environment`` is the :class:`~hydromodpy.project.environment.Environment`
    of the call: ``None`` builds the default of the machine. It is checked
    here once, so a credentials file the table refuses, or a folder the
    bounds of the call do not allow, stops the calibrate before it starts.
    A completed session of the case of the file and of the same solution key
    is given back as its report, unless ``force``, ``resume`` or ``phase``.
    """
    from hydromodpy.calibration.preflight import preflight_launch
    from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
    from hydromodpy.calibration.runners.document import describe_dry_run, load_toml_calibration
    from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
    from hydromodpy.core.exceptions import CalibrationError
    from hydromodpy.core.workspace.resolve import find_data_workspace
    from hydromodpy.project.dispatch.workflow import (
        calibration_phases_or_raise,
        declared_calibration_phases,
        no_such_phase,
    )
    from hydromodpy.project.environment import Environment
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    # A calibration reads its files through the trial pipeline, the one global
    # the library keeps. Fill it before the routing question and the launch read.
    fill_trial_pipeline()

    target = Path(config_path).expanduser().resolve()
    if environment is None:
        environment = Environment.default()
    # The closest project root a file calibration has, before its document is
    # loaded: the workspace it names, else the folder of the TOML. The check
    # refuses the roots it must and reads the credentials file once.
    project_root = (
        Path(workspace).expanduser().resolve() if workspace is not None else target.parent
    )
    environment.check(
        project_root=project_root,
        workspace_root=find_data_workspace(project_root) or project_root,
    )
    # Routing alone tolerates an unreadable file: the runner that reads it next
    # reports the failure with its own context. Selecting a phase by name reaches
    # no runner, so the failure has to surface here, or the user is sent looking
    # at a phases block that is present and correct.
    if phase is not None:
        declared_phases = calibration_phases_or_raise(target)
    else:
        declared_phases = declared_calibration_phases(target)
    if phase is not None and not declared_phases:
        raise CalibrationError(no_such_phase(target.name, phase))
    preflight_launch(target)
    if dry_run:
        return describe_dry_run(load_toml_calibration(target)[0], target, workspace=workspace)
    if not (force or resume or phase is not None):
        from hydromodpy.project.dispatch.workflow import identical_session_of_file

        identical = identical_session_of_file(target)
        if identical is not None:
            return identical
    options = {
        "workspace": workspace,
        "project": project,
        "metric_fn": metric_fn,
        "objective": objective,
        "resume": resume,
    }
    if declared_phases:
        result = run_staged_calibration(target, phase=phase, bounds=environment.bounds, **options)
    else:
        # Same descent for the search of a calibration without phases: its trials
        # load their data under the bounds of the call, never through os.environ.
        result = run_calibration_cli(target, bounds=environment.bounds, **options)
    return write_session_reports(result) if report else result


def calibrate_project(
    proj: Project,
    *,
    config_path: str | Path | None = None,
    parameters: dict[str, dict] | None = None,
    outputs: dict[str, dict] | None = None,
    objective_blocks: list[dict] | None = None,
    phases: list[dict] | None = None,
    protocol: str | dict | None = None,
    method: str | None = None,
    max_trials: int | None = None,
    save_runs: str | None = None,
    seed: int | None = None,
    phase: str | None = None,
    case: str | None = None,
    resume: bool = False,
    force: bool = False,
    dry_run: bool = False,
    workspace: str | Path | None = None,
    project: str | None = None,
    project_label: str | None = None,
    metric_fn: Any = None,
    objective: str | None = None,
    report: bool = True,
):
    """Route :meth:`Project.calibrate` to the runner its declaration calls for.

    The arguments are those of :meth:`Project.calibrate`, whose docstring says
    what each mode does and raises. ``report=False`` skips the session report.
    """
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()

    python_mode = {
        "outputs": outputs,
        "objective_blocks": objective_blocks,
        "phases": phases,
        "method": method,
        "max_trials": max_trials,
        "save_runs": save_runs,
        "seed": seed,
    }
    _refuse_misplaced_arguments(
        config_path=config_path, parameters=parameters, protocol=protocol, python_mode=python_mode
    )
    label = project_label if project_label is not None else project
    options = {
        "workspace": workspace,
        "metric_fn": metric_fn,
        "objective": objective,
        "resume": resume,
    }
    if config_path is not None:
        if case is not None:
            raise ConfigError(FROM_FILE)
        return calibrate_a_file(
            config_path,
            phase=phase,
            dry_run=dry_run,
            project=label,
            force=force,
            report=report,
            **options,
        )
    if not (parameters or protocol is not None or dry_run or force or resume or phase is not None):
        identical = _identical_session(proj, case)
        if identical is not None:
            return identical
    run = _in_memory_runner(
        proj, dry_run=dry_run, label=label, phase=phase, case=case, options=options
    )
    if protocol is not None:
        result = run(_protocol_calibration(proj, protocol))
    elif not parameters:
        result = _calibrate_embedded(
            proj, run, phase=phase, case=case, dry_run=dry_run, label=label, options=options
        )
    else:
        result = run(_declared_calibration(proj, parameters, python_mode, phase=phase))
    return write_session_reports(result) if report and not dry_run else result


def write_session_reports(result: Any) -> Any:
    """Write the report of each session directory of a finished calibration, and return it.

    The directories are the one of ``result`` and the one of each phase. A report is a
    render: one that fails warns and does not fail the calibration.
    """
    from hydromodpy.project.report import report_session
    from hydromodpy.results.session.descriptor import session_descriptor_path

    directories: list[Path] = []
    top = getattr(result, "session_dir", None)
    if top is not None:
        directories.append(Path(top))
    for phase in getattr(result, "phases", None) or ():
        phase_dir = getattr(phase.report, "session_dir", None)
        if phase_dir is not None:
            directories.append(Path(phase_dir))
    for directory in dict.fromkeys(directories):
        if not session_descriptor_path(directory).is_file():
            continue
        try:
            report_session(directory)
        except Exception as exc:  # a render never fails a finished search
            logger.warning("session report of %s not written: %s", directory.name, exc)
    return result


def _identical_session(proj: Project, case: str | None):
    """Return the report of a completed session identical to the calibration this project carries.

    The case is the one the runner would name: *case*, else the case of the file the
    project was built from, else the ``[simulation] name`` the configuration writes.
    ``None`` when the project carries no ``[calibration]`` or no session answers.
    """
    from hydromodpy.calibration.runners.document import identical_session
    from hydromodpy.workflow.solution_key import planned_solution_key

    if getattr(proj._cfg, "calibration", None) is None:
        return None
    source = proj._config_path
    return identical_session(
        planned_solution_key(proj._cfg, search=True),
        project_root=Path(proj._cfg.workspace.project_root),
        case=case,
        source=None if source is None else Path(source),
        document=proj.config.model_dump(mode="json", exclude_none=True, exclude_unset=True),
    )


def _refuse_misplaced_arguments(
    *,
    config_path: str | Path | None,
    parameters: dict[str, dict] | None,
    protocol: str | dict | None,
    python_mode: Mapping[str, Any],
) -> None:
    """Refuse the arguments a calibration of this mode would silently ignore."""
    from hydromodpy.core.exceptions import ConfigError

    if config_path is not None or not parameters:
        # The declaration comes from a file or from the project config, so
        # the Python-mode arguments have nothing to apply to.
        ignored = [name for name, value in python_mode.items() if value is not None]
        if ignored:
            raise ConfigError(
                f"Project.calibrate() ignores {', '.join(ignored)} when the calibration "
                "comes from config_path= or from the project config. Write them in the "
                "[calibration] section, or pass parameters= to declare the search in Python."
            )
    if protocol is not None and (config_path is not None or parameters):
        raise ConfigError(
            "Project.calibrate() takes protocol= alone: it builds on the parameters and "
            "outputs of this project's own [calibration] section and writes the phases. "
            "Drop config_path= and parameters=."
        )


def _in_memory_runner(
    proj: Project,
    *,
    dry_run: bool,
    label: str | None,
    phase: str | None,
    case: str | None,
    options: Mapping[str, Any],
) -> Callable[[Any], Any]:
    """Return the call that preflights and runs, or plans, a calibration held in memory."""
    from hydromodpy.calibration.runners.document import describe_dry_run
    from hydromodpy.calibration.runners.programmatic_runner import (
        run_calibration_programmatic,
    )
    from hydromodpy.core.exceptions import ConfigError

    def run(cfg: CalibrationConfig):
        _preflight_in_memory(proj, cfg)
        if dry_run:
            if proj._config_path is None:
                raise ConfigError(
                    "Project.calibrate(dry_run=True) needs a project built from a file."
                )
            return describe_dry_run(
                cfg, Path(proj._config_path).resolve(), workspace=options["workspace"]
            )
        return run_calibration_programmatic(
            cfg, project=proj, project_label=label, phase=phase, case=case, **options
        )

    return run


def _protocol_calibration(proj: Project, protocol: str | dict) -> CalibrationConfig:
    """The calibration a protocol writes over this project's own ``[calibration]``."""
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.calibration.protocols import expand_calibration_protocol
    from hydromodpy.calibration.runners.programmatic_runner import project_defaults_on

    document = proj.config.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    document = expand_calibration_protocol(
        {
            **document,
            "calibration": {**document.get("calibration", {}), "protocol": protocol},
        }
    )
    return CalibrationConfig.model_validate(project_defaults_on(document["calibration"], proj))


def _calibrate_embedded(
    proj: Project,
    run: Callable[[Any], Any],
    *,
    phase: str | None,
    case: str | None,
    dry_run: bool,
    label: str | None,
    options: Mapping[str, Any],
):
    """Calibrate the ``[calibration]`` section carried by this project's config.

    A fully in-memory ``HydroModPyConfig`` so calibrates without re-declaring
    ``parameters=`` (matches the TOML path). Phases declared on a project built
    from a file run from that file.
    """
    from hydromodpy.core.exceptions import CalibrationError, ConfigError, ConfigMissingError
    from hydromodpy.project.dispatch.workflow import no_such_phase
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()

    embedded = getattr(proj._cfg, "calibration", None)
    if embedded is None:
        raise ConfigMissingError(
            "Project.calibrate() requires either config_path=, parameters= "
            "(Python-mode declaration), or a [calibration] section in the "
            "project config."
        )
    declared = [decl.name for decl in (getattr(embedded, "phases", None) or [])]
    source = proj._config_path
    if declared and source is not None:
        from hydromodpy.calibration.preflight import preflight_launch
        from hydromodpy.calibration.runners.document import describe_dry_run, load_toml_calibration
        from hydromodpy.calibration.runners.staged_runner import run_staged_calibration

        if case is not None:
            raise ConfigError(FROM_FILE)
        target = Path(source).resolve()
        preflight_launch(target)
        if dry_run:
            return describe_dry_run(
                load_toml_calibration(target)[0], target, workspace=options["workspace"]
            )
        return run_staged_calibration(target, phase=phase, project=label, **options)
    if not declared and phase is not None:
        raise CalibrationError(no_such_phase("this configuration", phase))
    # A declaration on a project built in memory has no file to fork
    # each phase from: run_calibration_programmatic writes one next
    # to this project's sessions/ and runs the staged runner on it.
    return run(embedded)


def _declared_calibration(
    proj: Project,
    parameters: dict[str, dict],
    python_mode: Mapping[str, Any],
    *,
    phase: str | None,
) -> CalibrationConfig:
    """The calibration ``parameters=`` and the Python-mode arguments declare."""
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.calibration.runners.programmatic_runner import project_defaults_on
    from hydromodpy.core.exceptions import CalibrationError
    from hydromodpy.project.dispatch.workflow import no_such_phase

    if phase is not None and not python_mode["phases"]:
        raise CalibrationError(no_such_phase("this parameters= declaration", phase))

    payload: dict[str, object] = {"parameters": dict(parameters)}
    for key in (
        "method",
        "max_trials",
        "save_runs",
        "seed",
        "outputs",
        "objective_blocks",
        "phases",
    ):
        value = python_mode[key]
        if value is not None:
            payload[key] = value

    # The project defaults go in first: a validation window needs the calibration
    # window [metrics] window leaves it.
    cfg = CalibrationConfig.model_validate(project_defaults_on(payload, proj))
    # Completed from the target each parameter names, as the TOML route does,
    # so a bare K searches the log space its field declares and gets the
    # same method as the same file would.
    project_config = proj._cfg
    if project_config is not None:
        from hydromodpy.calibration.parameter_resolution import resolve_parameter_targets

        resolve_parameter_targets(cfg, project_config)
    return cfg


def _preflight_in_memory(project: Project, calibration: Any) -> None:
    """Run the launch preflight on a calibration held in memory, on this project.

    The project's configuration with ``calibration`` in place of its own, the
    project defaults written in as the run writes them. A project built in
    memory has no file, and the checks anchor on its root.
    """
    from hydromodpy.calibration.preflight import preflight_launch
    from hydromodpy.calibration.runners.programmatic_runner import with_project_defaults
    from hydromodpy.project.trial_pipeline import fill_trial_pipeline

    fill_trial_pipeline()

    config = getattr(project, "config", None)
    source = getattr(project, "_config_path", None)
    if source is None:
        # A project with no file anchors its checks on its root, where project.toml would be.
        source = project._ctx.config_path
    preflight_launch(source, config=config, calibration=with_project_defaults(calibration, project))


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
