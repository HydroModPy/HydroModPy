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

from collections.abc import Iterable
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
    findings.extend(_check_outputs(calibration, where_from))
    findings.extend(_check_blocks(calibration))
    findings.extend(_check_phases(calibration))
    findings.extend(_check_engines(calibration))
    return findings


def _check_parameters(cfg: Any, calibration: Any) -> list[PreflightFinding]:
    """Check every declared parameter against the configuration it will write into."""
    from hydromodpy.calibration.targets import calibration_targets, targets_by_path

    findings: list[PreflightFinding] = []
    reachable = targets_by_path(calibration_targets(cfg))
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
                PreflightFinding("error", where, "no 'path' (or 'target') to write into.")
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


def _check_outputs(calibration: Any, source: Path) -> list[PreflightFinding]:
    """Check what an output needs that only the filesystem can answer.

    The geometry is looked for exactly where the run looks for it, so a file
    preflight calls missing is one the run would call missing too.
    """
    from hydromodpy.calibration.runners.cli_runner import _resolve_stream_geometry_paths

    _resolve_stream_geometry_paths(calibration, source)
    findings: list[PreflightFinding] = []
    for name, decl in (calibration.outputs or {}).items():
        where = f"[calibration.outputs.{name}]"
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


def _searches(calibration: Any) -> list[tuple[str, str, list[str], set[str], int]]:
    """Return one entry per search: where it is written, and what it is handed."""
    blocks = {block.name: str(block.metric) for block in calibration.objective_blocks or []}
    every_metric = set(blocks.values())

    def _metrics_of(selected: list[str], single: str | None) -> set[str]:
        if single:
            return {str(single)}
        if selected:
            return {blocks[name] for name in selected if name in blocks}
        return set(every_metric)

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
