"""The finding constructor and the report lines of the calibration preflight."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.diagnostic import Diagnostic, Severity

_CODE = "calibration_preflight"


_KEY_AND_TAIL = re.compile(r"^\[{1,2}(?P<key>[^\]]+)\]{1,2}(?:\s+(?P<tail>.+))?$")


def finding(severity: Severity, where: str, detail: str) -> Diagnostic:
    """Return one preflight finding as a :class:`Diagnostic` of code ``calibration_preflight``.

    ``where`` is the key as the checks below write it, ``[calibration.outputs.net]``
    or ``[[calibration.phases]] 'k' overrides``. The key becomes the dotted
    ``path``. The text after the key, a phase name or a word such as ``bounds``,
    goes to the head of ``detail`` so the finding says all it said before. A
    ``where`` that is not a bracketed key is kept as the path.
    """
    found = _KEY_AND_TAIL.match(where)
    if found is None:
        return Diagnostic(path=where, code=_CODE, severity=severity, detail=detail)
    tail = found["tail"]
    return Diagnostic(
        path=found["key"],
        code=_CODE,
        severity=severity,
        detail=f"{tail}: {detail}" if tail else detail,
    )


def protocol_lines(cfg: Any) -> tuple[list[str], list[str]]:
    """Say which published method a file runs, and where this run leaves it.

    Returns the lines a reader acts on, then the ones only ``-v`` prints: the
    stages, the references, and every reading of the paper this implementation
    makes. A value equal to the paper's, or written the way the recipe runs it
    anyway, is not a departure. A departure no key brings back is named on one
    line of the first list, and said in full in the second.
    """
    declared = getattr(getattr(cfg, "calibration", None), "protocol", None)
    if declared is None:
        return [], []
    from hydromodpy.calibration.protocols.base import protocol_support
    from hydromodpy.calibration.protocols.matching_hydrographic_network import (
        options_the_recipe_already_runs,
        why_the_spin_up_year_is_scored,
    )
    from hydromodpy.calibration.protocols.registry import (
        deviations_in_force,
        get_protocol,
        protocol_record,
    )

    record = protocol_record(declared.name, declared)
    time = getattr(getattr(cfg, "simulation", None), "time", None)
    normal: list[str] = [f"protocol: {record['name']}@{record['version']} - {record['title']}"]
    verbose: list[str] = [
        f"  stage {index}: {stage}" for index, stage in enumerate(record["stages"], start=1)
    ]
    # The protocol drops its default window without a word on a short run, so
    # this is where the reader learns the spin-up year is scored.
    whole_run = why_the_spin_up_year_is_scored(cfg.calibration, time)
    if whole_run is not None:
        normal.append(f"  stage 2 scores the whole run, spin-up year included: {whole_run}")
    verbose.extend(f"  cite: {reference}" for reference in record["references"])
    # Where this run departs from the publication it cites. A reader comparing a
    # result to the literature needs this before the run, not after.
    always: list[str] = []
    for item in deviations_in_force(
        cfg.calibration,
        getattr(cfg, "geographic", None),
        getattr(getattr(cfg, "metrics", None), "window", None),
    ):
        told = f"{item.here} (paper: {item.paper})"
        if item.written:
            suffix = f" - this file sets {_rendered(item.value)}"
        elif item.value is not None:
            suffix = f" - value in force: {_rendered(item.value)}"
        else:
            suffix = ""
        if item.state == "always":
            always.append(item.key)
            verbose.append(f"  always differs from the paper on {item.key}: {told}")
        elif item.state == "departs":
            normal.append(f"  differs from the paper on {item.key}: {told}{suffix}")
        elif item.state == "reads_paper":
            verbose.append(f"  reads the paper on {item.key}: {told}")
        else:
            verbose.append(f"  as the paper on {item.key}: {told}{suffix}")
    if always:
        normal.append(
            f"  always differs from the paper on: {', '.join(always)} (-v says how; no key "
            "brings these back)"
        )
    # An option moved off the recipe keeps the method but changes what the number
    # rests on, and only the file knows it moved.
    same = options_the_recipe_already_runs(
        declared,
        cfg.calibration,
        time,
        metrics_window=getattr(getattr(cfg, "metrics", None), "window", None),
    )
    for option in record.get("options_away_from_the_recipe", ()):
        line = f"{option['key']} = {_rendered(option['here'])}"
        if option["key"] in same:
            verbose.append(f"  option written as the recipe runs it: {line}")
        else:
            normal.append(
                f"  option away from the recipe: {line} (recipe: {_rendered(option['recipe'])})"
            )
    backend = getattr(getattr(cfg, "solver", None), "backend_name", None)
    backend = str(getattr(backend, "value", backend) or "")
    if backend:
        # The registered protocol lists the observables its stages read; the
        # declared section carries the options only.
        verdict = protocol_support(get_protocol(declared.name), backend)
        if verdict.verdict != "tested":
            if verdict.reason:
                normal.append(
                    f"  on {backend}: {verdict.verdict} - the backend says: {verdict.reason}."
                )
            else:
                normal.append(
                    f"  on {backend}: {verdict.verdict.replace('_', ' ')} - no case in this "
                    "repository runs the protocol on that backend."
                )
    return normal, verbose


def _rendered(value: object) -> str:
    """Return a value as a reader of a terminal would want to see it.

    A quantity reprs as ``<Quantity(50, 'meter')>``, which is the object and not
    the number the file wrote. An option left unset reads ``unset``.
    """
    if value is None:
        return "unset"
    if hasattr(value, "magnitude") and hasattr(value, "units"):
        return f"'{value:~P}'"
    return repr(value)


def comparison_lines(cfg: Any, source: Path) -> list[str]:
    """Return what each phase, or the whole section, compares with what.

    First ``[metrics] window``, the window the run is scored on. Then one
    block per line: its criterion, its share, the simulated quantity and what
    it is compared against, and the window the phase scores on. A plain calibration with no
    ``[[calibration.phases]]`` still runs one search, so it gets one table
    under ``[calibration]``. ``source`` anchors a relative
    ``map.complete`` the same way the run would.
    """
    from hydromodpy.calibration.runners.document import (
        declared_window_text,
        resolve_stream_geometry_paths,
    )
    from hydromodpy.calibration.runners.staged_report import objective_comparison_table

    calibration = getattr(cfg, "calibration", None)
    if calibration is None:
        return []
    resolve_stream_geometry_paths(calibration, Path(source))
    lines: list[str] = [metrics_window_line(cfg)]
    for phase in calibration.phases or [None]:
        label = phase.name if phase is not None else "[calibration]"
        table = objective_comparison_table(calibration, phase)
        if not table:
            continue
        lines.append(f"compares ({label}):")
        lines.extend(f"  {comparison_line(row)}" for row in table)
        lines.append(f"  scores on: {declared_window_text(calibration, phase)}")
    return lines


def metrics_window_line(cfg: Any) -> str:
    """Say ``[metrics] window``, the window the run is scored on, or that there is none."""
    window = getattr(getattr(cfg, "metrics", None), "window", None)
    if window is None:
        return "[metrics] window: unset, the run carries no score"
    return f"[metrics] window: {window.start} to {window.end}, the window the run is scored on"


def comparison_line(row: Mapping[str, Any]) -> str:
    """Return one line of what a block, or the single-metric route, compares.

    ``row`` is one entry of
    :func:`hydromodpy.calibration.runners.staged_report.objective_comparison_table`.
    Its ``source`` keeps the absolute path a network output resolved to; here
    only, formatting shortens it when it sits under the working directory, so
    the line does not carry one checkout's full path.
    """
    from hydromodpy.calibration.runners.recap import percent

    label = row["block"] or "single metric"
    source = _shortened_if_under_cwd(row["source"])
    return (
        f"{label}\t{row['metric']}\tshare {percent(row['share'])}\t{row['quantity']}\tvs {source}"
    )


def _shortened_if_under_cwd(text: str) -> str:
    """Return ``text`` relative to the working directory, when it is an absolute path under it."""
    from hydromodpy.core.state.portable import display_path

    if not Path(text).is_absolute():
        return text
    shown = display_path(text)
    return text if Path(shown).is_absolute() else shown


def missing(
    where: str,
    key: str,
    named: Iterable[str],
    declared: set[str],
    section: str,
) -> list[Diagnostic]:
    unknown = sorted({str(item) for item in named} - declared)
    if not unknown:
        return []
    available = ", ".join(sorted(declared)) or "nothing"
    return [
        finding(
            "error",
            where,
            f"{key} names {', '.join(unknown)}, which {section} does not declare. "
            f"Declared: {available}.",
        )
    ]
