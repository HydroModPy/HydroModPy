"""The preflight checks of the matching-network criterion."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.calibration.preflight_report import finding
from hydromodpy.calibration.preflight_searches import (
    config_of,
    declared_searches,
    outputs_scored_by_search,
    phase_named_blocks,
    publishes_a_signed_residual,
    raw_document,
    resolved_paths,
    roots_of_the_search,
    search_candidates,
)
from hydromodpy.core.diagnostic import Diagnostic


def check_the_network_criterion_is_not_asked_to_pick_a_ridge(
    calibration: Any, searched: Mapping[str | None, Any]
) -> list[Diagnostic]:
    """Warn when an objective scored only on network output(s) moves more than one parameter.

    The network criterion constrains a transmissivity-like combination (T/R).
    Two parameters that both act on it -- K and the aquifer thickness, for
    instance -- form a ridge in that cost, and the search returns one point of
    the ridge rather than an identifiable pair. Not an error: a staged
    protocol may freeze every other parameter first and mean exactly this.

    K beside the recharge factor in a steady search is an error: that state reads
    K/R and nothing else, so the ridge is exact.
    """
    from hydromodpy.calibration.parameter_resolution import RECHARGE_FACTOR_PATH
    from hydromodpy.calibration.runners.prepared_model import moves_a_hydraulic_conductivity

    findings: list[Diagnostic] = []
    for phase, where, names in search_candidates(calibration):
        if len(names) <= 1:
            continue
        outputs = outputs_scored_by_search(calibration, phase)
        if not outputs:
            continue
        if not all(output.support == "network" for output in outputs.values()):
            continue
        moved = resolved_paths(calibration, names)
        exact_ridge = (
            RECHARGE_FACTOR_PATH in moved
            and moves_a_hydraulic_conductivity(moved)
            and _search_regime(config_of(searched, phase), phase) == "steady"
        )
        findings.append(
            finding(
                "error" if exact_ridge else "warning",
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


def check_a_minimiser_on_two_bounds(calibration: Any) -> list[Diagnostic]:
    """Refuse a minimiser on one parameter and two weighted bounds.

    A root search combines two roots and a minimiser returns the lowest weighted
    cost, so the value would depend on the method. Several parameters leave no root
    search to differ from: K and the porosity together on the two maps stay open
    for the twin to measure.
    """
    from hydromodpy.calibration.optim.optimizer import engine_traits

    findings: list[Diagnostic] = []
    for (phase, where, names), search in zip(
        search_candidates(calibration), declared_searches(calibration), strict=True
    ):
        method = calibration.method_for(phase)[0]
        if (
            len(names) == 1
            and not engine_traits(method).needs_signed_residual
            and roots_of_the_search(calibration, phase) == 2
            and any(publishes_a_signed_residual(metric) for metric in search[3])
        ):
            findings.append(
                finding(
                    "error",
                    where,
                    f"{method!r} would return the lowest weighted cost over two bounds, where "
                    "a root search returns the mean of two roots, so the value would depend "
                    "on the method. Search with bisection on distance_gap, or weigh one bound "
                    "zero in map.calibrate_on.",
                )
            )
    return findings


def check_the_network_search_can_trust_its_release_packages(
    calibration: Any, searched: Mapping[str | None, Any]
) -> list[Diagnostic]:
    """Refuse a K-moving network search next to an SFR or LAK with a fixed conductance.

    Checked against the boundaries the model of each search declares: a
    phase that turns a package off through its own ``overrides``, as
    ``auto_sfr_drn.toml`` does, is checked without it.
    """
    from hydromodpy.calibration.runners.prepared_model import (
        moves_a_hydraulic_conductivity,
        network_outputs_scored,
        release_package_conductance_conflict,
    )

    findings: list[Diagnostic] = []
    for phase, where, names in search_candidates(calibration):
        config = config_of(searched, phase)
        if config is None:
            continue
        flow = getattr(config, "flow", None)
        outputs = outputs_scored_by_search(calibration, phase)
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
        moves_k = moves_a_hydraulic_conductivity(resolved_paths(calibration, names))
        message = release_package_conductance_conflict(network, flow, moves_k=moves_k)
        if message is not None:
            findings.append(finding("error", where, message))
    return findings


def _search_regime(project_config: Any, phase: Any | None) -> str | None:
    """Return the flow regime one search runs, or ``None`` when nothing says.

    A phase's ``regime`` first, then a ``flow.flow_regime`` its overrides
    write, then the ``[flow]`` of ``project_config``.
    """
    written = getattr(phase, "regime", None)
    if written is None:
        written = (getattr(phase, "overrides", None) or {}).get("flow.flow_regime")
    if written is None:
        written = getattr(getattr(project_config, "flow", None), "flow_regime", None)
    if written is None:
        return None
    return str(getattr(written, "value", written)).strip().lower()


def _extents_scored_by(calibration: Any, phase: Any | None) -> list[tuple[str, Any]]:
    """Return ``(name, model.extent)`` of each network output a search scores with an extent."""
    return [
        (name, output.model.extent)
        for name, output in sorted(outputs_scored_by_search(calibration, phase).items())
        if output.support == "network" and output.model.extent is not None
    ]


def check_an_extent_is_scored_on_a_transient_run(
    calibration: Any, searched: Mapping[str | None, Any]
) -> list[Diagnostic]:
    """Refuse an extent table on a network output a steady search scores.

    The two-bound mode reads the timesteps of a transient run. A steady run
    holds one period, and the criterion refuses it at the first trial, after
    the phases before it have spent their budget.
    """
    findings: list[Diagnostic] = []
    for phase, where, _ in search_candidates(calibration):
        config = config_of(searched, phase)
        if config is None or _search_regime(config, phase) != "steady":
            continue
        for name, _extent in _extents_scored_by(calibration, phase):
            ran_by = "[flow] flow_regime" if phase is None else where
            findings.append(
                finding(
                    "error",
                    f"[calibration.outputs.{name}]",
                    f"declares an extent table and is scored by a steady search "
                    f"({ran_by}). The two-bound mode reads the timesteps of a transient "
                    "run, and a steady run holds one period. Score this output in one "
                    "state, without the extent table, or run the search transient.",
                )
            )
    return findings


def check_the_extent_durations_fit_the_timestep(
    calibration: Any, searched: Mapping[str | None, Any]
) -> list[Diagnostic]:
    """Refuse extent durations the timestep of a search cannot read.

    The scoring counts the rules in timesteps of a complete year and refuses
    them at the first trial (``extent_step_problems``). The same test runs here
    on the nominal year of the step the search runs, before any budget is spent.
    A phase that overrides the step is left to that first trial.
    """
    from hydromodpy.catchment.stream_network.extent import (
        dry_steps,
        extent_step_problems,
        flowing_steps,
        parse_extent_duration,
    )
    from hydromodpy.core.time.window import nominal_step_days

    findings: list[Diagnostic] = []
    for phase, _where, _ in search_candidates(calibration):
        config = config_of(searched, phase)
        overrides = getattr(phase, "overrides", None) or {}
        if config is None or any(str(key).startswith("simulation.time") for key in overrides):
            continue
        time = getattr(getattr(config, "simulation", None), "time", None)
        value = getattr(time, "step_value", None)
        unit = getattr(time, "step_unit", None)
        if value is None or unit is None:
            continue
        step_days = nominal_step_days(value, unit)
        for name, extent in _extents_scored_by(calibration, phase):
            try:
                maximal = flowing_steps(parse_extent_duration(extent.flowing_at_least), step_days)
                dry = dry_steps(parse_extent_duration(extent.dry_at_most), step_days)
            except ValueError:
                continue
            problems = extent_step_problems(
                [max(1, round(365.0 / step_days))],
                maximal_flowing_steps=maximal,
                minimal_dry_steps=dry,
            )
            if problems:
                findings.append(
                    finding(
                        "error",
                        f"[calibration.outputs.{name}.model.extent]",
                        f"flowing_at_least = {extent.flowing_at_least!r} and "
                        f"dry_at_most = {extent.dry_at_most!r} cannot be "
                        f"read on a timestep of {step_days:g} days: " + "; ".join(problems) + ".",
                    )
                )
    return findings


def check_a_network_estimator_names_its_network_output(
    calibration: Any,
) -> list[Diagnostic]:
    """Refuse a single-metric search on a network estimator whose variable names no network.

    A search with no block takes the single-metric route. It reads the output
    its ``variable`` names and nothing else, so a network output declared
    beside it is never scored. The route serves only a station variable, so
    the search stops at its first trial.
    """
    from hydromodpy.calibration.criteria.registry import NETWORK_ESTIMATORS

    declared = dict(calibration.outputs or {})
    findings: list[Diagnostic] = []
    for phase, where, _ in search_candidates(calibration):
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
            finding(
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


def check_the_scoring_windows_hold_what_they_score(
    calibration: Any, searched: Mapping[str | None, Any], source: Path
) -> list[Diagnostic]:
    """Refuse a scoring window that cannot hold what its search scores.

    The run refuses it at the first trial of the search, after the phases
    before it have spent their budget. Two cases. A block on an output with no
    date, a vector typed into the file, has nothing a window can cut. A network
    output read in one state is dated at the stamp that closes the period it
    reads, the first, the last or the one holding its date, and the window has
    to hold that stamp. The stamp is read on the time grid the search runs:
    one period over the steady window for a steady phase, the project's own
    grid otherwise, written with the phase's overrides. A date on ``time`` that
    grid does not hold is refused too, window or not.
    """
    import pandas as pd

    from hydromodpy.calibration.metrics.observable_scoring import (
        bound_text,
        refuse_window_without_dates,
    )
    from hydromodpy.calibration.metrics.observed_pairing import observing_outputs
    from hydromodpy.core.time.selection import TimeSelectionError, resolve_state

    findings: list[Diagnostic] = []
    document: list[Mapping[str, Any] | None] = []
    for phase, where, _ in search_candidates(calibration):
        if phase is not None and phase.is_single_metric:
            continue
        blocks = (
            phase_named_blocks(calibration, list(phase.objective_blocks))
            if phase is not None
            else list(calibration.objective_blocks or [])
        )
        if not blocks:
            continue
        outputs = outputs_scored_by_search(calibration, phase)
        config = config_of(searched, phase)
        edges = None if config is None else _search_edges(config, phase, source, document)
        declared = getattr(phase, "window", None) or calibration.window
        # Validated when the file was read, so both bounds parse.
        window = (
            None
            if declared is None
            else tuple(
                None if bound is None else pd.Timestamp(bound)
                for bound in (declared.start, declared.end)
            )
        )
        read = {str(name) for block in blocks for name in block.uses_outputs}
        for name in sorted(read & set(outputs)):
            output = outputs[name]
            if output.support != "network" or output.model.extent is not None:
                continue
            if edges is None or output.time in ("first", "last"):
                continue
            try:
                resolve_state(output.time, edges, n_periods=len(edges) - 1)
            except TimeSelectionError as exc:
                findings.append(
                    finding(
                        "error",
                        f"[calibration.outputs.{name}]",
                        f"time = {output.time!r} names no state of the run {where} scores "
                        f"it in: {exc}",
                    )
                )
                edges = None
        if window is not None and edges is not None and len(edges) > 1:
            first, last = pd.Timestamp(edges[0]), pd.Timestamp(edges[-1])
            start, end = window
            if (start is not None and start > last) or (end is not None and end < first):
                findings.append(
                    finding(
                        "error",
                        where,
                        f"window {bound_text(start)} to {bound_text(end)} holds no date of the "
                        f"run, which runs from {bound_text(first)} to {bound_text(last)}. Move the "
                        "window inside the run.",
                    )
                )
                continue
        try:
            refuse_window_without_dates(
                outputs, blocks, window, observing_outputs(outputs), boundaries=edges
            )
        except ValueError as exc:
            findings.append(finding("error", where, str(exc)))
    return findings


def _search_edges(
    project_config: Any,
    phase: Any | None,
    source: Path,
    document: list[Mapping[str, Any] | None],
) -> tuple[Any, ...] | None:
    """Return the period bounds of the time grid one search runs, or ``None``.

    A steady phase runs one period over its steady window, read from the raw
    document as the run reads it. Any other search runs the grid of
    ``project_config``, the model the search runs, its phase's overrides
    written in. ``None`` when that cannot be told here: a steady window the
    regime check already refuses, or a project with no dated grid.
    ``document`` caches the raw document between searches, read once.
    """
    import pandas as pd

    from hydromodpy.core.time.selection import grid_edges
    from hydromodpy.core.time.window import resolve_simulation_time_grid

    if getattr(phase, "regime", None) == "steady":
        from hydromodpy.calibration.runners.phase_regime import regime_overrides

        if not document:
            try:
                document.append(raw_document(project_config, source))
            except (OSError, ValueError):
                document.append(None)
        if document[0] is None:
            return None
        try:
            written = regime_overrides(phase, document[0])
        except ValueError:
            return None
        start = pd.Timestamp(written["simulation.time.start_datetime"])
        # Spelled with a unit: ``pd.Timedelta(days=n)`` warns under the pinned NumPy.
        span = pd.Timedelta(int(written["simulation.time.step_value"]), unit="D")
        return (start, start + span)
    try:
        edges = grid_edges(resolve_simulation_time_grid(project_config))
    except (TypeError, ValueError):
        # A [simulation.time] the run cannot read is refused by the run itself,
        # with its own message; this check has no grid to date a state on.
        return None
    return None if edges is None else tuple(edges)
