"""What a calibration document says about its searches: the roots, the phases that search and the outputs they score."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def config_of(searched: Mapping[str | None, Any], phase: Any | None) -> Any | None:
    """Return the project configuration one search runs, or ``None`` when unknown."""
    return searched.get(None if phase is None else phase.name)


def raw_document(config: Any, source: Path) -> Mapping[str, Any]:
    """Return the raw document a phase reads its regime from.

    The file, ``base_config`` merged, as the run reads it. A project built in
    memory has no file, and the document is its configuration, dumped the way
    ``Project.calibrate`` writes it for the staged runner.
    """
    from hydromodpy.calibration.runners.trial import trial_pipeline

    if source.is_file() or not hasattr(config, "model_dump"):
        return trial_pipeline().load_document(source)
    return config.model_dump(mode="json", exclude_none=True)


def publishes_a_signed_residual(metric: str) -> bool:
    """Whether this criterion's cost IS the absolute residual a root search closes on.

    The answer comes from the criterion, not from a list held here. The network
    criterion publishes ``J_signed`` beside every cost, so merely reading that
    output is not enough: a bisection reports as its best the trial whose cost is
    smallest, and it can only do that when the cost IS that residual, which is
    true of ``distance_gap`` and false of ``distance_mean``. The estimator is
    what knows the difference, so the estimator is what declares it.
    """
    from hydromodpy.calibration.criteria.registry import criterion_for

    return criterion_for(metric).requirements().signed


def roots_of_the_search(calibration: Any, phase: Any | None) -> int:
    """Return how many roots a root search closes on the network outputs it scores.

    A whole-file search whose variable names a declared output carries the
    implicit block the model builds, so the blocks already name that output.
    One whose variable names none scores no network output, and
    :func:`check_a_network_estimator_names_its_network_output` refuses it.
    """
    from hydromodpy.calibration.optim.adapters.bisection_adapter import roots_scored

    outputs = outputs_scored_by_search(calibration, phase)
    return roots_scored(
        output for output in outputs.values() if getattr(output, "support", None) == "network"
    )


def declared_searches(calibration: Any) -> list[tuple[str, str, list[str], set[str], int]]:
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
            block.name: str(block.metric) for block in phase_named_blocks(calibration, selected)
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
            calibration.parallel_for(phase),
        )
        for phase in calibration.phases
    ]


def phase_named_blocks(calibration: Any, names: list[str]) -> list[Any]:
    """Return the objective blocks named, or every declared one when none are.

    The name-matching rule ``declared_searches`` applies to build each search's metric
    set, factored out so a linearized width's per-phase check does not write a
    second version of it. ``declared_searches`` collapses the result by block name on
    top of this; the width check reads the block objects themselves.
    """
    declared = list(calibration.objective_blocks or [])
    if not names:
        return declared
    selected = set(names)
    return [block for block in declared if block.name in selected]


def search_candidates(calibration: Any) -> list[tuple[Any | None, str, list[str]]]:
    """Return ``(phase, where, moved-parameter names)`` for every search this file declares.

    ``phase`` is ``None`` for a mono-phase document, which is what
    :func:`outputs_scored_by_search` reads to tell a whole-file search from a
    phase's own.
    """
    if not calibration.phases:
        return [(None, "[calibration]", sorted(calibration.parameters or {}))]
    return [
        (phase, f"[[calibration.phases]] {phase.name!r}", list(phase.parameters))
        for phase in calibration.phases
    ]


def outputs_scored_by_search(calibration: Any, phase: Any | None) -> dict[str, Any]:
    """Return the outputs one search scores, keyed by name.

    Generalizes the selection :func:`_linearized_scored_outputs` builds for a
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
        blocks = phase_named_blocks(calibration, list(phase.objective_blocks))
        if phase.outputs:
            return {name: outputs[name] for name in phase.outputs if name in outputs}
        read = {name for block in blocks for name in block.uses_outputs}
        return {name: value for name, value in outputs.items() if name in read}
    blocks = list(calibration.objective_blocks or [])
    if not blocks:
        return {}
    read = {name for block in blocks for name in block.uses_outputs}
    return {name: value for name, value in outputs.items() if name in read}


def resolved_paths(calibration: Any, names: Iterable[str]) -> list[str | None]:
    """Return the effective target path of every named declared parameter."""
    parameters = calibration.parameters or {}
    return [parameters[name].resolve_target() for name in names if name in parameters]
