"""The checks that need the prepared model, run once right after the preparation.

The preflight (:mod:`hydromodpy.calibration.preflight`) checks the document
before anything is prepared. Four things it cannot see need the
configuration the pipeline was prepared from: a bound outside the range the
field accepts, which only building the flow tells, the conductance of the
drains and of the release packages a network search relies on, as the phase
built them, and the catchment a network criterion would score, which only the
model top on the mesh tells. :func:`check_the_prepared_model` runs them, once per
preparation, before the session is reserved: once for a search without
phases, once per phase of a staged one, whatever the restarts.

The preflight sits above the runners in ``calibration_layout.yaml`` and the
preparation happens in them, so these checks live here and the preflight
reads the helpers it shares with them from this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.core.logging import get_logger
from hydromodpy.physics.flow.property_ids import CONDUCTIVITY_IDS

if TYPE_CHECKING:
    from hydromodpy.calibration.optim.parameters import ParameterSpace

logger = get_logger(__name__)


def check_the_prepared_model(
    cfg: CalibrationConfig, trial_ctx: Any | None, space: ParameterSpace
) -> None:
    """Refuse what the prepared model shows, before the session and the first solve.

    ``cfg`` is the search about to run, a phase's own for a staged
    calibration, and ``trial_ctx`` what ``prepare_trials`` returned for it.
    An evaluator that needs no prepared model built none, so there is
    nothing to check. Raises :class:`ValueError` for a bound the field
    refuses and :class:`~hydromodpy.core.exceptions.ObjectiveError` for a
    conductance or a catchment the network criterion cannot trust.
    """
    if trial_ctx is None:
        return
    _assert_bounds_valid(trial_ctx, space)
    _assert_network_conductance_proportional(cfg, trial_ctx, space)
    _assert_active_release_packages_follow_k(cfg, trial_ctx, space)
    _assert_the_scored_catchment_is_the_delineated_one(cfg, trial_ctx, space)


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


def moves_a_hydraulic_conductivity(paths: Iterable[str | None]) -> bool:
    """True when one of ``paths`` addresses a hydraulic conductivity field.

    Matches ``flow.param.K``, ``Kv`` or ``K22`` at any depth under it
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
            if parts[2] in CONDUCTIVITY_IDS:
                return True
    return False


def balanced_roots(cfg: Any, names: Iterable[str]) -> list[str]:
    """Return which of ``names`` a root search can walk: a conductivity searched in log space."""
    declared = cfg.parameters or {}
    return [
        name
        for name in names
        if name in declared
        and str(declared[name].search_space) == "log"
        and moves_a_hydraulic_conductivity([declared[name].resolve_target()])
    ]


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


def network_outputs_of(cfg: CalibrationConfig) -> list[str]:
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
    ``C = K * cell_area / drain_bed_thickness_m`` on every backend (the
    fallback in ``drain_conductance.hk_fallback_drain_conductance`` on both
    MODFLOW backends, ``fluxes.derived_drain_conductance_m2_s`` on
    Boussinesq). All three apply it only when the configured conductance is not
    strictly positive. A fixed value breaks the invariance from a factor 1.05
    onwards, and the run still completes and returns a number, so a K-moving
    search is refused before the first solve.

    A search that drives some other parameter with the conductance fixed is a
    different question: the network criterion can be pointed at any parameter,
    and nothing here can say whether that search means something, so it gets a
    warning instead of a refusal, naming that its result depends on the chosen
    conductance.

    The outputs are resolved by :func:`network_outputs_scored`, so a phase
    scored through its own ``variable``/``objective`` is seen even though the
    staged runner empties its ``cfg.outputs``.
    """
    network_outputs = network_outputs_of(cfg)
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
}
"""Display label for the active_bc ids the registry declares 'advanced_package'.

RIV and GHB would join this table -- neither ties its conductance to K by
construction -- but neither is a constructible boundary id today:
``FLOW_BOUNDARY_DEFINITIONS`` (``boundary_condition_registry.py``) declares no
'riv' and no 'ghb' entry, so a ``[flow.bc.riv]`` table is refused at config
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
    which reports the same text as an error finding at the start of a launch,
    before anything is prepared.
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
    message = release_package_conductance_conflict(network_outputs_of(cfg), flow, moves_k=moves_k)
    if message is not None:
        raise ObjectiveError(message)


def _assert_the_scored_catchment_is_the_delineated_one(
    cfg: CalibrationConfig, trial_ctx: Any, space: ParameterSpace
) -> None:
    """Refuse a network search whose scored catchment is not the catchment asked for.

    The criterion scores the cells whose descent reaches the outlet on the mesh graph.
    ``catchment_mismatch`` says how far those sit from the delineated outline, and it
    depends on the geometry alone, so one build before the first solve answers for every
    trial. The geometry is the one a trial builds, on a model built and not solved, so
    a map that draws no stream is refused here too, with the message of the trial. The
    model and the geometry cost about two seconds on 21 406 cells. An output with
    ``verdict.max_catchment_mismatch = false`` builds nothing and is never refused.
    """
    from hydromodpy.calibration.runners.trial import TrialContext, built_model

    if not isinstance(trial_ctx, TrialContext):
        return
    outputs = {name: cfg.outputs[name] for name in network_outputs_of(cfg) if name in cfg.outputs}
    bounded = {
        name: output
        for name, output in outputs.items()
        if getattr(output, "support", None) == "network"
        and output.verdict.max_catchment_mismatch is not False
    }
    if not bounded:
        return
    from hydromodpy.calibration.metrics.solver_extract import (
        resolve_flow_adapter,
        scored_catchment_mismatch,
    )

    values = {param.name: float(param.lower) for param in space}
    with built_model(trial_ctx, values) as ctx:
        resolved = resolve_flow_adapter(ctx)
        if resolved is None:
            return
        run_ctx = resolved[1]
        for name, output in sorted(bounded.items()):
            try:
                gap = scored_catchment_mismatch(run_ctx, output)
            except ValueError as exc:
                # A map that draws no stream, in the words of a trial.
                raise ObjectiveError(f"Network output {name!r}: {exc}") from exc
            bound = float(output.verdict.max_catchment_mismatch)
            if gap > bound:
                raise ObjectiveError(
                    f"Network output {name!r}: catchment_mismatch = {gap:.1%}, the catchment "
                    "read on the descent graph differs from the delineated one by that share "
                    f"of its area, over the {bound:.1%} bound of "
                    "verdict.max_catchment_mismatch. The criterion would score another basin "
                    "than the one asked for. Three causes: an outlet on another branch, a mesh "
                    "too coarse for the catchment, or two conditionings of one DEM that "
                    "disagree along the divide (the polygon is cut on one, the descent graph "
                    "is built on the other, and a finer mesh does not close that gap). Check "
                    "the outlet first. If the gap is the third kind and you accept it, write "
                    "a larger bound, or max_catchment_mismatch = false, under "
                    "[calibration.outputs.<name>.verdict], knowing what it buys."
                )
            logger.info(
                "Network output %s: catchment_mismatch = %.2f%% of the delineated area, under "
                "the %.1f%% bound.",
                name,
                100.0 * gap,
                100.0 * bound,
            )


__all__ = [
    "balanced_roots",
    "check_the_prepared_model",
    "moves_a_hydraulic_conductivity",
    "network_outputs_of",
    "network_outputs_scored",
    "release_package_conductance_conflict",
]
