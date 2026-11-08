"""Reading a calibration document: the TOML, its defaults, the names it resolves.

Everything the search entries need before a session opens: the loader of
``calibration.toml``, the project defaults written into it, the stream-geometry
paths, the method and cost names a session journals, and the dry-run plan.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import (
    CalibPhaseDecl,
    CalibrationConfig,
)
from hydromodpy.calibration.persistence import (
    DEFAULT_PHASE,
)
from hydromodpy.calibration.protocols import (
    expand_calibration_protocol,
)
from hydromodpy.calibration.runners.session import (
    calibration_case_name,
    project_root_for,
)
from hydromodpy.core.exceptions import (
    CalibrationError,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.result_dirs import run_dir_rel, session_dir_rel

if TYPE_CHECKING:
    pass


logger = get_logger(__name__)


def load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    """Return the validated ``[calibration]`` section of ``path`` and the raw TOML.

    Read through ``base_config`` resolution, the same way the pipeline reads the
    file. Reading it raw instead made a ``[calibration]`` section inherited from
    a base configuration invisible here while the pipeline resolved it, so a
    calibration overlay of two lines failed on "No [calibration] section".

    The legacy keys are migrated in memory first, as the project loader does,
    so a file ``hmp doctor --fix-config <file>`` would fix also runs unfixed.
    """
    from pydantic import ValidationError

    from hydromodpy.calibration.runners.trial import trial_pipeline
    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.core.toml_io.error_locator import format_validation_error

    try:
        raw = trial_pipeline().load_document(path)
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    if "calibration" not in raw:
        raise ValueError(f"No [calibration] section in {path}")
    try:
        raw = expand_calibration_protocol(raw)
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    try:
        cfg = CalibrationConfig.model_validate(_with_project_defaults(raw, path))
    except ValidationError as exc:
        # The reader of this message writes TOML and does not read Python, so it
        # has to name the file, the line and the key rather than the model.
        raise ConfigError(
            format_validation_error(exc, source_path=path, loc_prefix=("calibration",))
        ) from None
    resolve_stream_geometry_paths(cfg, path)
    _resolve_parameter_names(cfg, path)
    return cfg, raw


def _with_project_defaults(raw: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """Return the raw ``[calibration]`` table with ``[site] gauge`` and ``[metrics] window`` written in."""
    from hydromodpy.calibration.config import apply_project_defaults
    from hydromodpy.core.exceptions import ConfigError

    site = raw.get("site")
    metrics = raw.get("metrics")
    try:
        return apply_project_defaults(
            raw["calibration"],
            site_gauge=site.get("gauge") if isinstance(site, Mapping) else None,
            metrics_window=metrics.get("window") if isinstance(metrics, Mapping) else None,
        )
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None


def _resolve_parameter_names(cfg: CalibrationConfig, config_path: Path) -> None:
    """Complete every parameter from the target it points at.

    The catalog is read off the resolved project configuration, which this
    section is one part of, so the project is built here. Anchored on the same
    file, and idempotent like :func:`resolve_stream_geometry_paths`, because a
    declaration is only ever completed where the file said nothing.
    """
    from hydromodpy.calibration.parameter_resolution import (
        UnresolvedParameterName,
        resolve_parameter_targets,
    )

    if not getattr(cfg, "parameters", None):
        return
    from hydromodpy.calibration.runners.trial import trial_pipeline

    try:
        project_cfg = trial_pipeline().load_config(config_path)
    except UnresolvedParameterName:
        # The names are the file's own business and the message already says which
        # one is wrong. Swallowing it here left the run to fail three steps later
        # on "must declare a 'path'", which accuses the form this file no longer
        # has to write.
        raise
    except Exception:
        # A file that is not a runnable project has nothing to resolve against.
        # Loading must stay possible anyway: `--list-phases` runs on a machine
        # holding none of the data, and the parameter without a path is refused
        # by the space and the preflight with their own message.
        logger.debug("No project configuration to resolve parameter names against", exc_info=True)
        return
    resolve_parameter_targets(cfg, project_cfg)


def resolve_stream_geometry_paths(cfg: CalibrationConfig, config_path: Path) -> None:
    """Anchor every relative map path of an output to the file that declares it.

    Both maps are anchored: ``map.complete`` and ``map.permanent``.

    A path in a TOML is relative to that TOML, the way ``base_config`` is, and a
    bare filename falls back to ``<project>/data/hydrography/`` like every other
    data path. Reading it against the working directory instead made the run
    depend on where it was launched from.

    Called from :func:`run_calibration_core`, where the CLI, the staged and the
    programmatic routes converge, and again from :func:`load_toml_calibration`
    for the readers that never run a calibration. Running twice is harmless: the
    second pass sees absolute paths and skips them.

    A path that resolves to nothing is left exactly as declared. Loading a
    configuration must not require its data to be present: ``--list-phases`` has
    to work on a machine that holds none of it, and the criterion already names
    the file it could not read.
    """
    base = config_path.expanduser().resolve().parent
    for name, role, candidate in cfg.map_files():
        if candidate.is_absolute():
            continue
        found = next(
            (
                trial
                for root in (base, base.parent, base.parent.parent)
                for trial in (root / candidate, root / "data" / "hydrography" / candidate.name)
                if trial.exists()
            ),
            None,
        )
        if found is not None:
            setattr(cfg.outputs[name].map, role, found.resolve())


def session_cost_name(cfg: CalibrationConfig, phase: CalibPhaseDecl | None = None) -> str:
    """Return the metric a search scores on, as its objective blocks name it.

    A search scored through blocks names their metrics, joined by ``" + "``
    when there are several. A single-metric search names its ``objective``.
    Without ``phase``, a staged session keeps the value and the window of its
    last phase, so it names what that phase scores.
    """
    last = phase if phase is not None else (cfg.phases[-1] if cfg.phases else None)
    if last is not None and last.is_single_metric:
        return str(last.objective or cfg.objective)
    metrics = [str(block.metric) for block, _weight in cfg.objective_blocks_for(last)]
    if metrics:
        return " + ".join(dict.fromkeys(metrics))
    return str(cfg.objective)


def declared_window_text(cfg: CalibrationConfig, phase: CalibPhaseDecl | None = None) -> str:
    """Say the window a search scores on, as the file declares it.

    ``cfg`` is the ``[calibration]`` section and ``phase`` one of its phases,
    ``None`` for the section's own search. The phase's ``window``,
    else the section's; a transient phase carries ``[metrics] window`` there
    once the project defaults are applied. A bound left open reads as the
    first or last paired sample. Without a window, the whole run is scored.
    """
    window = getattr(cfg, "window", None)
    if phase is not None and phase.window is not None:
        window = phase.window
    if window is not None and (window.start or window.end):
        start = window.start or "the first paired sample"
        end = window.end or "the last paired sample"
        return f"window {start} to {end}"
    return "no window, all of the run"


def with_its_method(cfg: CalibrationConfig) -> CalibrationConfig:
    """Return ``cfg`` with the method it runs written in.

    Itself when the file names one. Otherwise a copy carrying the method its
    criteria call for (``CalibrationConfig.method_for``), so every reader after
    this point, the session journal and the params hash included, sees the name
    that ran.
    """
    method, reason = cfg.method_for()
    if reason is None:
        return cfg
    logger.info("The calibration names no method and runs %s: %s.", method, reason)
    return cfg.model_copy(update={"method": method})


def refuse_an_objective_that_is_not_an_entry_point(objective: str | None) -> None:
    """Refuse an ``objective=`` that does not name a Python callable.

    ``objective=`` is an entry point specification, ``"module.path:callable"``,
    on all three routes. A metric NAME handed to it was silently ignored: a
    caller asking for ``objective="kge"`` on a document declaring ``nse``
    calibrated on ``nse`` and nothing said so.

    Called at the entry of each public route rather than where the value is
    consumed. Two reasons, both measured. A staged run that reuses its phases
    from disk never reaches the consumer, so the value traveled into the reuse
    fingerprint without ever being checked. And the consumer sits after
    ``prepare_trials``, so a refused call used to pay the whole geographic,
    mesh and data prefix first, and leave a fresh catalog, a lock and a WAL
    behind in a workspace where no calibration ever ran.
    """
    if not objective or ":" in objective:
        return
    raise CalibrationError(
        f"objective={objective!r} is not a 'module.path:callable' entry point. "
        "objective= names a Python callable to build the metric extractor with, and "
        "a metric name is not one. Declare the metric where the document declares "
        "metrics: [calibration] objective for the single-metric route, a block's "
        "'metric' for the composite one, or objective_blocks=[{'name': ..., "
        "'metric': ..., 'uses_outputs': [...]}] when calling Project.calibrate, "
        "which passes no [calibration] table."
    )


def load_calibration_document(
    config_path: Path | str, workspace: Path | str | None
) -> tuple[Path, Path, CalibrationConfig, dict, str]:
    """Return the file, the project root, the section, the raw TOML and the case of a document."""
    cfg_path = Path(config_path).expanduser().resolve()
    project_root = project_root_for(cfg_path, workspace)
    cfg, raw = load_toml_calibration(cfg_path)
    return cfg_path, project_root, cfg, raw, calibration_case_name(cfg_path)


def describe_dry_run(
    cfg: CalibrationConfig, cfg_path: Path, *, workspace: Path | str | None = None
) -> dict[str, Any]:
    """Return what the calibration of ``cfg`` would do, without writing anything.

    The version is the one the session would reserve now
    (:func:`~hydromodpy.results.catalog.registration.next_version_dirname`); the
    promoted run takes the same directory name under ``runs/``.
    """
    from hydromodpy.results.catalog.registration import next_version_dirname

    project_root = project_root_for(cfg_path, workspace)
    case = calibration_case_name(cfg_path)
    dirname = next_version_dirname(project_root, case)
    phases = [
        {
            "name": decl.name,
            "parameters": list(decl.parameters),
            "max_trials": cfg.max_trials_for(decl),
            "window": declared_window_text(cfg, decl),
        }
        for decl in cfg.phases or ()
    ] or [
        {
            "name": DEFAULT_PHASE,
            "parameters": list(cfg.parameters),
            "max_trials": cfg.max_trials,
            "window": declared_window_text(cfg),
        }
    ]
    return {
        "case": case,
        "project_root": str(project_root),
        "session_dir": session_dir_rel(dirname),
        "run_dir": run_dir_rel(dirname),
        "version": dirname,
        "phases": phases,
        "solves_in_parallel": max(
            [cfg.parallel_for(decl) for decl in cfg.phases or ()] or [cfg.parallel]
        ),
        "save_runs": cfg.save_runs,
    }


def session_method(cfg: CalibrationConfig) -> str:
    """Return the search method a session journals.

    The method the document runs (``CalibrationConfig.method_for``), chosen
    from what the search scores when the file names none. A staged document
    names the method of each phase, joined in declaration order.
    """
    if cfg.phases:
        return " + ".join(cfg.method_for(phase)[0] for phase in cfg.phases)
    return cfg.method_for()[0]


def metrics_window_of(raw: Mapping[str, Any] | None) -> Any:
    """Return ``[metrics] window`` of a document, or None."""
    metrics = None if raw is None else raw.get("metrics")
    return metrics.get("window") if isinstance(metrics, Mapping) else None


def site_name(raw: Mapping[str, Any]) -> str | None:
    """Return ``[site] name`` of a document, or None."""
    site = raw.get("site")
    name = site.get("name") if isinstance(site, Mapping) else None
    return str(name) if name else None
