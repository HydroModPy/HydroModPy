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
