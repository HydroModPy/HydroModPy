"""Everything a calibration needs, checked before the first solve.

A calibration is hours of solver time, and until now every check fired where it
sat: a missing stream geometry when the criterion first ran, a typo in a
parameter path at the first trial, a phase that cannot describe a runnable
calibration when its turn came, after the phases before it had spent their whole
budget. Each one cost the run that had already happened.

Two rules make this useful rather than merely early. Nothing here solves, so it
costs a second whatever the model. And every check runs: a file with three
mistakes comes back with three findings, so it takes one pass to fix instead of
three overnight runs.

What this cannot see is stated as clearly as what it can. A station's record is
loaded by the data step, which needs a network and a catchment, so preflight
checks the names a file declares against each other and leaves the loading to
the run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class PreflightFinding:
    """One thing that will stop, or spoil, the run about to start."""

    severity: Severity
    where: str
    """The TOML key the reader has to go and edit."""

    detail: str
    """What is wrong, and what to write instead."""

    def line(self) -> str:
        """Return the finding as one printable line."""
        return f"{self.severity.upper():7} {self.where}: {self.detail}"


def preflight_calibration(config: Any, *, source: str | Path) -> list[PreflightFinding]:
    """Return everything wrong with a loaded calibration, before it runs.

    ``config`` is the resolved project configuration and ``source`` the file it
    came from, which is what a relative geometry path is anchored against.
    Loading is the caller's, because a configuration is assembled a layer above
    this one; a file that will not load has nothing here to check.
    """
    calibration = getattr(config, "calibration", None)
    if calibration is None or not getattr(calibration, "parameters", None):
        return [
            PreflightFinding(
                "error",
                "[calibration]",
                "no calibration to run: declare [calibration.parameters.<name>] with "
                "bounds and a path. `hmp config targets` lists what this project "
                "exposes.",
            )
        ]

    where_from = Path(source).expanduser().resolve()
    findings: list[PreflightFinding] = []
    findings.extend(_check_parameters(config, calibration))
    findings.extend(_check_outputs(calibration, where_from, config))
    findings.extend(_check_blocks(calibration))
    findings.extend(_check_phases(calibration))
    findings.extend(_check_engines(calibration))
    findings.extend(_check_the_precision_can_be_honoured(calibration))
    findings.extend(_check_the_backend_can_serve_the_outputs(config, calibration))
    return findings


def _check_parameters(cfg: Any, calibration: Any) -> list[PreflightFinding]:
    """Check every declared parameter against the configuration it will write into."""
    from hydromodpy.calibration.parameter_resolution import unresolved_parameter_names
    from hydromodpy.calibration.targets import calibration_targets, targets_by_path

    findings: list[PreflightFinding] = []
    reachable = targets_by_path(calibration_targets(cfg))
    refused_names = unresolved_parameter_names(calibration, cfg)
    for name, decl in (calibration.parameters or {}).items():
        where = f"[calibration.parameters.{name}]"
        bounds = list(getattr(decl, "bounds", ()) or ())
        if len(bounds) == 2 and bounds[0] >= bounds[1]:
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"bounds are {bounds[0]:g} .. {bounds[1]:g}; the lower one has to be "
                    "the smaller one.",
                )
            )
        target = decl.resolve_target()
        if not target:
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    # The finding already names the section in its 'where' column.
                    refused_names.get(name, "").replace(f"{where} ", "", 1)
                    or "names nothing this project carries, and writes no 'path' either.",
                )
            )
            continue
        if target not in reachable:
            near = ", ".join(sorted(reachable)[:6]) or "nothing"
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"path {target!r} is not a value this configuration carries. "
                    f"`hmp config targets` lists them; it starts with {near}.",
                )
            )
            continue
        findings.extend(_check_bounds_against_physics(where, name, decl, bounds))
    return findings


def _check_bounds_against_physics(
    where: str, name: str, decl: Any, bounds: list[float]
) -> list[PreflightFinding]:
    from hydromodpy.calibration.optim.parameters import _assert_bounds_are_physical

    if len(bounds) != 2:
        return []
    try:
        _assert_bounds_are_physical(name, float(bounds[0]), float(bounds[1]), decl.units)
    except ValueError as exc:
        return [PreflightFinding("error", where, str(exc))]
    if str(getattr(decl, "transform", "identity")).lower() == "log" and bounds[0] <= 0.0:
        return [
            PreflightFinding(
                "error",
                where,
                f'transform = "log" needs a lower bound above zero, got {bounds[0]:g}.',
            )
        ]
    return []


def _check_outputs(calibration: Any, source: Path, project_config: Any) -> list[PreflightFinding]:
    """Check what an output needs that only the filesystem or the project can answer.

    The geometry is looked for exactly where the run looks for it, so a file
    preflight calls missing is one the run would call missing too. A declared
    ``observed_network`` is faced with the project the same way a parameter's
    name is faced with the catalogue: refused here beside whatever else is
    wrong, rather than at the first trial.
    """
    from hydromodpy.calibration.observations.network_source import unresolved_observed_networks
    from hydromodpy.calibration.runners.cli_runner import _resolve_stream_geometry_paths

    _resolve_stream_geometry_paths(calibration, source)
    refused_networks = unresolved_observed_networks(calibration, project_config)
    findings: list[PreflightFinding] = []
    for name, decl in (calibration.outputs or {}).items():
        where = f"[calibration.outputs.{name}]"
        if name in refused_networks:
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    # The finding already names the section in its 'where' column.
                    refused_networks[name].replace(f"{where} ", "", 1),
                )
            )
        geometry = getattr(decl, "stream_geometry_path", None)
        if geometry and not Path(str(geometry)).exists():
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"stream_geometry_path {geometry!r} is not there, and none of the "
                    "places the run looks holds it. The criterion resolves no geometry "
                    "of its own, so the run would stop at the first trial.",
                )
            )
    return findings


def _check_blocks(calibration: Any) -> list[PreflightFinding]:
    findings: list[PreflightFinding] = []
    declared = set(calibration.outputs or {})
    seen: set[str] = set()
    for block in calibration.objective_blocks or []:
        where = f"[[calibration.objective_blocks]] {block.name!r}"
        if block.name in seen:
            findings.append(PreflightFinding("error", where, "two blocks share this name."))
        seen.add(block.name)
        findings.extend(
            _missing(where, "uses_outputs", block.uses_outputs, declared, "[calibration.outputs]")
        )
    return findings


def _check_phases(calibration: Any) -> list[PreflightFinding]:
    phases = calibration.phases
    if not phases:
        return []
    findings: list[PreflightFinding] = []
    parameters = set(calibration.parameters or {})
    outputs = set(calibration.outputs or {})
    blocks = {block.name for block in calibration.objective_blocks or []}
    names = [phase.name for phase in phases]
    ran: set[str] = set()

    for phase in phases:
        where = f"[[calibration.phases]] {phase.name!r}"
        if names.count(phase.name) > 1:
            findings.append(PreflightFinding("error", where, "two phases share this name."))
        findings.extend(
            _missing(where, "parameters", phase.parameters, parameters, "[calibration.parameters]")
        )
        findings.extend(_missing(where, "outputs", phase.outputs, outputs, "[calibration.outputs]"))
        findings.extend(
            _missing(
                where,
                "objective_blocks",
                phase.objective_blocks,
                blocks,
                "[[calibration.objective_blocks]]",
            )
        )
        if phase.depends_on is not None and phase.depends_on not in ran:
            known = ", ".join(names) or "nothing"
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"depends_on names {phase.depends_on!r}, which no earlier phase "
                    f"declares. Phases run in the order written: {known}.",
                )
            )
        ran.add(phase.name)
    return findings


def _publishes_a_signed_residual(metric: str) -> bool:
    """Whether this criterion's cost IS the absolute residual a root search closes on.

    The answer comes from the criterion, not from a list held here. The network
    criterion publishes ``J_signed`` beside every cost, so merely reading that
    output is not enough: a bisection reports as its best the trial whose cost is
    smallest, and it can only do that when the cost IS that residual, which is
    true of ``distance_gap`` and false of ``distance_mean``. The estimator is
    what knows the difference, so the estimator is what declares it.
    """
    from hydromodpy.calibration.criteria import criterion_for

    try:
        return criterion_for(metric).requirements().signed
    except ValueError:
        # An unknown metric is refused elsewhere, by name; nothing to add here.
        return False


def _signed_residual_metrics() -> list[str]:
    """Return every registered criterion a root search may be pointed at."""
    from hydromodpy.calibration.criteria import available_criteria

    return sorted(name for name in available_criteria() if _publishes_a_signed_residual(name))


def _check_engines(calibration: Any) -> list[PreflightFinding]:
    """Face each search with what its engine says it can be handed.

    An engine refuses an impossible pairing in its constructor, which is right
    but late: a staged calibration builds phase two's optimizer when phase two
    starts, after phase one has spent its whole budget.
    """
    from hydromodpy.calibration.optim.optimizer import available_optimizers, engine_traits

    known = set(available_optimizers())
    findings: list[PreflightFinding] = []
    for where, method, names, metrics, parallel in _searches(calibration):
        if method not in known:
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"method {method!r} is not registered. Available: {', '.join(sorted(known))}.",
                )
            )
            continue
        traits = engine_traits(method)
        if traits.max_parameters is not None and len(names) > traits.max_parameters:
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"{method!r} moves {traits.max_parameters} parameter(s) at a time and "
                    f"this search declares {len(names)}: {', '.join(names)}.",
                )
            )
        if traits.required_transform is not None:
            wrong = [
                name
                for name, decl in (calibration.parameters or {}).items()
                if name in names
                and str(getattr(decl, "transform", "identity")) != traits.required_transform
            ]
            if wrong:
                findings.append(
                    PreflightFinding(
                        "error",
                        where,
                        f"{method!r} walks a {traits.required_transform!r} variable and "
                        f"its stopping rule is a width in it, but {', '.join(wrong)} "
                        f"declare(s) another transform.",
                    )
                )
        if traits.needs_signed_residual and not any(
            _publishes_a_signed_residual(metric) for metric in metrics
        ):
            named = ", ".join(sorted(metrics)) or "nothing"
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"{method!r} closes a bracket on a signed residual and reports the "
                    f"trial with the smallest cost as its best, which only agree when "
                    f"the cost IS that residual. This search is scored on {named}. "
                    f"Score it on {', '.join(_signed_residual_metrics())}, or "
                    "search it with a minimiser.",
                )
            )
        if parallel > 1 and not traits.supports_parallel:
            findings.append(
                PreflightFinding(
                    "warning",
                    where,
                    f"{method!r} returns one point at a time, so parallel = {parallel} "
                    "buys nothing.",
                )
            )
    return findings


_OBSERVABLE_BY_SUPPORT: Mapping[str, str] = {
    "lake": "stage",
    "network": "release_flux",
}
"""What an output's support actually asks the backend for."""


def _check_the_precision_can_be_honoured(calibration: Any) -> list[PreflightFinding]:
    """Refuse a precision the engine of that search cannot stop on.

    The translation happens when the optimizer is built, which for phase two is
    after phase one has spent its budget. A precision that was never going to be
    readable has to be refused before the first solve, not after the last.
    """
    from hydromodpy.calibration.optim.optimizer import available_optimizers, engine_traits

    known = set(available_optimizers())
    findings: list[PreflightFinding] = []
    uncertainty = getattr(calibration, "uncertainty", None)
    if getattr(uncertainty, "method", None) == "linearized":
        # Same reason as the precision below: the width is built after the
        # last solve, so `hmp calibrate --check` is where a document that can
        # never carry one is named, before any of it is paid for. A phased
        # document gets one width per phase (D234), built from what THAT
        # PHASE scores, so each phase is checked on its own selection rather
        # than on the whole file's.
        from hydromodpy.calibration.metrics.composite import (
            refuse_a_burn_in_the_residuals_cannot_honour,
        )
        from hydromodpy.core.exceptions import UncertaintyNotAvailableError

        for where, outputs, blocks, single_metric in _linearized_scored_outputs(calibration):
            observing = [
                name
                for name, decl in outputs.items()
                if getattr(decl, "observes", None) is not None
            ]
            if not observing:
                if single_metric:
                    detail = (
                        "scores on variable/objective directly, not on paired residuals: it "
                        "builds no residual vector for a linearized width to be taken from. "
                        "A single-metric phase inherits none of the calibration's outputs, "
                        "whatever another output in this file declares -- see _phase_config -- "
                        "so naming observes elsewhere is not a remedy here. Read the width "
                        "with method='cost_profile', or restructure this phase to score "
                        "objective_blocks."
                    )
                else:
                    detail = (
                        "method='linearized' is built from residuals, and no output names a "
                        'station to be compared against. Declare observes = "<station>" on '
                        "the outputs this calibration is fitted to, or use "
                        "method='cost_profile', which reads the trace instead."
                    )
                findings.append(PreflightFinding("error", where, detail))
                continue
            try:
                refuse_a_burn_in_the_residuals_cannot_honour(
                    outputs, blocks, int(calibration.warmup_periods or 0)
                )
            except UncertaintyNotAvailableError as exc:
                findings.append(PreflightFinding("error", where, str(exc)))
    restarts = getattr(getattr(calibration, "uncertainty", None), "restarts", None)
    for where, method, tolerance, kwargs in _declared_precisions(calibration):
        if restarts is not None and method in known:
            from hydromodpy.calibration.runners.restarts import assert_restarts_can_explore

            try:
                assert_restarts_can_explore(method, int(restarts))
            except ValueError as exc:
                findings.append(PreflightFinding("error", where, str(exc)))
        if tolerance is None or method not in known:
            continue
        traits = engine_traits(method)
        if traits.tolerance_option is None:
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"tolerance asks {method!r} to stop at a precision on the parameter, "
                    "and that engine stops on its evaluation budget instead. Set max_iter, "
                    "or run this search on an engine that converges on the parameter.",
                )
            )
            continue
        if traits.tolerance_option in (kwargs or {}):
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    f"tolerance and optimizer_kwargs.{traits.tolerance_option} both set "
                    f"the stopping rule of {method!r}. Keep one.",
                )
            )
    return findings


def _declared_precisions(calibration: Any) -> list[tuple[str, str, float | None, dict]]:
    """Return one entry per search: where it is written, its engine and its precision."""
    if not calibration.phases:
        return [
            (
                "[calibration]",
                str(calibration.method),
                calibration.tolerance,
                dict(calibration.optimizer_kwargs or {}),
            )
        ]
    return [
        (
            f"[[calibration.phases]] {phase.name!r}",
            str(phase.method),
            phase.tolerance,
            dict(phase.optimizer_kwargs or {}),
        )
        for phase in calibration.phases
    ]


def _check_the_backend_can_serve_the_outputs(
    config: Any, calibration: Any
) -> list[PreflightFinding]:
    """Face each declared output with what the chosen backend says it can serve.

    A backend answers on the resolved configuration in three states, so this
    separates two refusals a binary answer confuses: one declaration away, with
    the declaration named, and out of reach on this backend whatever the file
    says. Both used to arrive at the first extraction, hours into a search.
    """
    adapter = _flow_adapter_for(config)
    if adapter is None:
        return []
    declared = getattr(adapter, "declared_observables", None)
    if declared is None:
        return []
    support_by_name = {item.name: item for item in declared(config)}
    findings: list[PreflightFinding] = []
    for name, decl in (calibration.outputs or {}).items():
        observable = _OBSERVABLE_BY_SUPPORT.get(str(getattr(decl, "support", "")))
        if observable is None:
            continue
        support = support_by_name.get(observable)
        if support is None or support.is_servable_now:
            continue
        findings.append(
            PreflightFinding(
                "error",
                f"[calibration.outputs.{name}]",
                f"this output reads {observable!r}, which the chosen backend does not "
                f"serve as configured: {support.reason}",
            )
        )
    return findings


def _flow_adapter_for(config: Any) -> Any | None:
    """Return the flow adapter this configuration selects, or ``None``."""
    from hydromodpy.solver.base.registry import get_solver_adapter

    backend = getattr(getattr(config, "solver", None), "backend_name", None)
    backend = getattr(backend, "value", backend)
    if not backend:
        return None
    try:
        return get_solver_adapter("flow", str(backend))
    except (KeyError, ValueError):
        return None


def _searches(calibration: Any) -> list[tuple[str, str, list[str], set[str], int]]:
    """Return one entry per search: where it is written, and what it is handed."""

    def _metrics_of(selected: list[str], single: str | None) -> set[str]:
        if single:
            return {str(single)}
        # Collapsed by name, last one wins. Two blocks may share a name - the
        # file is refused for it, but this runs before that refusal is reached,
        # and keeping both would change which of the other findings fire.
        by_name = {
            block.name: str(block.metric) for block in _phase_named_blocks(calibration, selected)
        }
        return set(by_name.values())

    if not calibration.phases:
        return [
            (
                "[calibration]",
                str(calibration.method),
                sorted(calibration.parameters or {}),
                _metrics_of([], None if calibration.objective_blocks else calibration.objective),
                int(calibration.parallel),
            )
        ]
    return [
        (
            f"[[calibration.phases]] {phase.name!r}",
            str(phase.method),
            list(phase.parameters),
            _metrics_of(list(phase.objective_blocks), phase.objective),
            int(phase.parallel),
        )
        for phase in calibration.phases
    ]


def _phase_named_blocks(calibration: Any, names: list[str]) -> list[Any]:
    """Return the objective blocks named, or every declared one when none are.

    The name-matching rule ``_searches`` applies to build each search's metric
    set, factored out so a linearized width's per-phase check does not write a
    second version of it. ``_searches`` collapses the result by block name on
    top of this; the width check reads the block objects themselves.
    """
    declared = list(calibration.objective_blocks or [])
    if not names:
        return declared
    selected = set(names)
    return [block for block in declared if block.name in selected]


def _linearized_scored_outputs(
    calibration: Any,
) -> list[tuple[str, Mapping[str, Any], list[Any], bool]]:
    """Return, per search, its label, what it actually scores, and whether it is single-metric.

    Mirrors the output and block selection
    ``hydromodpy.calibration.runners.staged_runner._phase_config`` builds for
    a phase: naming no block reads every declared one, naming no output reads
    what the blocks read, and a single-metric phase (naming its own
    ``variable`` or ``objective`` instead of blocks) reads neither -- there is
    nothing there for a linearized width to be built from, which is a finding
    of its own rather than a silent skip.

    The output filter below reads ``phase.objective_blocks`` -- the phase's OWN
    declaration -- exactly as ``_phase_config`` does. Reading the resolved
    ``blocks`` list instead (non-empty whenever the calibration declares any
    block at all, even one the phase never named) filters outputs down to what
    OTHER phases' blocks read, dropping an output this phase would have kept.
    """
    if not calibration.phases:
        return [
            (
                "[calibration.uncertainty]",
                calibration.outputs or {},
                list(calibration.objective_blocks or []),
                False,
            )
        ]
    result: list[tuple[str, Mapping[str, Any], list[Any], bool]] = []
    for phase in calibration.phases:
        where = f"[[calibration.phases]] {phase.name!r}"
        if phase.is_single_metric:
            result.append((where, {}, [], True))
            continue
        outputs = dict(calibration.outputs or {})
        blocks = _phase_named_blocks(calibration, list(phase.objective_blocks))
        if phase.outputs:
            outputs = {name: outputs[name] for name in phase.outputs if name in outputs}
        elif phase.objective_blocks:
            read = {name for block in blocks for name in block.uses_outputs}
            outputs = {name: value for name, value in outputs.items() if name in read}
        result.append((where, outputs, blocks, False))
    return result


def _missing(
    where: str,
    key: str,
    named: Iterable[str],
    declared: set[str],
    section: str,
) -> list[PreflightFinding]:
    unknown = sorted({str(item) for item in named} - declared)
    if not unknown:
        return []
    available = ", ".join(sorted(declared)) or "nothing"
    return [
        PreflightFinding(
            "error",
            where,
            f"{key} names {', '.join(unknown)}, which {section} does not declare. "
            f"Declared: {available}.",
        )
    ]


__all__ = ["PreflightFinding", "Severity", "preflight_calibration"]
