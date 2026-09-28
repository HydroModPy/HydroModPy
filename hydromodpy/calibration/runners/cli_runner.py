"""CLI entry point ``hmp calibrate <calibration.toml>``.

Workflow:

1. Load the TOML and validate the ``[calibration]`` section into a
   :class:`CalibrationConfig`.
2. Resolve the evaluator ``[calibration].evaluator`` names, through
   :mod:`hydromodpy.calibration.evaluation.registry`. What turns a parameter
   sample into a cost lives behind that name, and this module does not know
   which implementation answers.
3. Prepare the downstream pipeline once via :func:`prepare_trials` **when the
   resolved evaluator declares it needs one**, reusing the earliest-affected-step
   optimisation so setup phases do not re-run per trial. An evaluator that
   replaces the model skips this entirely and is handed ``trial_ctx=None``.
4. Drive the ask/tell loop through :class:`CalibrationEngine`, which calls the
   evaluator once per suggestion. For the in-tree ``hydromodpy_pipeline``
   evaluator that means forking the prepared context, running the solver in
   lightweight mode, and extracting the objective in RAM.
5. Persist every iteration into the DuckDB ``calibration_iterations``
   table (``sim_id`` left ``NULL`` by default).
6. Honor ``save_runs`` -- ``"best_n"`` / ``"all"`` promote the chosen
   trials through :mod:`hydromodpy.calibration.runners.promotion`. Promotion
   replays the pipeline, so it is refused outright when no model was prepared.

The ``objective`` argument is a Python escape hatch
(``"module.path:fn"``) for users who need a custom scalar -- the TOML
``[calibration].objective`` + ``[calibration].variable`` pair already
covers the standard NSE / KGE / RMSE cases.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig, scoring_window_bounds
from hydromodpy.calibration.evaluation import TrialRequest
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.optim.cache import ParamsHashCache
from hydromodpy.calibration.optim.diagnostics import correlated_parameter_pairs
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.objective import (
    mean_objective_block_shares,
    objective_block_shares,
)
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
    engine_traits,
)
from hydromodpy.calibration.optim.progress_reporter import ConsoleProgressReporter
from hydromodpy.calibration.optim.stopping import resolve_budget, stopping_kwargs
from hydromodpy.calibration.optim.tolerance import (
    IntervalWidth,
    ParameterInterval,
    tolerance_intervals,
)
from hydromodpy.calibration.persistence import (
    CalibrationStoreFactory,
    default_store_factory,
)
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.calibration.runners.failure_watch import ConsecutiveFailureWatch
from hydromodpy.calibration.runners.promotion import promote_iterations
from hydromodpy.calibration.runners.restarts import run_restarts
from hydromodpy.calibration.runners.sandbox import keep_trial_scratch
from hydromodpy.calibration.runners.state import (
    SessionChain,
    build_cache_context,
    load_metric_fn_entry_point,
    preload_hash_cache,
    space_from_config,
)
from hydromodpy.calibration.runners.state import (
    override_paths as resolve_override_paths,
)
from hydromodpy.calibration.runners.trial import (
    TrialMetricFn,
    prepare_trials,
)
from hydromodpy.core.exceptions import (
    CalibrationError,
    ObjectiveError,
    UncertaintyNotAvailableError,
)
from hydromodpy.core.interrupts import TerminationRequested, terminate_as_interrupt
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.engine import CalibrationSession
    from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
    from hydromodpy.calibration.report import CalibrationReport
    from hydromodpy.calibration.runners.trial import TrialContext

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# TOML loader
# ---------------------------------------------------------------------------


def load_toml_calibration(path: Path) -> tuple[CalibrationConfig, dict]:
    """Return the validated ``[calibration]`` section of ``path`` and the raw TOML.

    Read through ``base_config`` resolution, the same way the pipeline reads the
    file. Reading it raw instead made a ``[calibration]`` section inherited from
    a base configuration invisible here while the pipeline resolved it, so a
    calibration overlay of two lines failed on "No [calibration] section".
    """
    from pydantic import ValidationError

    from hydromodpy.core.exceptions import ConfigError
    from hydromodpy.core.toml_io.error_locator import format_validation_error
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    raw = load_toml_with_base_config(path)
    if "calibration" not in raw:
        raise ValueError(f"No [calibration] section in {path}")
    try:
        raw = expand_calibration_protocol(raw)
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    try:
        cfg = CalibrationConfig.model_validate(raw["calibration"])
    except ValidationError as exc:
        # The reader of this message writes TOML and does not read Python, so it
        # has to name the file, the line and the key rather than the model.
        raise ConfigError(
            format_validation_error(exc, source_path=path, loc_prefix=("calibration",))
        ) from None
    resolve_stream_geometry_paths(cfg, path)
    _resolve_parameter_names(cfg, path)
    return cfg, raw


def _resolve_parameter_names(cfg: CalibrationConfig, config_path: Path) -> None:
    """Complete every parameter from the target it points at.

    The catalogue is read off the resolved project configuration, which this
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
    from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider

    try:
        project_cfg = get_root_config_provider().from_toml(config_path)
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
    """Anchor every relative ``stream_geometry_path`` to the file that declares it.

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
    for output in cfg.outputs.values():
        # An output that names its source carries no path, the model refusing both
        # at once, so the check below already skips it. It also skips every output
        # that has no such field at all, which is every support but 'network'.
        declared = getattr(output, "stream_geometry_path", None)
        if not declared or Path(declared).is_absolute():
            continue
        candidate = Path(declared)
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
            output.stream_geometry_path = str(found.resolve())


def _api_isolation_needed(parallel: int) -> bool:
    """Whether api solves must be isolated in a child process this session.

    True for any PARALLEL session. The decision is on parallelism alone, NOT the
    declared ``mf6_runner``: the effective runner is resolved at build time and an
    exposed-band (marnage) coupling forces the ``api`` runner even when the config
    leaves ``mf6_runner`` at its ``subprocess`` default. ``_run_via_api`` is
    reached ONLY for that effective api runner, so isolating whenever trials run
    concurrently is correct (and a no-op for subprocess solves, which never reach
    it). A serial session keeps the in-process api path (live progress bar, no
    spawn). Isolating gives each concurrent libmf6 its own process, so the global
    Fortran INPUT state never collides across threads.
    """
    return parallel > 1


def _assert_bounds_valid(trial_ctx: Any, space: ParameterSpace) -> None:
    """Reject calibration bounds that fall outside the target field's valid range.

    Field validation (e.g. a specific yield must stay in its physical range)
    only fires when the process is built, not on plain attribute assignment, so
    a bad bound is silent until each trial that samples there crashes at fork.
    This probe injects every parameter's lower and upper bound into a copy of the
    config and rebuilds the flow once; a build failure means the bound is out of
    range, so fail fast with a clear message instead of losing trials.

    Only flow-targeted parameters are probed (the common case: K, Sy, Ss,
    bedleak, ...). A base flow that already fails to build is left for the run to
    surface, so a pre-existing config issue is never blamed on a bound.
    """
    from hydromodpy.calibration.optim.parameters import apply_parameter_to_config
    from hydromodpy.physics.flow import Flow

    base_cfg = getattr(trial_ctx, "base_cfg", None) or getattr(
        getattr(trial_ctx, "ctx", None), "cfg", None
    )
    if base_cfg is None or not hasattr(base_cfg, "model_copy"):
        return
    try:
        Flow(config=base_cfg.flow)
    except Exception:
        return
    for param in space:
        if param.effective_path is None or not param.effective_path.startswith("flow."):
            continue
        for label, value in (("lower", param.lower), ("upper", param.upper)):
            probe = base_cfg.model_copy(deep=True)
            apply_parameter_to_config(probe, param, float(value))
            try:
                Flow(config=probe.flow)
            except Exception as exc:
                lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()]
                detail = next(
                    (ln for ln in lines if "outside" in ln.lower()),
                    lines[-1] if lines else str(exc),
                )
                raise ValueError(
                    f"calibration parameter {param.name!r} {label} bound {value:g} is outside "
                    f"the valid range for {param.effective_path!r}: {detail}"
                ) from exc


_CONDUCTIVITY_PARAM_IDS: tuple[str, ...] = ("K", "Kx", "Ky", "Kz")


def moves_a_hydraulic_conductivity(paths: Iterable[str | None]) -> bool:
    """True when one of ``paths`` addresses a hydraulic conductivity field.

    Matches ``flow.param.K``, ``Kx``, ``Ky`` or ``Kz`` at any depth under it
    (a per-zone value included) and nothing else: ``flow.param.Ss`` shares the
    ``flow.param`` prefix but not the id. Shared by the two guards below and by
    :mod:`hydromodpy.calibration.preflight`, which faces the same declared
    parameters before a project config resolves into a live ``ParameterSpace``.
    """
    for path in paths:
        if path is None:
            continue
        parts = str(path).split(".")
        if len(parts) >= 3 and parts[0] == "flow" and parts[1] == "param":
            if parts[2] in _CONDUCTIVITY_PARAM_IDS:
                return True
    return False


def network_outputs_scored(
    outputs: Mapping[str, Any],
    *,
    variable: str | None = None,
    objective: str | None = None,
) -> list[str]:
    """Return the names of the network outputs one search scores.

    ``outputs`` are the outputs the search reads. A single-metric search, its
    own ``variable`` and ``objective`` instead of blocks, passes both: the
    staged runner empties its ``outputs`` (``_phase_config`` in
    ``staged_runner.py``), so its ``variable`` is the output, and only a
    network estimator (``NETWORK_ESTIMATORS``) scores a network output. The
    runner guards and :mod:`hydromodpy.calibration.preflight` both resolve a
    search through this, so a check made before the run and the one made at
    the first solve read the same outputs.
    """
    names = sorted(
        name for name, output in outputs.items() if getattr(output, "support", None) == "network"
    )
    if names or not variable:
        return names
    from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS

    return [variable] if str(objective) in NETWORK_ESTIMATORS else []


def _network_outputs_of(cfg: CalibrationConfig) -> list[str]:
    """Return the network outputs the search ``cfg`` describes scores, by name.

    A configuration with no block is a single-metric search, whether the
    whole-file route or a phase narrowed by the staged runner.
    """
    if cfg.objective_blocks:
        return network_outputs_scored(cfg.outputs)
    return network_outputs_scored(cfg.outputs, variable=cfg.variable, objective=cfg.objective)


def _assert_network_conductance_proportional(
    cfg: CalibrationConfig, trial_ctx: Any, space: ParameterSpace
) -> None:
    """Face a fixed drain conductance with what a K-moving network criterion needs.

    The criterion calibrates the ratio K/R, and that only holds, while a search
    moves K, if the drain conductance follows the conductivity:
    ``C = K * cell_area / drain_bed_thickness_m`` on both MODFLOW backends (the
    fallback in ``drain_conductance.hk_fallback_drain_conductance``),
    ``C = K * cell_area`` on Boussinesq. All three apply it only when the
    configured conductance is not strictly positive. A fixed value breaks the
    invariance from a factor 1.05 onwards, and the run still completes and
    returns a number, so a K-moving search is refused before the first solve.

    A search that drives some other parameter with the conductance fixed is a
    different question: the network criterion can be pointed at any parameter,
    and nothing here can say whether that search means something, so it gets a
    warning instead of a refusal, naming that its result depends on the chosen
    conductance.

    The outputs are resolved by :func:`network_outputs_scored`, so a phase
    scored through its own ``variable``/``objective`` is seen even though the
    staged runner empties its ``cfg.outputs``.
    """
    network_outputs = _network_outputs_of(cfg)
    if not network_outputs:
        return
    flow = getattr(getattr(trial_ctx, "base_cfg", None), "flow", None)
    if flow is None or "drainage" not in flow.active_bc:
        return
    boundary = flow.bc.get("drainage")
    if boundary is None or boundary.value is None or float(boundary.value) <= 0.0:
        return
    names = ", ".join(repr(name) for name in network_outputs)
    detail = (
        f"flow.bc.drainage.value is {float(boundary.value):g} {boundary.units}, a fixed "
        "drain conductance (the fallback, C = K * cell_area / drain_bed_thickness_m in "
        "hydromodpy/solver/modflow_common/drain_conductance.py, only applies when the "
        "configured value is not strictly positive)."
    )
    if moves_a_hydraulic_conductivity(param.effective_path for param in space):
        raise ObjectiveError(
            f"Network calibration output(s) {names}: {detail} The criterion calibrates "
            "the ratio K/R, which holds only while the conductance follows the K this "
            "search moves. A fixed conductance leaves that invariance from a factor 1.05 "
            "onwards, so the calibrated ratio would mean nothing. Set the value to zero."
        )
    logger.warning(
        "Network calibration output(s) %s: %s This search does not move a hydraulic "
        "conductivity, so the K/R invariance is not at stake, but the result still "
        "depends on the conductance chosen.",
        names,
        detail,
    )


_ADVANCED_PACKAGE_LABEL: Mapping[str, str] = {
    "sfr": "SFR (routed stream reaches)",
    "lake": "LAK",
    "reservoir": "LAK",
}
"""Display label for the active_bc ids the registry declares 'advanced_package'.

RIV and GHB would join this table -- neither ties its conductance to K by
construction -- but neither is a constructible ``flow.active_bc`` id today:
``FLOW_BOUNDARY_DEFINITIONS`` (``boundary_condition_registry.py``) declares no
'riv' and no 'ghb' entry, so ``flow.active_bc = ["riv"]`` is refused at config
load, before a calibration ever reaches this guard.
"""


def _active_advanced_packages(flow: Any) -> list[str]:
    """Return the active ``flow.active_bc`` ids in the 'advanced_package' family.

    That family is exactly the boundaries whose conductance a package builds
    from its own data, never derived from K: SFR and LAK today.

    DRN is not in it: its family is 'head_dependent_exchange', and its
    conductance falls back to ``K * cell_area / drain_bed_thickness_m``
    whenever none is configured (``drain_conductance.py``), so it already
    follows K.

    CHD is not in it either: its family is 'dirichlet', fixing a head rather
    than a conductance. Dividing the steady-state flow equation by K leaves a
    fixed head unchanged, so K/R stays intact under any CHD whatever K does.
    """
    from hydromodpy.physics.flow.boundary_condition_registry import boundary_definition

    offenders: list[str] = []
    for bc_id in getattr(flow, "active_bc", None) or ():
        definition = boundary_definition(bc_id)
        if definition is not None and definition.family == "advanced_package":
            offenders.append(bc_id)
    return offenders


def release_package_conductance_conflict(
    network_outputs: Sequence[str], flow: Any, *, moves_k: bool
) -> str | None:
    """Return the refusal message for a K-moving network search over a fixed
    release-package conductance, or ``None`` when the search can trust it.

    ``network_outputs`` are the names :func:`network_outputs_scored` resolves
    for the search. Shared by the runner guard, which raises this as an
    :class:`ObjectiveError`, and by :mod:`hydromodpy.calibration.preflight`,
    which reports the same text as an error finding for ``hmp calibrate
    --check`` before any solve pays for the mistake.
    """
    if not moves_k or flow is None:
        return None
    if not network_outputs:
        return None
    offending_ids = _active_advanced_packages(flow)
    if not offending_ids:
        return None
    labels = sorted({_ADVANCED_PACKAGE_LABEL.get(bc_id, bc_id.upper()) for bc_id in offending_ids})
    named = " and ".join(labels)
    names = ", ".join(repr(name) for name in network_outputs)
    return (
        f"Network calibration output(s) {names} move a hydraulic conductivity while "
        f"{named} is active. DRN's conductance follows K, through the "
        "K * cell_area / drain_bed_thickness_m fallback; CHD fixes a head, so dividing "
        f"the flow equation by K leaves it unchanged. {named} builds its own conductance "
        "from its own package data instead, so the K/R this search calibrates would not "
        f"mean what the criterion assumes. A K-proportional conductance for {named} is "
        "future work."
    )


def _assert_active_release_packages_follow_k(
    cfg: CalibrationConfig, trial_ctx: Any, space: ParameterSpace
) -> None:
    """Refuse a K-moving network search next to an SFR or LAK with a fixed conductance.

    Checked before the first solve, same as
    :func:`_assert_network_conductance_proportional`, and on the outputs the
    same resolution reads: a single-metric phase scoring a network output
    through its own ``variable`` is seen here too. A run with one of these
    packages active still completes and still returns a K/R that does not
    mean what the criterion assumes.
    """
    flow = getattr(getattr(trial_ctx, "base_cfg", None), "flow", None)
    moves_k = moves_a_hydraulic_conductivity(param.effective_path for param in space)
    message = release_package_conductance_conflict(_network_outputs_of(cfg), flow, moves_k=moves_k)
    if message is not None:
        raise ObjectiveError(message)


def _search_space_payload(space: ParameterSpace) -> dict[str, Any]:
    """Return the searched bounds, one entry per parameter, as plain data.

    Written into the session journal so the frozen search space is readable
    next to the trials it produced, without opening the index.
    """
    return {
        param.name: {
            "bounds": [param.lower, param.upper],
            "transform": param.transform,
            "target": param.effective_path,
            "units": param.units,
        }
        for param in space
    }


def _session_config_payload(cfg: CalibrationConfig, evaluator: object) -> dict[str, Any]:
    """Return the configuration a session records, with what was resolved on it.

    A document that names no evaluator and no forward model still runs one of
    each, and the defaults are exactly the case a first study hits. Recording
    the raw field would journal ``None`` beside trials produced by a named
    class, so the session would not say what ran. The ids come off the built
    evaluator, which is the object that answered, never off the document.
    """
    payload = cfg.model_dump()
    payload["evaluator"] = getattr(evaluator, "evaluator_id", None) or cfg.evaluator
    forward_model = getattr(evaluator, "forward_model_id", None)
    if forward_model is not None:
        payload["forward_model"] = forward_model
    return payload


def _persist_observed_for_report(catalog: Any, trial_ctx: Any, variable: str) -> None:
    """Store the calibration observations so the report can draw obs-vs-sim.

    The promoted run writes the simulated series to the catalog; the matching
    observed series is sim-independent, so it lands once in the ``observations``
    table keyed by station. Only the lake-level family is wired today; the
    observed station is prefixed ``lake:<id>`` to line up with the simulated
    LAK stage station.
    """
    if variable != "lake_level":
        return
    ctx = getattr(trial_ctx, "ctx", None)
    write = getattr(catalog, "write_observations", None)
    if ctx is None or write is None:
        return
    from hydromodpy.calibration.metrics.series import load_observed

    for obs in load_observed(ctx, "lake_level"):
        station = obs.station_id if obs.station_id.startswith("lake:") else f"lake:{obs.station_id}"
        try:
            write(station, "lake_level", obs.series, unit="m", quality="observed")
        except Exception as exc:
            logger.warning("Could not persist observed lake level %s for report: %s", station, exc)


# ---------------------------------------------------------------------------
# Core loop (caller-agnostic)
# ---------------------------------------------------------------------------


def _release_session_scratch(trial_ctx: TrialContext | None) -> None:
    """Drop the preprocessing tree the session shared across its trials.

    Trials skip the setup steps and read the tree built once for the session,
    so no trial may delete it; and only a *promoted* run reaches the export
    step that normally does. A session that promotes nothing therefore used to
    leave hundreds of MB of DEM and flow rasters under ``.hmp/scratch``. This
    runs on every exit path (success, failure, SIGINT) and never raises.

    ``None`` when the named evaluator prepared no model: nothing was built, so
    there is nothing to release.
    """
    from hydromodpy.spatial.geographic.store_ingestion import cleanup_stable_folder

    if trial_ctx is None:
        return
    geographic = getattr(getattr(trial_ctx.ctx, "setup", None), "geographic", None)
    if geographic is None:
        return
    geographic_cfg = getattr(getattr(trial_ctx, "base_cfg", None), "geographic", None)
    keep = keep_trial_scratch() or bool(getattr(geographic_cfg, "write_intermediates", False))
    try:
        cleanup_stable_folder(geographic, keep=keep)
    except Exception:  # noqa: BLE001 - cleanup never decides the session outcome
        logger.warning("Could not remove the calibration session scratch", exc_info=True)


def calibration_trace(
    history: Iterable[Any],
    values_by_trial: Mapping[int, Mapping[str, float]],
) -> list[dict[str, Any]]:
    """Return the session history in the shape the diagnostics read.

    The cost travels under ``objective_value``, which the diagnostics know as a
    meta column. Under any other name it is taken for one more calibrated
    parameter, and a single-parameter search then reports the parameter as
    correlated with its own cost.
    """
    return [
        {
            "parameters": dict(values_by_trial[item.trial_id]),
            "objective_value": item.objective_value,
        }
        for item in history
        if item.trial_id in values_by_trial
    ]


def _tolerance_intervals_or_none(
    trace: list[dict[str, Any]],
    names: list[str],
    space: ParameterSpace,
    width: IntervalWidth,
) -> list[ParameterInterval]:
    """Return the interval around each calibrated value, or nothing.

    A criterion solved at zero, such as the stream-network gap, has no fraction
    of itself to take, so a relative tolerance means nothing there. Reporting
    nothing is the honest answer rather than a number under a rule nobody chose,
    and the run says which line turns it back on. The same holds for one mesh
    cell no trial measured, and for a relative width on network distances.
    """
    if width.tolerance is None:
        logger.warning(
            "No interval was reported around the calibrated values: the width is one "
            "mesh cell, and no trial measured the mesh. Write [calibration.uncertainty] "
            "tolerance in metres to get one."
        )
        return []
    if width.mode == "relative" and width.on_distances:
        logger.warning(
            "No interval was reported around the calibrated values: mode = 'relative' "
            "reads the width as a fraction of the best cost, and this search is scored "
            "only on network distances, in metres, where a fraction has no meaning. "
            "Write mode = 'absolute' with a tolerance in metres, or leave both unwritten "
            "for one mesh cell."
        )
        return []
    bounds = {param.name: (param.lower, param.upper) for param in space}
    try:
        return tolerance_intervals(
            trace,
            names,
            bounds=bounds,
            tolerance=float(width.tolerance),
            mode=width.mode,
        )
    except ValueError as exc:
        logger.warning(
            "No interval was reported around the calibrated values: %s Write "
            '[calibration.uncertainty] mode = "absolute" with a tolerance in the unit '
            "of the cost to get one.",
            exc,
        )
        return []


def _cell_measured_by_the_criterion(results: Iterable[EvaluationResult | None]) -> float | None:
    """Return the mesh cell the network criterion measured on a trial, or ``None``.

    Every trial of one search scores the same mesh, so the first finite value
    is the cell. ``None`` when no trial scored a network output.
    """
    for result in results:
        if result is None:
            continue
        for key, value in (result.components or {}).items():
            if str(key).endswith(".cell_spacing_m") and math.isfinite(float(value)):
                return float(value)
    return None


def _width_read_off_the_trials(
    width: IntervalWidth, best: EvaluationResult | None, history: Iterable[EvaluationResult]
) -> IntervalWidth:
    """Return ``width`` with its one mesh cell measured, and log the width read."""
    if width.tolerance is None:
        cell = _cell_measured_by_the_criterion([best, *history])
        if cell is not None:
            width = width.measured(cell)
    where = {
        "phase": "written in the phase",
        "section": "written in [calibration.uncertainty]",
        "default": f"default, {width.rule}",
    }[width.source]
    logger.info(
        "Interval width: %s %s (%s).",
        "unmeasured" if width.tolerance is None else f"{width.tolerance:.4g}",
        width.mode,
        where,
    )
    return width


def _log_parameter_interval(interval: ParameterInterval, best: EvaluationResult | None) -> None:
    """Log the range the trials could not tell apart from one calibrated value.

    A value that reaches a search bound is the best point of a search that was
    forbidden to look further, not a value the trials converged onto: that is
    a warning, not an informational line, and it names the cost it was reached at.
    """
    reach = [
        side
        for side, hit in (
            ("lower", interval.reaches_lower_bound),
            ("upper", interval.reaches_upper_bound),
        )
        if hit
    ]
    if reach:
        logger.warning(
            "%s = %.4g reached the %s search bound, at a cost of %.4g: this is the best "
            "point of a search that was forbidden to look further, not a value the trials "
            "converged onto.",
            interval.name,
            interval.best,
            " and ".join(reach),
            best.objective_value if best is not None else float("nan"),
        )
        return
    logger.info(
        "%s = %.4g, and %d of %d trials scored within %.3g of the best over [%.4g, %.4g].",
        interval.name,
        interval.best,
        interval.n_within,
        interval.n_trials,
        interval.threshold,
        interval.lower,
        interval.upper,
    )


CONDUCTIVITY_PATH = "flow.param.K.field.value"
"""The homogeneous conductivity, the one parameter the paper's ratios divide."""


def _non_negative(value: Any) -> float | None:
    """Return ``value`` as a float when it is finite and not negative, else None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0.0 else None


def _conductivity_unit(trial_ctx: Any, param: CalibParameter) -> str:
    """Return the unit the model reads the conductivity value in.

    The sample is written as-is into ``flow.param.K.field.value``, so the field's
    own unit rules. The declaration's ``units`` comes next, then ``m/s``.
    """
    flow = getattr(getattr(trial_ctx, "base_cfg", None), "flow", None)
    entry = (getattr(flow, "param", None) or {}).get("K")
    unit = getattr(getattr(entry, "field", None), "unit", None)
    for candidate in (unit, param.units):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return "m/s"


def _roptim_verdict_extra(
    outputs: Mapping[str, Any] | None,
    components: Mapping[str, float] | None,
) -> dict[str, Any]:
    """Read Eq. 4 on the trial the search returns, once per network output.

    The paper reads ``roptim <= 2`` at the optimum ("At this point", HESS
    27, p. 3225), and so does this: a trial on the way to the root is not the
    result, and bounding it refused whole brackets. Each trial still carries
    ``<output>.roptim`` and ``<output>.roptim_valid`` as components.

    Returns ``{"roptim_verdict": {output: {value, bound, L_ref, Doptim,
    valid}}}``, or nothing when no network output published a ``roptim``. A
    value above its bound warns once. With ``on_roptim_violation = "error"``
    it raises :class:`CalibrationError`; the caller has already saved the
    session, and a staged calibration stops there, before freezing anything.
    A ``roptim`` that is not a number, an empty network at the returned
    trial, is not qualified and counts as a violation.
    """
    found = components or {}
    verdicts: dict[str, dict[str, Any]] = {}
    fatal: list[str] = []
    for name, output in sorted((outputs or {}).items()):
        if output.support != "network" or f"{name}.roptim" not in found:
            continue
        value = float(found[f"{name}.roptim"])
        bound = float(output.roptim_max)
        length = float(found.get(f"{name}.L_ref", float("nan")))
        optimal = float(found.get(f"{name}.Doptim", float("nan")))
        valid = math.isfinite(value) and value <= bound
        verdicts[name] = {
            "value": value if math.isfinite(value) else None,
            "bound": bound,
            "L_ref": length if math.isfinite(length) else None,
            "Doptim": optimal if math.isfinite(optimal) else None,
            "valid": valid,
        }
        if valid:
            continue
        if math.isfinite(value):
            message = (
                f"Output {name!r}: roptim = {value:.3g} exceeds the bound {bound:.3g}: the "
                f"mean mismatch Doptim = {optimal:.4g} m is more than {bound:.3g} times "
                f"L_ref = {length:.4g} m. L_ref is the cell size, floored by "
                "observed_position_accuracy when the output declares one. It qualifies the "
                "calibrated value; it does not say the value is wrong."
            )
        else:
            message = (
                f"Output {name!r}: roptim is not a number at the returned trial, so the "
                f"bound {bound:.3g} cannot qualify it: the simulated network is empty there."
            )
        logger.warning(message)
        if output.on_roptim_violation == "error":
            fatal.append(message)
    if fatal:
        raise CalibrationError(" ".join(fatal))
    return {"roptim_verdict": verdicts} if verdicts else {}


def _network_ratios_extra(
    *,
    network_outputs: Iterable[str],
    components: Mapping[str, float] | None,
    best_parameters: Mapping[str, float] | None,
    space: ParameterSpace,
    trial_ctx: Any = None,
) -> dict[str, Any]:
    """Return the derived values of Abherve et al. (2023), Table 1, or nothing.

    The network criterion compares two networks and drives any parameter. The
    paper's ratios exist only when the one parameter the search moved is the
    homogeneous conductivity written as a value. A thickness, a zone or a
    multiplier divided by R names nothing, so every other search gets none.

    - ``k_over_r``: K/R, what the criterion identifies at fixed geometry.
    - ``k_optim_m_s``: K in m/s, the calibrated value against that recharge.
    - ``d_sat_m``: dsat, the saturated thickness averaged over the catchment.
    - ``t_over_r_m``: T/R = (K/R) dsat, a length.
    - ``t_optim_m2_s``: Toptim = K dsat.

    R and dsat are read off the best trial, ``<output>.R_mean_m_s`` and
    ``<output>.d_sat_m``, on the first network output by name, which the note
    names. The run is already saved when this runs, so a conductivity unit that
    is not one logs a warning and publishes nothing rather than raise.
    """
    outputs = sorted(network_outputs)
    if not outputs or not best_parameters or len(best_parameters) != 1:
        return {}
    ((name, value),) = best_parameters.items()
    param = next((p for p in space if p.name == name), None)
    if param is None or param.effective_path != CONDUCTIVITY_PATH or param.mode != "replace":
        return {}
    from hydromodpy.core.units.hydraulic_conductivity import factor_to_m_per_s

    unit = _conductivity_unit(trial_ctx, param)
    try:
        conductivity = float(value) * factor_to_m_per_s(unit)
    except ValueError as exc:
        logger.warning("No K/R in the report: %s", exc)
        return {}
    found = components or {}
    output = outputs[0]
    recharge = _non_negative(found.get(f"{output}.R_mean_m_s"))
    if not recharge:
        return {}
    k_over_r = conductivity / recharge
    extra: dict[str, Any] = {"k_over_r": k_over_r, "k_optim_m_s": conductivity}
    note = (
        f"k_over_r = {k_over_r:.4g} against R_mean_m_s = {recharge:.4g} m/s on output "
        f"{output!r}, k_optim = {conductivity:.4g} m/s"
    )
    d_sat = _non_negative(found.get(f"{output}.d_sat_m"))
    if d_sat is not None:
        extra["d_sat_m"] = d_sat
        extra["t_over_r_m"] = k_over_r * d_sat
        extra["t_optim_m2_s"] = conductivity * d_sat
        note += (
            f", d_sat = {d_sat:.4g} m, t_over_r = {k_over_r * d_sat:.4g} m, "
            f"t_optim = {conductivity * d_sat:.4g} m2/s"
        )
        ratio = _non_negative(found.get(f"{output}.d_sat_over_d"))
        if ratio is not None:
            extra["d_sat_over_d"] = ratio
            if ratio > 0.5:
                note += (
                    f". The aquifer runs {ratio:.0%} full: T/R depends on the imposed "
                    "thickness there"
                )
    extra["k_over_r_note"] = note + "."
    return extra


def _search_outcome_extra(session: CalibrationSession) -> dict[str, Any]:
    """Return how the search stopped, and the root search's final bracket.

    ``search`` records whether the engine met its own stopping rule, the
    declared budget and the extension granted once. A staged calibration reads
    ``search["converged"]`` and freezes nothing from a phase that did not.
    ``bracket`` exists only for the root search: the interval whose two ends
    change sign, in physical units, which is what the search proved about the
    root beyond the trial it returns.
    """
    from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter

    extra: dict[str, Any] = {
        "search": {
            "converged": bool(session.converged),
            "stopping_rule": session.stopping_rule,
            "max_iter": int(session.max_iter),
            "extension": int(session.extension),
            "n_evaluations": len(session.history),
        }
    }
    if isinstance(session.optimizer, BisectionAdapter):
        bracket = session.optimizer.bracket_record()
        if bracket is not None:
            extra["bracket"] = bracket
    return extra


def _status_of_the_search(
    session: CalibrationSession, status: str, error: str | None
) -> tuple[str, str | None]:
    """Return the session status to persist, ``partial`` when the rule was not met.

    ``extra["search"]`` lives on the in-memory report only. A resumed staged
    chain reads the catalog instead, and reuses a phase whose session closed as
    ``completed``. A search that spent its budget before its stopping rule was
    met must not close as ``completed``, or a resume would freeze the value the
    live run refused to freeze. ``partial`` already means "trials ran, the stage
    did not finish", which is what the resume reader skips.
    """
    if status != "completed" or session.converged:
        return status, error
    return "partial", (
        f"stopping rule ({session.stopping_rule}) not met after {len(session.history)} "
        f"evaluations (max_iter = {session.max_iter}, extension = {session.extension})"
    )


def _phase_objective_block_shares(
    cfg: CalibrationConfig,
    history: list[EvaluationResult],
    best: EvaluationResult | None,
) -> dict[str, Any] | None:
    """Return the ``objective_block_shares`` a finished phase's report carries.

    ``"mean"`` averages each block's share of the cost over the finished
    trials (``status == "completed"`` and a finite objective, the convention
    every optimizer adapter reads its own history with); ``"mean_n_trials"``
    is how many of them entered that average. ``"best"`` reads the share at
    the trial the search reports. ``None`` for a phase scored through a
    single metric, with no ``[[calibration.objective_blocks]]`` declared, or
    when no finished trial gives a computable share.
    """
    blocks = [(str(block.name), float(block.weight)) for block in cfg.objective_blocks or []]
    if not blocks:
        return None
    finished = [
        result
        for result in history
        if result.status == "completed" and math.isfinite(result.objective_value)
    ]
    mean_result = mean_objective_block_shares(blocks, (result.components for result in finished))
    if mean_result is None:
        return None
    mean_shares, n_trials = mean_result
    payload: dict[str, Any] = {"mean": mean_shares, "mean_n_trials": n_trials}
    if best is not None:
        best_shares = objective_block_shares(best.components, blocks)
        if best_shares is not None:
            payload["best"] = best_shares
    return payload


def _first_trial_pairing(history: list[EvaluationResult]) -> dict[str, dict[str, Any]] | None:
    """Return, per output, the dates and pair count the first trial retained.

    Read from ``history[0]`` rather than recomputed for every trial: the
    pairing a search follows is set before the first candidate is scored and
    does not change trial to trial, so the first one already says it for the
    whole phase (``ObservableScorer.score`` in ``metrics/observable_scoring.py``
    writes ``<name>.n_paired`` and ``<name>.date_start`` / ``<name>.date_end``
    into the components of every trial, from ``PairedOutputs``,
    ``metrics/observed_pairing.py``). ``None`` when no output names a station:
    nothing was paired.
    """
    if not history:
        return None
    components = history[0].components or {}
    names = sorted({key.rsplit(".", 1)[0] for key in components if key.endswith(".n_paired")})
    if not names:
        return None
    pairing: dict[str, dict[str, Any]] = {}
    for name in names:
        entry: dict[str, Any] = {"n_paired": int(components[f"{name}.n_paired"])}
        start = components.get(f"{name}.date_start")
        end = components.get(f"{name}.date_end")
        if start is not None and end is not None:
            entry["start"] = date.fromordinal(int(start)).isoformat()
            entry["end"] = date.fromordinal(int(end)).isoformat()
        pairing[name] = entry
    return pairing


def attach_a_linearized_width(
    report: CalibrationReport,
    *,
    cfg: CalibrationConfig,
    trial_ctx: TrialContext,
    space: ParameterSpace,
    perturbation: float,
) -> CalibrationReport:
    """Attach a first-order width to the answer the search returned.

    One model run per parameter, around the optimum, and the optimum itself is not
    re-run: the derivatives are taken from the reference the caller already paid for.
    A calibration whose parameters the data cannot separate is refused a width rather
    than given a fabricated one, and the failure says which.
    """
    import numpy as np

    from hydromodpy.calibration.metrics.composite import build_paired_vector_capture
    from hydromodpy.calibration.optim.fosm import (
        forward_difference_jacobian,
        linearized_covariance,
        uncertainty_from_covariance,
    )
    from hydromodpy.calibration.runners.trial import run_trial_light

    if not report.best_parameters:
        logger.warning("No candidate was scored, so there is no answer to put a width beside.")
        return report

    # Only the typed refusal, which says the document cannot carry a width at
    # all: every other way this function declines leaves the report standing,
    # and a search already paid for is too expensive to throw away over a
    # declaration. A record that failed to load, or an output naming no
    # station, still leaves loudly the way it always did.
    try:
        capture_fn, captured = build_paired_vector_capture(
            cfg.outputs or {},
            ctx=trial_ctx.ctx,
            objective_blocks=list(cfg.objective_blocks or []),
            warmup_periods=int(cfg.warmup_periods or 0),
            scoring_window=scoring_window_bounds(cfg.scoring_window),
            min_samples=int(cfg.aggregate.min_samples),
        )
    except UncertaintyNotAvailableError as exc:
        logger.warning("No width is reported: %s", exc)
        return report

    def _simulate(values):
        run_trial_light(
            trial_ctx,
            dict(values),
            objective=cfg.objective,
            variable=cfg.variable,
            metric_fn=capture_fn,
            trial_id=-1,
            reject_water_budget_above=cfg.reject_water_budget_above,
        )
        return np.asarray(captured["simulated"], dtype=float)

    names = [name for name in space.names if name in report.best_parameters]
    logger.info(
        "Taking %d derivative(s) around the answer at a %.3g relative step; the calibrated "
        "values do not move.",
        len(names),
        perturbation,
    )
    jacobian = forward_difference_jacobian(
        names, report.best_parameters, _simulate, relative_step=perturbation
    )
    residuals = np.asarray(captured["simulated"], dtype=float) - np.asarray(
        captured["observed"], dtype=float
    )
    try:
        covariance = linearized_covariance(jacobian, residuals)
    except ValueError as exc:
        logger.warning("No width is reported: %s", exc)
        return report
    widths = uncertainty_from_covariance(names, report.best_parameters, covariance)
    for item in widths:
        tradeoff = item.strongest_tradeoff()
        logger.info(
            "%s = %.4g +- %.4g%s",
            item.parameter,
            item.value,
            item.sigma,
            "" if tradeoff is None else f", correlated {tradeoff[1]:+.2f} with {tradeoff[0]}",
        )
    return replace(report, parameter_uncertainty=widths)


def _engine_kwargs(cfg: CalibrationConfig, space: ParameterSpace, *, start_at: Any) -> dict:
    """Return everything the engine is constructed with beyond the space and the seed."""
    kwargs = stopping_kwargs(
        cfg.method, space, tolerance=cfg.tolerance, declared=cfg.optimizer_kwargs
    )
    if start_at is not None and engine_traits(cfg.method).accepts_a_start_point:
        kwargs["start_at"] = start_at
    return kwargs


def _with_its_method(cfg: CalibrationConfig) -> CalibrationConfig:
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
    from disk never reaches the consumer, so the value travelled into the reuse
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


def run_calibration_core(
    cfg: CalibrationConfig,
    trial_ctx: TrialContext | None,
    *,
    workspace: Path,
    space: ParameterSpace,
    project_label: str = "calibration",
    cfg_path: Path | None = None,
    metric_fn: TrialMetricFn | None = None,
    objective: str | None = None,
    store_factory: CalibrationStoreFactory | None = None,
    chain: SessionChain | None = None,
    start_at: Any | None = None,
    interval_width: IntervalWidth | None = None,
) -> CalibrationReport:
    """Heart of the calibration loop. Caller-agnostic.

    ``start_at`` is where the search begins, in transformed space, and is how a
    restart-based uncertainty makes one repetition differ from the next. It is
    handed to the engine only when the engine declares it accepts one; on any
    other engine a new seed is the whole of the difference.

    ``interval_width`` is the width the interval beside each value is read
    with, as the staged runner resolved it for the phase. Unset, it is resolved
    from ``cfg``. One mesh cell is measured off the trials, which the network
    criterion records beside its cost.

    The caller is responsible for:

    - building a :class:`TrialContext` (via :func:`prepare_trials` with the
      appropriate ``parameter_space`` and ``override_paths``) when the named
      evaluator declares it needs one, and passing ``None`` when it does not --
      :func:`hydromodpy.calibration.evaluation.registry.needs_prepared_model`
      answers that from the name alone, before the preparation is paid for,
    - resolving the workspace,
    - building the :class:`ParameterSpace`,
    - providing ``cfg_path`` when ``cfg.materialize_candidates`` is True
      (overlays are derived from the on-disk TOML).

    ``chain`` names the session and places it in a chain of phases. A
    standalone calibration leaves it unset and gets a fresh session id.

    ``cfg_path`` is also what a declared ``stream_geometry_path`` is anchored
    on. The three entry points converge here and all three pass it, whereas only
    the CLI one goes through :func:`load_toml_calibration`; anchoring anywhere
    else leaves the two programmatic routes reading the working directory.
    """
    from hydromodpy.calibration.persistence import CalibrationPersistence
    from hydromodpy.calibration.report import CalibrationReport

    if cfg_path is not None:
        resolve_stream_geometry_paths(cfg, cfg_path)
    cfg = _with_its_method(cfg)
    # Same refusal for a mono-phase run as for a staged one: an optimizer_kwarg
    # foreign to the declared method used to die as a bare TypeError inside the
    # adapter constructor, after the first solve.
    cfg.validate_registry()
    override_paths = resolve_override_paths(cfg)

    factory = store_factory or default_store_factory
    catalog = factory(workspace, cfg.persistence)
    persistence = CalibrationPersistence(
        catalog, persistence=cfg.persistence, project_root=workspace
    )

    engine_cache: ParamsHashCache | None = None
    if cfg.use_cache:
        engine_cache = ParamsHashCache()
        try:
            n_preloaded = preload_hash_cache(catalog.connection, engine_cache)
            if n_preloaded:
                logger.info("Preloaded %d params_hash entries from DuckDB", n_preloaded)
        except Exception:
            logger.debug("Cache preload skipped (fresh catalog or schema mismatch)")

    refuse_an_objective_that_is_not_an_entry_point(objective)
    if metric_fn is None and objective and ":" in objective:
        metric_fn = load_metric_fn_entry_point(objective)

    use_api_isolation = _api_isolation_needed(cfg.parallel)
    # Both probe the configuration the pipeline was built from. An evaluator that
    # declares it needs no prepared model built none, so there is nothing to
    # probe: guarded here rather than left to two getattr chains that would
    # return early and look like a check that passed.
    if trial_ctx is not None:
        _assert_bounds_valid(trial_ctx, space)
        _assert_network_conductance_proportional(cfg, trial_ctx, space)
        _assert_active_release_packages_follow_k(cfg, trial_ctx, space)

    # The evaluator is resolved by the name the document wrote, and built with
    # only the options its class names. Before the session row, because an
    # evaluator that cannot be built must not leave a session behind claiming a
    # search happened.
    evaluator = evaluation_registry.create(
        cfg.evaluator,
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        workspace=workspace,
        cfg_path=cfg_path,
        metric_fn=metric_fn,
    )
    if trial_ctx is None and (cfg.save_runs != "none" or cfg.rerun_best_with_outputs):
        raise CalibrationError(
            f"calibration.evaluator names {getattr(evaluator, 'evaluator_id', cfg.evaluator)!r}, "
            "which runs no HydroModPy model, and save_runs / rerun_best_with_outputs ask for "
            "the best trials to be replayed through the pipeline and written as simulations. "
            "There is no pipeline to replay them through. Refused here rather than at the end "
            "of a search that would have had nothing to promote."
        )

    session_id = chain.session_id if chain is not None else uuid.uuid4().hex
    persistence.start_session(
        session_id=session_id,
        project=project_label,
        method=cfg.method,
        objective_name=cfg.objective,
        search_space=_search_space_payload(space),
        config=_session_config_payload(cfg, evaluator),
        parent_session_id=chain.parent_session_id if chain is not None else None,
        root_session_id=chain.root_session_id if chain is not None else None,
        phase_name=chain.phase_name if chain is not None else None,
        phase_index=chain.phase_index if chain is not None else None,
    )

    optimizer = build_optimizer(
        cfg.method,
        space,
        seed=cfg.seed,
        **_engine_kwargs(cfg, space, start_at=start_at),
    )
    cache_context = build_cache_context(
        cfg=cfg,
        trial_ctx=trial_ctx,
        space=space,
        override_paths=override_paths,
        objective_entrypoint=objective,
    )

    materialize_root: Path | None = None
    if cfg.materialize_candidates:
        if cfg.candidates_root is None:
            raise ValueError(
                "calibration.materialize_candidates is True but "
                "calibration.candidates_root is not set."
            )
        if cfg_path is None:
            raise ValueError(
                "calibration.materialize_candidates is True but no source TOML "
                "is available. Provide cfg_path or run from a TOML-loaded Project."
            )
        materialize_root = Path(cfg.candidates_root).expanduser().resolve()
        materialize_root.mkdir(parents=True, exist_ok=True)

    def wrapped_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        result = evaluator.evaluate(TrialRequest(trial_id=sugg.trial_id, values=sugg.values))
        # calibration_iterations CHECK accepts only finite lifecycle states.
        # Map "failed" metric errors onto "crashed" for persistence.
        db_status = "crashed" if result.status == "failed" else result.status
        meta: dict[str, object] = {}
        if result.error:
            meta["error"] = result.error
            logger.warning("Calibration trial %d %s: %s", sugg.trial_id, db_status, result.error)
        if cfg.persist_iteration_detail == "full":
            meta["block_costs"] = dict(result.components)
        if materialize_root is not None and cfg_path is not None:
            from hydromodpy.calibration.runners.materialize import materialize_candidate

            try:
                overlay_path = materialize_candidate(
                    cfg_path,
                    dict(sugg.values),
                    space,
                    materialize_root,
                    iteration_index=sugg.trial_id,
                )
                meta["materialized_overlay"] = str(overlay_path)
            except Exception as exc:
                logger.warning(
                    "Failed to materialize overlay for trial %d: %s",
                    sugg.trial_id,
                    exc,
                )
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=result.cost,
            status=db_status,
            duration_s=result.duration_s,
            components=dict(result.components) or None,
            metadata=meta,
        )

    # An EvaluationResult carries no parameters, and a cache hit never reaches
    # the evaluator, so the suggestion is the only place the values of a trial
    # are seen. Keeping them is what lets the report name the best candidate.
    values_by_trial: dict[int, dict[str, float]] = {}

    # A mis-configured search fails the same way on every trial. Stopping on a
    # streak refuses it in seconds instead of spending the whole budget and then
    # reporting a best candidate chosen between values that all came from one
    # error.
    failure_watch = ConsecutiveFailureWatch()

    def on_iteration(sugg: ParamSuggestion, result: EvaluationResult) -> None:
        values_by_trial[sugg.trial_id] = {k: float(v) for k, v in sugg.values.items()}
        persistence.append_iteration(
            session_id,
            sugg,
            result,
            detail=cfg.persist_iteration_detail,
        )
        # After the trial is recorded, so a stopped search still shows what it
        # tried, and only for trials the engine actually ran: a cache hit never
        # reaches this callback.
        failure_watch.record(
            failed=result.status != "completed",
            error=str((result.metadata or {}).get("error") or ""),
        )

    # "auto" becomes the count the engine publishes, so the log and the progress
    # bar show what the run will spend.
    budget = resolve_budget(optimizer, cfg.max_iter)
    logger.info(
        "Calibration session %s | method=%s max_iter=%d save_runs=%s",
        session_id,
        cfg.method,
        budget,
        cfg.save_runs,
    )

    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=wrapped_evaluator,
        max_iter=budget,
        batch_size=cfg.batch_size,
        parallel=cfg.parallel,
        cache=engine_cache,
        cache_context=cache_context,
        progress=ConsoleProgressReporter(cfg.method, budget),
        session_id=session_id,
        on_iteration=on_iteration,
    )

    t0 = time.perf_counter()
    session: CalibrationSession | None = None
    final_status = "failed"
    final_error: str | None = None
    promotion_count = 0
    promotion_failures: list[str] = []
    best_sim_id: str | None = None
    best: EvaluationResult | None = None

    try:
        from hydromodpy.solver.base.api_isolation import api_isolation_context

        # Isolate each api solve in its own process for the PARALLEL trial loop
        # only; promotion below replays a single run and stays in-process. The
        # switch is backend-neutral on purpose: this path runs for every solver,
        # so importing it must not cost a backend.
        #
        # A calibration is hours long, so what ends it is often not a keyboard:
        # a scheduler time limit, a container stop, a plain kill. All of those
        # are SIGTERM, which by default ends the process where it stands and
        # leaves this session 'running' in the index for good.
        with terminate_as_interrupt(), api_isolation_context(use_api_isolation):
            session = engine.run()
        best = session.best

        promotion_required = cfg.save_runs != "none" or cfg.rerun_best_with_outputs
        if promotion_required:
            if cfg_path is None:
                raise ValueError(
                    "Calibration promotion requires a source TOML "
                    "(promotion replays the full pipeline). Provide cfg_path or disable "
                    "save_runs/rerun_best_with_outputs."
                )
            promotion_count, promotion_failures, best_sim_id = promote_iterations(
                cfg=cfg,
                trial_ctx=trial_ctx,
                catalog=catalog,
                persistence=persistence,
                session_id=session_id,
                best=best,
                override_paths=override_paths,
            )
            if best_sim_id is not None:
                _persist_observed_for_report(catalog, trial_ctx, cfg.variable)

        n_total = len(session.history)
        n_ok = sum(1 for h in session.history if h.status in ("completed", "cached"))
        if n_total > 0 and n_ok == n_total:
            final_status = "completed"
        elif n_ok > 0:
            final_status = "partial"
        else:
            final_status = "failed"
            if n_total == 0:
                final_error = "no iterations completed"
        if promotion_failures:
            final_status = "partial" if promotion_count > 0 else "failed"
            final_error = "; ".join(promotion_failures)
        final_status, final_error = _status_of_the_search(session, final_status, final_error)
    except TerminationRequested:
        final_status = "aborted"
        final_error = "SIGTERM"
        raise
    except KeyboardInterrupt:
        final_status = "aborted"
        final_error = "SIGINT"
        raise
    except Exception as exc:
        final_status = "failed"
        final_error = str(exc)
        raise
    finally:
        _release_session_scratch(trial_ctx)
        elapsed = time.perf_counter() - t0
        n_iter = len(session.history) if session is not None else 0
        duration = session.duration_s if session is not None and session.duration_s else elapsed
        persistence.finalize_session(
            session_id,
            best=best,
            n_iterations=n_iter,
            duration_s=duration,
            status=final_status,
            error=final_error,
            best_sim_id=best_sim_id,
        )
        close = getattr(catalog, "close", None)
        if close is not None:
            close()

    # Two parameters that moved together across the whole search were never told
    # apart by the data: the search stopped on a ridge and reported that point as
    # a minimum. Read off the trace the session already holds, so it costs nothing.
    trace = calibration_trace(session.history, values_by_trial)
    names = [param.name for param in space]
    correlated = correlated_parameter_pairs(trace, names)
    width = _width_read_off_the_trials(
        interval_width if interval_width is not None else cfg.interval_width_for(),
        best,
        session.history,
    )
    intervals = _tolerance_intervals_or_none(trace, names, space, width)
    if correlated:
        for first, second, coefficient in correlated:
            logger.warning(
                "Calibration parameters %s and %s moved together (r = %+.2f): the trace "
                "does not tell them apart, so the reported pair is one point on a ridge.",
                first,
                second,
                coefficient,
            )

    for interval in intervals:
        _log_parameter_interval(interval, best)

    extra: dict[str, Any] = {"interval_width": width.to_dict()}
    if correlated:
        extra["correlated_parameters"] = correlated
    if intervals:
        extra["parameter_intervals"] = [interval.to_dict() for interval in intervals]
    pairing = _first_trial_pairing(session.history)
    if pairing:
        logger.info(
            "First trial paired: %s",
            "; ".join(
                f"{name} {info['n_paired']} pair(s)"
                + (f" from {info['start']} to {info['end']}" if "start" in info else "")
                for name, info in pairing.items()
            ),
        )
        extra["first_trial_pairing"] = pairing
    extra.update(
        _network_ratios_extra(
            network_outputs=[
                name for name, output in (cfg.outputs or {}).items() if output.support == "network"
            ],
            components=best.components if best is not None else None,
            best_parameters=values_by_trial.get(best.trial_id) if best is not None else None,
            space=space,
            trial_ctx=trial_ctx,
        )
    )
    extra.update(_search_outcome_extra(session))
    extra.update(_roptim_verdict_extra(cfg.outputs, best.components if best else None))

    return CalibrationReport(
        session_id=session_id,
        method=cfg.method,
        extra=extra,
        n_iterations=len(session.history),
        best_objective=best.objective_value if best else None,
        best_sim_id=best_sim_id,
        best_parameters=values_by_trial.get(best.trial_id) if best else None,
        objective_block_shares=_phase_objective_block_shares(cfg, session.history, best),
        duration_s=float(session.duration_s if session.duration_s else elapsed),
        save_runs=cfg.save_runs,
        promoted=promotion_count,
        workspace=workspace,
        store_factory=lambda path: factory(path, cfg.persistence),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_calibration_cli(
    config_path: Path | str,
    *,
    objective: str | None = None,
    workspace: Path | str | None = None,
    project: str = "calibration",
    metric_fn: TrialMetricFn | None = None,
    return_report: bool = False,
    store_factory: CalibrationStoreFactory | None = None,
) -> dict | object:
    """Run a calibration described by ``config_path``.

    Parameters
    ----------
    config_path
        Path to a TOML that declares ``[calibration]`` plus the full
        ``[simulation]`` / ``[flow]`` / ``[data]`` blocks.
    objective
        Optional escape hatch: ``"module.path:callable"`` selects the
        RAM metric extractor. ``metric_fn`` wins when both are given;
        a value that is not an entry point is refused.
    workspace
        Override the project catalog root (defaults to the one resolved
        from the TOML).
    project
        Project label written to ``calibration_sessions.project``.
    metric_fn
        Programmatic override for the metric extractor.
    return_report
        When True, return the structured :class:`CalibrationReport`
        instead of its ``to_dict()`` payload.
    """
    refuse_an_objective_that_is_not_an_entry_point(objective)
    cfg_path = Path(config_path).expanduser().resolve()
    cfg, raw = load_toml_calibration(cfg_path)
    cfg = _with_its_method(cfg)
    space = space_from_config(cfg)
    paths = resolve_override_paths(cfg)

    # Asked of the class, before anything is built: preparing trials runs the
    # whole geographic, mesh and data prefix of the pipeline, and an evaluator
    # that replaces the model has no use for the model's setup. Paying for it
    # anyway is what would make a surrogate as slow as what it stands in for.
    trial_ctx = (
        prepare_trials(cfg_path, override_paths=paths, parameter_space=space)
        if evaluation_registry.needs_prepared_model(cfg.evaluator)
        else None
    )

    if workspace is not None:
        ws_root = Path(workspace).expanduser().resolve()
    elif trial_ctx is not None:
        ws_root = trial_ctx.workspace
    else:
        # No prepared context to read the project root off, so the document is
        # asked directly. Falling straight through to the file's directory would
        # write the session journal somewhere else than a run of the same file
        # that names the pipeline evaluator, over the same declared root.
        declared = (raw.get("workspace") or {}).get("project_root")
        ws_root = Path(declared).expanduser() if declared else cfg_path.parent
        if not ws_root.is_absolute():
            ws_root = (cfg_path.parent / ws_root).resolve()

    def _one_search(restart_seed: int, start_at):
        return run_calibration_core(
            cfg
            if restart_seed == (cfg.seed or 0)
            else cfg.model_copy(update={"seed": restart_seed}),
            trial_ctx,
            workspace=ws_root,
            space=space,
            project_label=project,
            cfg_path=cfg_path,
            metric_fn=metric_fn,
            objective=objective,
            store_factory=store_factory,
            start_at=start_at,
        )

    uncertainty = getattr(cfg, "uncertainty", None)
    if getattr(uncertainty, "method", None) == "multistart":
        logger.info(
            "Running %d restarts: the answer is the best of them, the spread is reported "
            "beside it, and each restart is a full search.",
            int(uncertainty.restarts),
        )
        report, spread = run_restarts(
            _one_search,
            method=cfg.method,
            space=space,
            restarts=int(uncertainty.restarts),
            seed=cfg.seed,
        )
        for item in spread:
            logger.info(
                "%s: best %.4g, restarts spanned %.4g to %.4g over %d searches%s.",
                item.parameter,
                item.best,
                item.lowest,
                item.highest,
                len(item.values),
                " - more than a factor ten, so this calibration did not identify it"
                if item.spans_a_decade
                else "",
            )
    elif getattr(uncertainty, "method", None) == "linearized":
        if trial_ctx is None:
            raise CalibrationError(
                "uncertainty.method is 'linearized', which perturbs each calibrated value and "
                "rebuilds the model to read the sensitivity off it. The evaluator named here "
                "runs no HydroModPy model, so there is nothing to rebuild. Use 'cost_profile', "
                "which reads the trace the search already produced, or 'multistart'."
            )
        report = _one_search(cfg.seed or 0, None)
        report = attach_a_linearized_width(
            report,
            cfg=cfg,
            trial_ctx=trial_ctx,
            space=space,
            perturbation=float(uncertainty.perturbation),
        )
    else:
        report = _one_search(cfg.seed or 0, None)
    if return_report:
        return report
    return report.to_dict()


__all__ = [
    "attach_a_linearized_width",
    "refuse_an_objective_that_is_not_an_entry_point",
    "load_toml_calibration",
    "resolve_stream_geometry_paths",
    "run_calibration_cli",
    "run_calibration_core",
]
