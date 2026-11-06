"""The routing of a calibration: which runner a declaration goes to.

:meth:`Project.calibrate <hydromodpy.project.facade.Project.calibrate>` and
``hmp.calibrate`` on a path end here. A TOML file goes to the staged runner when
it declares ``[[calibration.phases]]``, to the CLI runner otherwise
(:func:`calibrate_a_file`). A declaration held in memory (``parameters=``, a
``protocol=``, or the ``[calibration]`` section of the project config) goes to the
programmatic runner, on the project itself (:func:`calibrate_project`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibrationConfig
    from hydromodpy.project.facade import Project

FROM_FILE = (
    "case= names the session of a calibration held in memory; a file names its "
    "case with [simulation] name."
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
):
    """Run the calibration a TOML file declares. It needs no :class:`Project`."""
    from hydromodpy.calibration.preflight import preflight_launch
    from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
    from hydromodpy.calibration.runners.document import describe_dry_run, load_toml_calibration
    from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
    from hydromodpy.core.exceptions import CalibrationError
    from hydromodpy.project.dispatch.workflow import (
        calibration_phases_or_raise,
        declared_calibration_phases,
        no_such_phase,
    )

    target = Path(config_path).expanduser().resolve()
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
    options = {
        "workspace": workspace,
        "project": project,
        "metric_fn": metric_fn,
        "objective": objective,
        "resume": resume,
    }
    if declared_phases:
        return run_staged_calibration(target, phase=phase, **options)
    return run_calibration_cli(target, **options)


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
    dry_run: bool = False,
    workspace: str | Path | None = None,
    project: str | None = None,
    project_label: str | None = None,
    metric_fn: Any = None,
    objective: str | None = None,
):
    """Route :meth:`Project.calibrate` to the runner its declaration calls for.

    The arguments are those of :meth:`Project.calibrate`, whose docstring says
    what each mode does and raises.
    """
    from hydromodpy.core.exceptions import ConfigError

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
        return calibrate_a_file(config_path, phase=phase, dry_run=dry_run, project=label, **options)
    run = _in_memory_runner(
        proj, dry_run=dry_run, label=label, phase=phase, case=case, options=options
    )
    if protocol is not None:
        return run(_protocol_calibration(proj, protocol))
    if not parameters:
        return _calibrate_embedded(
            proj, run, phase=phase, case=case, dry_run=dry_run, label=label, options=options
        )
    return run(_declared_calibration(proj, parameters, python_mode, phase=phase))


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

    config = getattr(project, "config", None)
    source = getattr(project, "_config_path", None)
    if source is None:
        root = getattr(getattr(config, "workspace", None), "project_root", None)
        source = Path(root if root is not None else Path.cwd()) / "project.toml"
    preflight_launch(source, config=config, calibration=with_project_defaults(calibration, project))
