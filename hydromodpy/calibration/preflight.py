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
    findings.extend(_check_the_regimes(calibration, where_from))
    findings.extend(_check_engines(calibration))
    findings.extend(_check_the_precision_can_be_honoured(calibration))
    findings.extend(_check_the_budgets(calibration))
    findings.extend(_check_the_interval_widths(calibration))
    findings.extend(_check_the_backend_can_serve_the_outputs(config, calibration))
    findings.extend(_check_the_network_criterion_is_not_asked_to_pick_a_ridge(calibration))
    findings.extend(_check_the_network_search_can_trust_its_release_packages(calibration, config))
    findings.extend(_check_the_minimal_maps_are_there(calibration, where_from))
    findings.extend(_check_an_extent_is_scored_on_a_transient_run(calibration, config))
    findings.extend(_check_a_network_estimator_names_its_network_output(calibration))
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
    from hydromodpy.calibration.optim.parameters import assert_bounds_are_physical

    if len(bounds) != 2:
        return []
    try:
        assert_bounds_are_physical(name, float(bounds[0]), float(bounds[1]), decl.units)
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
    ``observed_network`` or ``minimal_observed_network`` is faced with the
    project the same way a parameter's name is faced with the catalogue:
    refused here beside whatever else is wrong, rather than at the first trial.
    """
    from hydromodpy.calibration.observations.network_source import (
        unresolved_minimal_observed_networks,
        unresolved_observed_networks,
    )
    from hydromodpy.calibration.runners.cli_runner import resolve_stream_geometry_paths

    resolve_stream_geometry_paths(calibration, source)
    refused_networks = unresolved_observed_networks(calibration, project_config)
    refused_minimal_networks = unresolved_minimal_observed_networks(calibration, project_config)
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
        if name in refused_minimal_networks:
            findings.append(
                PreflightFinding(
                    "error",
                    where,
                    # The finding already names the section in its 'where' column.
                    refused_minimal_networks[name].replace(f"{where} ", "", 1),
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


def _check_the_regimes(calibration: Any, source: Path) -> list[PreflightFinding]:
    """Write every phase's regime the way the run will, and report what cannot be.

    A steady phase reads its window from ``steady_window`` or from
    ``[simulation.time]`` of the raw document, which is what the run reads too.
    A window given backwards, with one offset, or in no readable spelling is
    otherwise found only when the run starts.
    """
    phases = [
        phase for phase in calibration.phases or () if getattr(phase, "regime", None) is not None
    ]
    if not phases:
        return []
    from hydromodpy.calibration.runners.phase_regime import regime_overrides
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    try:
        document = load_toml_with_base_config(source)
    except (OSError, ValueError) as exc:
        return [
            PreflightFinding(
                "error",
                "[simulation.time]",
                f"the phases that give a regime read their window from {source.name}, "
                f"which cannot be read: {exc}",
            )
        ]
    findings: list[PreflightFinding] = []
    for phase in phases:
        try:
            regime_overrides(phase, document)
        except ValueError as exc:
            findings.append(
                PreflightFinding(
                    "error",
                    f"[[calibration.phases]] {phase.name!r}",
                    f"regime = {phase.regime!r} cannot be written: {exc}",
                )
            )
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
    linearized = _linearized_scored_outputs(calibration)
    if linearized:
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

        for where, outputs, blocks, single_metric in linearized:
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
    for where, method, tolerance, kwargs, restarts in _declared_precisions(calibration):
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


def _declared_precisions(
    calibration: Any,
) -> list[tuple[str, str, float | None, dict, int | None]]:
    """Return one entry per search: where it is written, its engine, its precision, its restarts.

    The engine is the one the search runs: a method left unwritten is checked as
    the run will choose it. The restarts are the phase's own over the section's.
    """
    if not calibration.phases:
        return [
            (
                "[calibration]",
                calibration.method_for()[0],
                calibration.tolerance,
                dict(calibration.optimizer_kwargs or {}),
                calibration.uncertainty.restarts,
            )
        ]
    return [
        (
            f"[[calibration.phases]] {phase.name!r}",
            calibration.method_for(phase)[0],
            phase.tolerance,
            dict(phase.optimizer_kwargs or {}),
            calibration.uncertainty_for(phase).restarts,
        )
        for phase in calibration.phases
    ]


def _check_the_budgets(calibration: Any) -> list[PreflightFinding]:
    """Refuse a root-search budget below its nominal count, announce one below its worst.

    The root search counts its evaluations from its bounds, sweep, tolerance and
    bracket expansions (:func:`~hydromodpy.calibration.optim.adapters.
    bisection_adapter.root_search_budget`), so a budget that cannot close the
    bracket even with the root inside the bounds is a configuration error,
    found here rather than after the budget is spent. ``"auto"`` is always
    enough. Every other engine cannot count, and nothing is checked. A search
    scored on a network output with two bounds closes two roots, and is
    counted so.
    """
    from hydromodpy.calibration.optim.adapters.bisection_adapter import (
        BisectionAdapter,
        root_search_budget,
    )
    from hydromodpy.calibration.optim.stopping import AUTO_BUDGET, short_budget

    findings: list[PreflightFinding] = []
    searches = zip(_budgets(calibration), _search_candidates(calibration), strict=True)
    for (where, method, names, max_iter, tolerance, kwargs), (phase, _, _) in searches:
        if method != BisectionAdapter.name or max_iter == AUTO_BUDGET or len(names) != 1:
            continue
        decl = (calibration.parameters or {}).get(names[0])
        bounds = list(getattr(decl, "bounds", None) or ())
        if len(bounds) != 2:
            continue
        rel_tol = tolerance if tolerance is not None else kwargs.get("rel_tol")
        options = {
            key: value
            for key, value in (
                ("rel_tol", rel_tol),
                ("sweep_points", kwargs.get("sweep_points")),
                ("bracket_expand", kwargs.get("bracket_expand")),
            )
            if value is not None
        }
        if kwargs.get("signed_component") in (None, "J_signed"):
            options["roots"] = _roots_of_the_search(calibration, phase)
        try:
            counted = root_search_budget(float(bounds[0]), float(bounds[1]), **options)
        except (TypeError, ValueError):
            # Bounds or options the other checks already refuse.
            continue
        verdict = short_budget(counted, int(max_iter))
        if verdict is None:
            continue
        severity, detail = verdict
        if getattr(calibration, "protocol", None) is not None:
            detail += (
                " A protocol stage takes its max_iter from [calibration.protocol] "
                "steady_max_iter or transient_max_iter."
            )
        findings.append(PreflightFinding(severity, where, detail))
    return findings


def _roots_of_the_search(calibration: Any, phase: Any | None) -> int:
    """Return how many roots a root search closes on the network outputs it scores.

    A whole-file search whose variable names a declared output carries the
    implicit block the model builds, so the blocks already name that output.
    One whose variable names none scores no network output, and
    :func:`_check_a_network_estimator_names_its_network_output` refuses it.
    """
    from hydromodpy.calibration.optim.adapters.bisection_adapter import roots_scored

    outputs = _outputs_scored_by_search(calibration, phase)
    return roots_scored(
        output for output in outputs.values() if getattr(output, "support", None) == "network"
    )


def _budgets(calibration: Any) -> list[tuple[str, str, list[str], Any, float | None, dict]]:
    """Return one entry per search: where its budget is written, its engine and its options."""
    if not calibration.phases:
        return [
            (
                "[calibration]",
                calibration.method_for()[0],
                sorted(calibration.parameters or {}),
                calibration.max_iter,
                calibration.tolerance,
                dict(calibration.optimizer_kwargs or {}),
            )
        ]
    return [
        (
            f"[[calibration.phases]] {phase.name!r}",
            calibration.method_for(phase)[0],
            list(phase.parameters),
            phase.max_iter,
            phase.tolerance,
            dict(phase.optimizer_kwargs or {}),
        )
        for phase in calibration.phases
    ]


def _check_the_interval_widths(calibration: Any) -> list[PreflightFinding]:
    """Refuse a relative width on a search scored only by network distances.

    A relative width is a fraction of the best cost. A network distance is in
    metres and solved at zero, so a fraction of it says nothing about how far a
    stream may move. The width is read after the last solve, so this is where
    it is named, before any of it is paid for.
    """
    searches = [(None, "[calibration.uncertainty]")] if not calibration.phases else []
    searches += [
        (phase, f"[[calibration.phases]] {phase.name!r}") for phase in calibration.phases or ()
    ]
    findings: list[PreflightFinding] = []
    for phase, where in searches:
        width = calibration.interval_width_for(phase)
        if width.mode != "relative" or not width.on_distances:
            continue
        written = (
            "in this phase" if width.mode_source == "phase" else "in [calibration.uncertainty]"
        )
        findings.append(
            PreflightFinding(
                "error",
                where,
                f"mode = 'relative', written {written}, reads the interval width as a "
                "fraction of the best cost, and this search is scored only on network "
                "distances, in metres, solved at zero: a fraction of a distance has no "
                "meaning. Write mode = 'absolute' with a tolerance in metres, or leave "
                "both unwritten for one mesh cell.",
            )
        )
    return findings


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
    """Return one entry per search: where it is written, and what it is handed.

    The engine is the one the search runs: a method left unwritten is faced with
    its traits as the run will choose it.
    """

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
                calibration.method_for()[0],
                sorted(calibration.parameters or {}),
                _metrics_of([], None if calibration.objective_blocks else calibration.objective),
                int(calibration.parallel),
            )
        ]
    return [
        (
            f"[[calibration.phases]] {phase.name!r}",
            calibration.method_for(phase)[0],
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
    """Return, per search whose width is linearized, its label, what it scores, and more.

    The last item says whether the search is single-metric. A search reads the
    method of its phase over the section's, so only the phases that end up
    linearized are returned.

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
        if calibration.uncertainty.method != "linearized":
            return []
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
        if calibration.uncertainty_for(phase).method != "linearized":
            continue
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


def _search_candidates(calibration: Any) -> list[tuple[Any | None, str, list[str]]]:
    """Return ``(phase, where, moved-parameter names)`` for every search this file declares.

    ``phase`` is ``None`` for a mono-phase document, which is what
    :func:`_outputs_scored_by_search` reads to tell a whole-file search from a
    phase's own.
    """
    if not calibration.phases:
        return [(None, "[calibration]", sorted(calibration.parameters or {}))]
    return [
        (phase, f"[[calibration.phases]] {phase.name!r}", list(phase.parameters))
        for phase in calibration.phases
    ]


def _outputs_scored_by_search(calibration: Any, phase: Any | None) -> dict[str, Any]:
    """Return the outputs one search scores, keyed by name.

    Generalises the selection :func:`_linearized_scored_outputs` builds for a
    linearized width to every search: naming no block reads every declared
    output, naming no output reads what the blocks read. A single-metric
    phase (its own ``variable``/``objective`` instead of blocks) never turns
    its ``variable`` into a per-phase ``objective_blocks`` entry the way the
    whole-file ``(objective, variable)`` pair does, so it is resolved here
    against ``calibration.outputs`` directly: the phase's own ``variable``,
    falling back to the section's when the phase declares none, the same
    inheritance :func:`hydromodpy.calibration.runners.staged_runner._phase_config`
    applies when it narrows the phase's own configuration. Reading this
    calibration's full declared outputs matters: at runtime that narrowed
    configuration has its ``outputs`` emptied for exactly this route (nothing
    there is meant to be extracted twice), so a network-ridge or a
    release-package check that read ``cfg.outputs`` instead of this
    calibration-level dict would stay blind to a single-metric phase scoring
    a network output.
    """
    outputs = dict(calibration.outputs or {})
    if phase is not None:
        if phase.is_single_metric:
            variable = phase.variable if phase.variable is not None else calibration.variable
            output = outputs.get(variable)
            return {variable: output} if output is not None else {}
        blocks = _phase_named_blocks(calibration, list(phase.objective_blocks))
        if phase.outputs:
            return {name: outputs[name] for name in phase.outputs if name in outputs}
        read = {name for block in blocks for name in block.uses_outputs}
        return {name: value for name, value in outputs.items() if name in read}
    blocks = list(calibration.objective_blocks or [])
    if not blocks:
        return {}
    read = {name for block in blocks for name in block.uses_outputs}
    return {name: value for name, value in outputs.items() if name in read}


def _resolved_paths(calibration: Any, names: Iterable[str]) -> list[str | None]:
    """Return the effective target path of every named declared parameter."""
    parameters = calibration.parameters or {}
    return [parameters[name].resolve_target() for name in names if name in parameters]


def _check_the_network_criterion_is_not_asked_to_pick_a_ridge(
    calibration: Any,
) -> list[PreflightFinding]:
    """Warn when an objective scored only on network output(s) moves more than one parameter.

    The network criterion constrains a transmissivity-like combination (T/R).
    Two parameters that both act on it -- K and the aquifer thickness, for
    instance -- form a ridge in that cost, and the search returns one point of
    the ridge rather than an identifiable pair. Not an error: a staged
    protocol may freeze every other parameter first and mean exactly this.
    """
    findings: list[PreflightFinding] = []
    for phase, where, names in _search_candidates(calibration):
        if len(names) <= 1:
            continue
        outputs = _outputs_scored_by_search(calibration, phase)
        if not outputs:
            continue
        if not all(output.support == "network" for output in outputs.values()):
            continue
        findings.append(
            PreflightFinding(
                "warning",
                where,
                f"scores only network output(s) {', '.join(sorted(outputs))} and moves "
                f"{len(names)} parameters at once ({', '.join(names)}). The network "
                "criterion constrains a transmissivity-like combination (T/R): two "
                "parameters that both act on it form a ridge, and the search returns one "
                "point of that ridge, not an identifiable pair. Freeze every parameter "
                "but one, or score an output this search does not share the ridge on.",
            )
        )
    return findings


def _check_the_network_search_can_trust_its_release_packages(
    calibration: Any, project_config: Any
) -> list[PreflightFinding]:
    """Refuse a K-moving network search next to an SFR or LAK with a fixed conductance.

    Checked against the project's base ``flow.active_bc``. A phase that turns a
    package off through its own ``overrides`` (as ``auto_sfr_drn.toml`` does by
    hand) is not replayed here: this preflight reads the declared file, not a
    resolved run, so a false positive is possible on such a phase and the
    runner guard right before the first solve, which sees the actual flow that
    phase built, has the last word.
    """
    from hydromodpy.calibration.runners.cli_runner import (
        moves_a_hydraulic_conductivity,
        network_outputs_scored,
        release_package_conductance_conflict,
    )

    flow = getattr(project_config, "flow", None)
    findings: list[PreflightFinding] = []
    for phase, where, names in _search_candidates(calibration):
        outputs = _outputs_scored_by_search(calibration, phase)
        if phase is not None and phase.is_single_metric:
            network = network_outputs_scored(
                outputs,
                variable=phase.variable if phase.variable is not None else calibration.variable,
                objective=phase.objective if phase.objective is not None else calibration.objective,
            )
        else:
            network = network_outputs_scored(outputs)
        if not network:
            continue
        moves_k = moves_a_hydraulic_conductivity(_resolved_paths(calibration, names))
        message = release_package_conductance_conflict(network, flow, moves_k=moves_k)
        if message is not None:
            findings.append(PreflightFinding("error", where, message))
    return findings


def _check_the_minimal_maps_are_there(calibration: Any, source: Path) -> list[PreflightFinding]:
    """Refuse a ``minimal_stream_geometry_path`` that is not there.

    Looked for where the run looks, anchored on the file that declares it, as
    ``stream_geometry_path`` is. The run would read it at the first trial.
    """
    from hydromodpy.calibration.runners.cli_runner import resolve_stream_geometry_paths

    resolve_stream_geometry_paths(calibration, source)
    findings: list[PreflightFinding] = []
    for name, decl in (calibration.outputs or {}).items():
        geometry = getattr(decl, "minimal_stream_geometry_path", None)
        if geometry and not Path(str(geometry)).exists():
            findings.append(
                PreflightFinding(
                    "error",
                    f"[calibration.outputs.{name}]",
                    f"minimal_stream_geometry_path {geometry!r} is not there, and none of "
                    "the places the run looks holds it. The minimal map is read at the "
                    "first trial, so the run would stop there.",
                )
            )
    return findings


def _search_regime(project_config: Any, phase: Any | None) -> str | None:
    """Return the flow regime one search runs, or ``None`` when nothing says.

    A phase's ``regime`` first, then a ``flow.flow_regime`` its overrides
    write, then the project's own ``[flow]``.
    """
    written = getattr(phase, "regime", None)
    if written is None:
        written = (getattr(phase, "overrides", None) or {}).get("flow.flow_regime")
    if written is None:
        written = getattr(getattr(project_config, "flow", None), "flow_regime", None)
    if written is None:
        return None
    return str(getattr(written, "value", written)).strip().lower()


def _check_an_extent_is_scored_on_a_transient_run(
    calibration: Any, project_config: Any
) -> list[PreflightFinding]:
    """Refuse an extent table on a network output a steady search scores.

    The two-bound mode reads the timesteps of a transient run. A steady run
    holds one period, and the criterion refuses it at the first trial, after
    the phases before it have spent their budget.
    """
    findings: list[PreflightFinding] = []
    for phase, where, _ in _search_candidates(calibration):
        if _search_regime(project_config, phase) != "steady":
            continue
        outputs = _outputs_scored_by_search(calibration, phase)
        for name, output in sorted(outputs.items()):
            if getattr(output, "extent", None) is None:
                continue
            ran_by = "[flow] flow_regime" if phase is None else where
            findings.append(
                PreflightFinding(
                    "error",
                    f"[calibration.outputs.{name}]",
                    f"declares an extent table and is scored by a steady search "
                    f"({ran_by}). The two-bound mode reads the timesteps of a transient "
                    "run, and a steady run holds one period. Score this output in one "
                    "state, without the extent table, or run the search transient.",
                )
            )
    return findings


def _check_a_network_estimator_names_its_network_output(
    calibration: Any,
) -> list[PreflightFinding]:
    """Refuse a single-metric search on a network estimator whose variable names no network.

    A search with no block takes the single-metric route. It reads the output
    its ``variable`` names and nothing else, so a network output declared
    beside it is never scored. The route serves only a station variable, so
    the search stops at its first trial.
    """
    from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS

    declared = dict(calibration.outputs or {})
    findings: list[PreflightFinding] = []
    for phase, where, _ in _search_candidates(calibration):
        if phase is None:
            if calibration.objective_blocks:
                continue
            variable, objective = calibration.variable, calibration.objective
        elif phase.is_single_metric:
            variable = phase.variable if phase.variable is not None else calibration.variable
            objective = phase.objective if phase.objective is not None else calibration.objective
        else:
            continue
        if str(objective).strip().lower() not in NETWORK_ESTIMATORS:
            continue
        if getattr(declared.get(variable), "support", None) == "network":
            continue
        networks = sorted(
            name
            for name, output in declared.items()
            if getattr(output, "support", None) == "network"
        )
        named = ", ".join(networks) or "none"
        findings.append(
            PreflightFinding(
                "error",
                where,
                f"objective {objective!r} scores a network output, and variable {variable!r} "
                f"names none this file declares (network outputs: {named}). With no block, "
                "the search reads only the output its variable names. Name the network "
                "output in variable, or score it through a [[calibration.objective_blocks]] "
                "entry.",
            )
        )
    return findings


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
