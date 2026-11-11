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

import copy
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydromodpy.core.config_kit.introspect import child_of
from hydromodpy.core.config_kit.written import log_experimental_keys
from hydromodpy.core.console.progress import MILESTONE
from hydromodpy.core.diagnostic import Diagnostic, Severity
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

_CODE = "calibration_preflight"

_KEY_AND_TAIL = re.compile(r"^\[{1,2}(?P<key>[^\]]+)\]{1,2}(?:\s+(?P<tail>.+))?$")


def _finding(severity: Severity, where: str, detail: str) -> Diagnostic:
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


def preflight_calibration(config: Any, *, source: str | Path) -> list[Diagnostic]:
    """Return everything wrong with a loaded calibration, before it runs.

    ``config`` is the resolved project configuration and ``source`` the file it
    came from, which is what a relative geometry path is anchored against.
    Loading is the caller's, because a configuration is assembled a layer above
    this one; a file that will not load has nothing here to check.
    """
    calibration = getattr(config, "calibration", None)
    if calibration is None or not getattr(calibration, "parameters", None):
        return [
            _finding(
                "error",
                "[calibration]",
                "no calibration to run: declare [calibration.parameters.<name>] with "
                "bounds and a path. `hmp config targets` lists what this project "
                "exposes.",
            )
        ]

    where_from = Path(source).expanduser().resolve()
    findings: list[Diagnostic] = []
    searched, unwritable = _search_configs(config, calibration, where_from)
    findings.extend(unwritable)
    findings.extend(_check_parameters(config, calibration))
    findings.extend(_check_outputs(calibration, where_from, config))
    findings.extend(_check_blocks(calibration))
    findings.extend(_check_phases(calibration))
    findings.extend(_check_the_regimes(calibration, config, where_from))
    findings.extend(_check_engines(calibration))
    findings.extend(_check_the_precision_can_be_honoured(calibration))
    findings.extend(_check_the_budgets(calibration))
    findings.extend(_check_the_interval_widths(calibration))
    findings.extend(_check_the_backend_can_serve_the_outputs(calibration, searched))
    findings.extend(
        _check_the_network_criterion_is_not_asked_to_pick_a_ridge(calibration, searched)
    )
    findings.extend(_check_a_minimiser_on_two_bounds(calibration))
    findings.extend(_check_the_network_search_can_trust_its_release_packages(calibration, searched))
    findings.extend(_check_an_extent_is_scored_on_a_transient_run(calibration, searched))
    findings.extend(_check_the_extent_durations_fit_the_timestep(calibration, searched))
    findings.extend(_check_a_network_estimator_names_its_network_output(calibration))
    findings.extend(
        _check_the_scoring_windows_hold_what_they_score(calibration, searched, where_from)
    )
    findings.extend(_check_the_observed_stations_are_loaded(calibration, config))
    return findings


def preflight_launch(
    config_path: str | Path, *, config: Any | None = None, calibration: Any | None = None
) -> list[Diagnostic]:
    """Check the calibration a launch is about to run, before anything is prepared.

    ``config_path`` is the effective document: the file the user named, or
    the copy ``--set``, ``--overlay`` and ``HMP_SET_*`` were written into. It
    is loaded the way the run loads it, protocol expanded and project defaults
    written, and every search is checked with the overrides of its phase.
    ``config`` is that project configuration when the caller holds it already,
    and ``calibration`` the section a Python launch runs in place of the
    file's. A file that does not load as a project is left to the run, which
    says why with its own context. See :func:`refuse_what_the_preflight_refuses`.
    """
    path = Path(config_path).expanduser().resolve()
    if not hasattr(config, "model_copy"):
        # No configuration held, or one that is not a validated model: the
        # file is the configuration.
        from hydromodpy.calibration.runners.trial import trial_pipeline

        pipeline = trial_pipeline()
        try:
            config = pipeline.load_config(path)
        except Exception:
            logger.debug("No project configuration to preflight in %s", path, exc_info=True)
            return []
    if calibration is not None:
        # A copy: the checks anchor geometry paths, and the run anchors its own.
        config = config.model_copy(update={"calibration": calibration.model_copy(deep=True)})
    return refuse_what_the_preflight_refuses(config, source=path)


def refuse_what_the_preflight_refuses(config: Any, *, source: str | Path) -> list[Diagnostic]:
    """Run the preflight at a launch: raise on its errors, log its warnings once.

    The experimental keys of the file are logged here too, once for the session,
    since no trial comes back through this gate.

    The one gate every launch passes, ``hmp calibrate``, ``hmp run``,
    ``--dry-run``, ``hmp.calibrate`` and ``Project.calibrate``, so the launch
    refuses what ``hmp check`` refuses, with every finding at once.
    Raises :class:`~hydromodpy.core.exceptions.ConfigError`, the code of a
    file to fix. Returns the findings, warnings only.
    """
    from hydromodpy.core.exceptions import ConfigError

    findings = preflight_calibration(config, source=source)
    errors = [finding for finding in findings if finding.severity == "error"]
    if errors:
        lines = "\n".join(f"  {finding.path}: {finding.detail}" for finding in errors)
        raise ConfigError(
            f"the calibration is refused before anything is prepared or solved, "
            f"{len(errors)} error(s):\n{lines}",
            diagnostics=errors,
        )
    seen: set[str] = set()
    for finding in findings:
        text = f"{finding.path}: {finding.detail}"
        if text not in seen:
            seen.add(text)
            logger.warning("%s", text)
    log_experimental_keys(config)
    # Where the run leaves the publication it cites, said before the first solve:
    # at the launch as ``hmp check`` says it, and the session writes it down.
    for line in protocol_lines(config)[0]:
        logger.info("%s", line, extra=MILESTONE)
    return findings


def _search_configs(
    config: Any, calibration: Any, source: Path
) -> tuple[dict[str | None, Any], list[Diagnostic]]:
    """Return the project configuration each search runs, keyed by phase name.

    A phase runs the project with its regime and its own ``overrides``
    written in, the way ``prepare_trials`` writes them, so a check on the
    model a search runs reads that model and not the file's base. Key
    ``None`` is the search of a file without phases. A phase whose overrides
    cannot be written is a finding, and its project checks are left out.
    """
    phases = list(calibration.phases or ())
    if not phases:
        return {None: config}, []
    from hydromodpy.calibration.optim.parameters import set_by_path
    from hydromodpy.calibration.runners.phase_regime import phase_overrides
    from hydromodpy.core.config_kit.base import thawed_copy

    document: Mapping[str, Any] = {}
    if any(getattr(phase, "regime", None) is not None for phase in phases):
        try:
            document = _raw_document(config, source)
        except (OSError, ValueError):
            # The regime check reports the file it cannot read.
            document = {}
    configs: dict[str | None, Any] = {}
    findings: list[Diagnostic] = []
    for phase in phases:
        try:
            overrides = phase_overrides(phase, document)
        except (KeyError, ValueError):
            # A regime that cannot be written is the regime check's finding.
            overrides = dict(phase.overrides or {})
        if not overrides:
            configs[phase.name] = config
            continue
        # The configuration of a project is a frozen copy, and the override must land.
        written = thawed_copy(copy.deepcopy(config))
        try:
            for dotted, value in overrides.items():
                set_by_path(written, str(dotted), value)
        except ValueError as exc:
            findings.append(
                _finding(
                    "error",
                    f"[[calibration.phases]] {phase.name!r} overrides",
                    f"cannot be written into the configuration: {exc}",
                )
            )
            continue
        configs[phase.name] = written
    return configs, findings


def _config_of(searched: Mapping[str | None, Any], phase: Any | None) -> Any | None:
    """Return the project configuration one search runs, or ``None`` when unknown."""
    return searched.get(None if phase is None else phase.name)


def _raw_document(config: Any, source: Path) -> Mapping[str, Any]:
    """Return the raw document a phase reads its regime from.

    The file, ``base_config`` merged, as the run reads it. A project built in
    memory has no file, and the document is its configuration, dumped the way
    ``Project.calibrate`` writes it for the staged runner.
    """
    from hydromodpy.calibration.runners.trial import trial_pipeline

    if source.is_file() or not hasattr(config, "model_dump"):
        return trial_pipeline().load_document(source)
    return config.model_dump(mode="json", exclude_none=True)


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
    from hydromodpy.calibration.protocols import (
        deviations_in_force,
        get_protocol,
        options_the_recipe_already_runs,
        protocol_record,
        why_the_spin_up_year_is_scored,
    )
    from hydromodpy.calibration.protocols.base import protocol_support

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
    from hydromodpy.calibration.runners.staged_runner import objective_comparison_table

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
    :func:`hydromodpy.calibration.runners.staged_runner.objective_comparison_table`.
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


_DATA_SECTION_BY_FAMILY: Mapping[str, str] = {
    "discharge": "hydrometry",
    "head": "piezometry",
    "lake_level": "lake_levels",
}
"""The ``[data.<section>]`` that loads each observed family."""


def _check_the_observed_stations_are_loaded(
    calibration: Any, project_config: Any
) -> list[Diagnostic]:
    """Refuse a station that the data step cannot load, from what the file declares.

    The record itself is loaded by the run. What can be told here is narrower and
    certain: every source of the data section of the station's family lists its
    stations, and none is this one. A source that lists no station, and a
    section the file does not write, are left to the run.
    """
    from hydromodpy.calibration.metrics.observed_pairing import OBSERVED_FAMILY_BY_VARIABLE

    data = getattr(project_config, "data", None)
    if data is None:
        return []
    findings: list[Diagnostic] = []
    for name, decl in (calibration.outputs or {}).items():
        station = getattr(decl, "observes", None)
        family = OBSERVED_FAMILY_BY_VARIABLE.get(str(getattr(decl, "variable", "") or ""))
        section = _DATA_SECTION_BY_FAMILY.get(family or "")
        if not station or section is None:
            continue
        where = f"[calibration.outputs.{name}]"
        sources = list(getattr(getattr(data, section, None), "sources", None) or [])
        listed = [list(getattr(source, "station_ids", None) or []) for source in sources]
        if not sources or any(not ids for ids in listed):
            continue
        known = sorted({str(item) for ids in listed for item in ids})
        if str(station) not in known:
            findings.append(
                _finding(
                    "error",
                    where,
                    f"observes station {station!r}, which no source of [data.{section}] "
                    f"lists in station_ids. Listed: {', '.join(known)}. Write one of them, "
                    f"or add the station to a source.",
                )
            )
    return findings


def _check_parameters(cfg: Any, calibration: Any) -> list[Diagnostic]:
    """Check every declared parameter against the configuration it will write into."""
    from hydromodpy.calibration.parameter_resolution import (
        RECHARGE_FACTOR_PATH,
        RECHARGE_VALUES_PATH,
        unresolved_parameter_names,
    )
    from hydromodpy.calibration.targets import calibration_targets, targets_by_path
    from hydromodpy.model.forcing.soil_config import soil_reservoir_of

    findings: list[Diagnostic] = []
    reachable = targets_by_path(calibration_targets(cfg))
    refused_names = unresolved_parameter_names(calibration, cfg)
    recharge = getattr(getattr(getattr(cfg, "flow", None), "sinks_sources", None), "recharge", None)
    loaded = getattr(getattr(cfg, "data", None), "types", None) or ()
    has_a_rate = "recharge" in loaded or (recharge is not None and recharge.peak_rate_mm_day() > 0)
    targets = {decl.resolve_target() for decl in (calibration.parameters or {}).values()}
    for name, decl in (calibration.parameters or {}).items():
        where = f"[calibration.parameters.{name}]"
        bounds = list(getattr(decl, "bounds", ()) or ())
        if len(bounds) == 2 and bounds[0] >= bounds[1]:
            findings.append(
                _finding(
                    "error",
                    where,
                    f"bounds are {bounds[0]:g} .. {bounds[1]:g}; the lower one has to be "
                    "the smaller one.",
                )
            )
        target = decl.resolve_target()
        if not target:
            findings.append(
                _finding(
                    "error",
                    where,
                    # The finding already names the section in its path.
                    refused_names.get(name, "").replace(f"{where} ", "", 1)
                    or "names nothing this project carries, and writes no 'path' either.",
                )
            )
            continue
        if target == RECHARGE_FACTOR_PATH and soil_reservoir_of(cfg.flow) is not None:
            findings.append(
                _finding(
                    "error",
                    where,
                    "moves the recharge factor, and the soil reservoir computes this recharge: "
                    "there is no rate to multiply. Calibrate ru instead, with its bounds in mm.",
                )
            )
            continue
        if target == RECHARGE_FACTOR_PATH and (not has_a_rate or RECHARGE_VALUES_PATH in targets):
            reason = (
                "the cost sees the product of the two, an exact ridge, so calibrate one"
                if has_a_rate
                else "there is no rate to multiply: write recharge values or load [data.recharge]"
            )
            findings.append(_finding("error", where, f"moves the recharge factor, and {reason}."))
            continue
        if target not in reachable:
            missing = _no_field_on_the_way(cfg, target)
            if missing is not None:
                near = ", ".join(sorted(reachable)[:6]) or "nothing"
                findings.append(
                    _finding(
                        "error",
                        where,
                        f"path {target!r} is not a value this configuration carries: "
                        f"{missing}. `hmp config targets` lists the values a parameter "
                        f"reaches by name; it starts with {near}.",
                    )
                )
                continue
            # The documented way out: the trial writes the value as given.
            findings.append(
                _finding(
                    "warning",
                    where,
                    f"path {target!r} is not in the catalogue `hmp config targets` "
                    "lists, so its unit and its physical range are not known here. "
                    "The trial writes the sampled value there as given.",
                )
            )
        findings.extend(_check_bounds_against_physics(where, name, decl, bounds))
    return findings


def _no_field_on_the_way(config: Any, path: str) -> str | None:
    """Say which segment of ``path`` names nothing in ``config``, or ``None``.

    Walked the way a trial writes a parameter
    (:func:`~hydromodpy.calibration.optim.parameters.set_by_path`): every
    segment has to exist, except a last one under a mapping, which the write
    adds as a key.
    """
    parts = str(path).split(".")
    target: Any = config
    for depth, part in enumerate(parts):
        reached = ".".join(parts[:depth]) or "the configuration root"
        if isinstance(target, Mapping):
            if part in target:
                target = target[part]
                continue
            if depth == len(parts) - 1:
                return None
            known = ", ".join(sorted(str(key) for key in target)[:12]) or "nothing"
            return f"no {part!r} under {reached}, which holds {known}"
        if isinstance(target, BaseModel):
            # A model also holds named tables, as solver.modflow6.
            try:
                target = child_of(target, part)
            except AttributeError as exc:
                return f"no {part!r} under {reached} ({exc})"
            continue
        if not hasattr(target, part):
            return f"no {part!r} under {reached}"
        target = getattr(target, part)
    return None


def _check_bounds_against_physics(
    where: str, name: str, decl: Any, bounds: list[float]
) -> list[Diagnostic]:
    from hydromodpy.calibration.optim.parameters import assert_bounds_are_physical

    if len(bounds) != 2:
        return []
    # The bounds of a scale are factors: the product is faced when written.
    try:
        if getattr(decl, "mode", "replace") != "scale":
            assert_bounds_are_physical(name, float(bounds[0]), float(bounds[1]), decl.units)
    except ValueError as exc:
        return [_finding("error", where, str(exc))]
    if str(getattr(decl, "search_space", "identity")).lower() == "log" and bounds[0] <= 0.0:
        return [
            _finding(
                "error",
                where,
                f'search_space = "log" needs a lower bound above zero, got {bounds[0]:g}.',
            )
        ]
    return []


def _check_outputs(calibration: Any, source: Path, project_config: Any) -> list[Diagnostic]:
    """Check what an output needs that only the filesystem or the project can answer.

    The geometry is looked for exactly where the run looks for it, so a file
    preflight calls missing is one the run would call missing too. A declared
    ``map.complete`` or ``map.permanent`` is faced with the
    project the same way a parameter's name is faced with the catalog:
    refused here beside whatever else is wrong, rather than at the first trial.
    """
    from hydromodpy.calibration.observations.network_source import (
        unresolved_minimal_observed_networks,
        unresolved_observed_networks,
    )
    from hydromodpy.calibration.runners.document import resolve_stream_geometry_paths

    resolve_stream_geometry_paths(calibration, source)
    refused = (
        unresolved_observed_networks(calibration, project_config),
        unresolved_minimal_observed_networks(calibration, project_config),
    )
    findings: list[Diagnostic] = []
    for name in calibration.outputs or {}:
        where = f"[calibration.outputs.{name}]"
        findings.extend(
            # The finding already names the section in its path.
            _finding("error", where, reasons[name].replace(f"{where} ", "", 1))
            for reasons in refused
            if name in reasons
        )
    findings.extend(
        _finding(
            "error",
            f"[calibration.outputs.{name}]",
            f"map.{role} {str(path)!r} is not there, and none of the places the run looks "
            "holds it. The criterion resolves no map of its own, so the run would stop at "
            "the first trial.",
        )
        for name, role, path in calibration.map_files()
        if not path.exists()
    )
    return findings


def _check_blocks(calibration: Any) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    declared = set(calibration.outputs or {})
    seen: set[str] = set()
    for block in calibration.objective_blocks or []:
        where = f"[[calibration.objective_blocks]] {block.name!r}"
        if block.name in seen:
            findings.append(_finding("error", where, "two blocks share this name."))
        seen.add(block.name)
        findings.extend(
            _missing(where, "uses_outputs", block.uses_outputs, declared, "[calibration.outputs]")
        )
    return findings


def _check_phases(calibration: Any) -> list[Diagnostic]:
    phases = calibration.phases
    if not phases:
        return []
    findings: list[Diagnostic] = []
    parameters = set(calibration.parameters or {})
    outputs = set(calibration.outputs or {})
    blocks = {block.name for block in calibration.objective_blocks or []}

    for phase in phases:
        where = f"[[calibration.phases]] {phase.name!r}"
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
        findings.extend(
            _finding("error", f"{where} bounds", problem)
            for problem in calibration.phase_bounds_problems(phase)
        )
    return findings


def _check_the_regimes(calibration: Any, config: Any, source: Path) -> list[Diagnostic]:
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

    try:
        document = _raw_document(config, source)
    except (OSError, ValueError) as exc:
        return [
            _finding(
                "error",
                "[simulation.time]",
                f"the phases that give a regime read their window from {source.name}, "
                f"which cannot be read: {exc}",
            )
        ]
    findings: list[Diagnostic] = []
    for phase in phases:
        try:
            regime_overrides(phase, document)
        except ValueError as exc:
            findings.append(
                _finding(
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

    return criterion_for(metric).requirements().signed


def _signed_residual_metrics() -> list[str]:
    """Return every registered criterion a root search may be pointed at."""
    from hydromodpy.calibration.criteria import available_criteria

    return sorted(name for name in available_criteria() if _publishes_a_signed_residual(name))


def _check_engines(calibration: Any) -> list[Diagnostic]:
    """Face each search with what its engine says it can be handed.

    An engine refuses an impossible pairing in its constructor, which is right
    but late: a staged calibration builds phase two's optimizer when phase two
    starts, after phase one has spent its whole budget. Its method_options are
    faced with the method here too. Loading a file already refuses them, but a
    configuration assembled in Python without validation reaches this check
    without that refusal, and the finding names the phase either way.
    """
    from hydromodpy.calibration.optim.method_config import method_options_problem
    from hydromodpy.calibration.optim.optimizer import (
        announced_optimizers,
        engine_traits,
        optimizers,
    )
    from hydromodpy.calibration.optim.parameters import refuse_normal_sampling

    known = set(optimizers.names())
    options_of = {entry[0]: entry[3] for entry in _declared_precisions(calibration)}
    findings: list[Diagnostic] = []
    for where, method, names, metrics, parallel in _searches(calibration):
        if method not in known:
            findings.append(
                _finding(
                    "error",
                    where,
                    f"method {method!r} is not registered. "
                    f"Available: {', '.join(announced_optimizers())}.",
                )
            )
            continue
        problem = method_options_problem(method, options_of.get(where))
        if problem is not None:
            findings.append(
                _finding(
                    "error",
                    where,
                    f"method_options: {problem} The run would stop when this search "
                    "starts, after the searches before it have spent their budget.",
                )
            )
        traits = engine_traits(method)
        if traits.max_parameters is not None and len(names) > traits.max_parameters:
            findings.append(
                _finding(
                    "error",
                    where,
                    f"{method!r} moves {traits.max_parameters} parameter(s) at a time and "
                    f"this search declares {len(names)}: {', '.join(names)}.",
                )
            )
        if traits.required_search_space is not None:
            wrong = [
                name
                for name, decl in (calibration.parameters or {}).items()
                if name in names
                and str(getattr(decl, "search_space", "identity")) != traits.required_search_space
            ]
            if wrong:
                findings.append(
                    _finding(
                        "error",
                        where,
                        f"{method!r} walks a {traits.required_search_space!r} variable and "
                        f"its stopping rule is a width in it, but {', '.join(wrong)} "
                        f"declare(s) another search space.",
                    )
                )
        for name in names:
            try:
                if not traits.draws_a_normal:
                    refuse_normal_sampling(method, name, calibration.parameters[name].sampling)
            except ValueError as refusal:
                findings.append(_finding("error", where, str(refusal)))
        if traits.needs_signed_residual and not all(
            _publishes_a_signed_residual(metric) for metric in metrics
        ):
            named = ", ".join(sorted(metrics)) or "nothing"
            findings.append(
                _finding(
                    "error",
                    where,
                    f"{method!r} closes a bracket on a signed residual and reports the "
                    f"trial with the smallest cost as its best, which only agree when "
                    f"the cost IS that residual. This search is scored on {named}. "
                    f"Score it on {', '.join(_signed_residual_metrics())}, or "
                    "search it with a minimiser.",
                )
            )
        if traits.reads_cost_as is not None and metrics and metrics != {traits.reads_cost_as}:
            named = ", ".join(sorted(metrics))
            findings.append(
                _finding(
                    "warning",
                    where,
                    f"{method!r} reads its cost as {traits.reads_cost_as} and builds its "
                    f"likelihood on it, and this search is scored on {named}. The chain "
                    f"would sample that number as if it were {traits.reads_cost_as}. "
                    f"Score it on {traits.reads_cost_as}.",
                )
            )
        # J measures a balance: with anything else to move, |J| falls by trading excess
        # for missing stream, the two networks no closer.
        if any(_publishes_a_signed_residual(metric) for metric in metrics) and (
            len(names) > 1 or len(metrics) > 1
        ):
            findings.append(
                _finding(
                    "warning",
                    where,
                    "distance_gap enters a cost beside another parameter or metric, and can "
                    "fall by trading excess for missing stream. Score distance_mean.",
                )
            )
        reach = None
        if not traits.supports_parallel:
            reach = 1
        elif traits.reach is not None:
            reach = traits.reach(options_of.get(where) or {}, len(names))
        if parallel > 1 and reach is not None and parallel > reach:
            findings.append(
                _finding(
                    "warning",
                    where,
                    f"{method!r} can use {reach} solves at once, so parallel = {parallel} "
                    f"buys nothing beyond {reach}. Each worker takes about 0.5 GiB and 3.3 s "
                    "to start.",
                )
            )
    return findings


_OBSERVABLE_BY_SUPPORT: Mapping[str, str] = {
    "lake": "stage",
    "network": "release_flux",
}
"""What an output's support actually asks the backend for."""


def _check_the_precision_can_be_honoured(calibration: Any) -> list[Diagnostic]:
    """Refuse a precision the engine of that search cannot stop on.

    The translation happens when the optimizer is built, which for phase two is
    after phase one has spent its budget. A precision that was never going to be
    readable has to be refused before the first solve, not after the last.
    """
    from hydromodpy.calibration.optim.optimizer import engine_traits, optimizers

    known = set(optimizers.names())
    findings: list[Diagnostic] = []
    linearized = _linearized_scored_outputs(calibration)
    if linearized:
        # Same reason as the precision below: the width is built after the
        # last solve, so `hmp check` is where a document that can
        # never carry one is named, before any of it is paid for. A phased
        # document gets one width per phase (D234), built from what THAT
        # PHASE scores, so each phase is checked on its own selection rather
        # than on the whole file's.
        for where, outputs, single_metric in linearized:
            observing = [
                name
                for name, decl in outputs.items()
                if getattr(decl, "observes", None) is not None
            ]
            if not observing:
                if single_metric:
                    detail = (
                        "scores variable/objective, whose implicit outputs are built from the "
                        "loaded records when the search starts: no declared output gives a "
                        "linearized width a residual vector to be taken from. "
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
                findings.append(_finding("error", where, detail))
                continue
    for where, method, precision, kwargs, restarts in _declared_precisions(calibration):
        if restarts is not None and method in known:
            from hydromodpy.calibration.runners.restarts import assert_restarts_can_explore

            try:
                assert_restarts_can_explore(method, int(restarts))
            except ValueError as exc:
                findings.append(_finding("error", where, str(exc)))
        if precision is None or method not in known:
            continue
        traits = engine_traits(method)
        if traits.precision_option is None:
            findings.append(
                _finding(
                    "error",
                    where,
                    f"precision asks {method!r} to stop at a precision on the parameter, "
                    "and that engine stops on its evaluation budget instead. Set max_trials, "
                    "or run this search on an engine that converges on the parameter.",
                )
            )
            continue
        if traits.precision_option in (kwargs or {}):
            findings.append(
                _finding(
                    "error",
                    where,
                    f"precision and method_options.{traits.precision_option} both set "
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
                calibration.precision,
                dict(calibration.method_options or {}),
                calibration.uncertainty.restarts,
            )
        ]
    return [
        (
            f"[[calibration.phases]] {phase.name!r}",
            calibration.method_for(phase)[0],
            phase.precision,
            calibration.method_options_for(phase),
            calibration.uncertainty_for(phase).restarts,
        )
        for phase in calibration.phases
    ]


def _check_the_budgets(calibration: Any) -> list[Diagnostic]:
    """Refuse a budget below the nominal count of its engine, announce one below its worst.

    Three engines count their evaluations before the first solve. The root
    search counts them from its bounds, sweep, precision and bracket expansions
    (:func:`~hydromodpy.calibration.optim.adapters.bisection_adapter.
    root_search_budget`), so a budget that cannot close the bracket even with
    the root inside the bounds is a configuration error, found here rather
    than after the budget is spent. The grid and the Latin hypercube count
    their design, and a budget below it would cut the sweep short. ``"auto"``
    is always enough. Every other engine cannot count, and nothing is checked.
    """
    from hydromodpy.calibration.optim.stopping import AUTO_BUDGET, short_budget

    findings: list[Diagnostic] = []
    searches = zip(_budgets(calibration), _search_candidates(calibration), strict=True)
    for (where, method, names, max_trials, precision, kwargs), (phase, _, _) in searches:
        if max_trials == AUTO_BUDGET:
            continue
        try:
            counted = _counted_budget(calibration, phase, method, names, precision, kwargs)
        except (TypeError, ValueError):
            # Bounds or options the other checks already refuse.
            continue
        if counted is None:
            continue
        verdict = short_budget(counted, int(max_trials))
        if verdict is None:
            continue
        severity, detail = verdict
        if getattr(calibration, "protocol", None) is not None:
            detail += (
                " A protocol stage takes its max_trials from [calibration.protocol] "
                "steady_max_trials or transient_max_trials."
            )
        findings.append(_finding(severity, where, detail))
    return findings


def _counted_budget(
    calibration: Any,
    phase: Any | None,
    method: str,
    names: list[str],
    precision: float | None,
    kwargs: dict,
) -> Any | None:
    """Return the evaluations a search counts before its first solve, or None.

    A root search scored on a network output with two bounds closes two roots,
    and is counted so. It is counted for the points the engine asks at once,
    ``max(batch_size, parallel)``, since each round of cuts places that many.
    """
    from hydromodpy.calibration.optim.adapters.bisection_adapter import (
        BisectionAdapter,
        root_search_budget,
    )
    from hydromodpy.calibration.optim.adapters.grid_adapter import GridAdapter, grid_budget
    from hydromodpy.calibration.optim.adapters.lhs_adapter import LhsAdapter, design_budget

    if method == GridAdapter.name:
        return grid_budget(len(names), kwargs.get("points_per_dim"))
    if method == LhsAdapter.name:
        n_samples = kwargs.get("n_samples")
        return design_budget(int(n_samples)) if n_samples is not None else None
    if method != BisectionAdapter.name or len(names) != 1:
        return None
    decl = (calibration.parameters or {}).get(names[0])
    bounds = list(getattr(decl, "bounds", None) or ())
    if len(bounds) != 2:
        return None
    rel_tol = precision if precision is not None else kwargs.get("rel_tol")
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
    options["batch"] = max(calibration.batch_size_for(phase), calibration.parallel_for(phase))
    return root_search_budget(float(bounds[0]), float(bounds[1]), **options)


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
                calibration.max_trials,
                calibration.precision,
                dict(calibration.method_options or {}),
            )
        ]
    return [
        (
            f"[[calibration.phases]] {phase.name!r}",
            calibration.method_for(phase)[0],
            list(phase.parameters),
            calibration.max_trials_for(phase),
            calibration.precision_for(phase),
            calibration.method_options_for(phase),
        )
        for phase in calibration.phases
    ]


def _check_the_interval_widths(calibration: Any) -> list[Diagnostic]:
    """Refuse a share of the best cost on a search scored only by network distances.

    A share is a fraction of the best cost. A network distance is in meters and
    solved at zero, so a fraction of it says nothing about how far a stream may
    move. The width is read after the last solve, so this is where it is named,
    before any of it is paid for.
    """
    searches = [(None, "[calibration.uncertainty]")] if not calibration.phases else []
    searches += [
        (phase, f"[[calibration.phases]] {phase.name!r}") for phase in calibration.phases or ()
    ]
    findings: list[Diagnostic] = []
    for phase, where in searches:
        width = calibration.interval_width_for(phase)
        if width.kind != "relative" or not width.on_distances:
            continue
        written = "in this phase" if width.source == "phase" else "in [calibration.uncertainty]"
        findings.append(
            _finding(
                "error",
                where,
                f"cost_margin, written {written}, is a share of the best cost, and this "
                "search is scored only on network distances, in metres, solved at zero: a "
                "fraction of a distance has no meaning. Write a length such as '25 m', or "
                "leave it unwritten for one mesh cell.",
            )
        )
    return findings


def _check_the_backend_can_serve_the_outputs(
    calibration: Any, searched: Mapping[str | None, Any]
) -> list[Diagnostic]:
    """Face each output with what the chosen backend says it can serve.

    A backend answers on the resolved configuration in three states, so this
    separates two refusals a binary answer confuses: one declaration away, with
    the declaration named, and out of reach on this backend whatever the file
    says. Both used to arrive at the first extraction, hours into a search.
    A phase asks on the model its overrides write, for the outputs it scores.
    """
    findings: list[Diagnostic] = []
    for phase, _where, _names in _search_candidates(calibration):
        config = _config_of(searched, phase)
        adapter = _flow_adapter_for(config) if config is not None else None
        declared = getattr(adapter, "declared_observables", None)
        if declared is None:
            continue
        active = frozenset(config.flow.active_bc or ())
        support_by_name = {item.name: item for item in declared(active)}
        outputs = (
            calibration.outputs or {}
            if phase is None
            else _outputs_scored_by_search(calibration, phase)
        )
        for name, decl in outputs.items():
            observable = _OBSERVABLE_BY_SUPPORT.get(str(getattr(decl, "support", "")))
            if observable is None:
                continue
            support = support_by_name.get(observable)
            if support is None or support.is_servable_now:
                continue
            finding = _finding(
                "error",
                f"[calibration.outputs.{name}]",
                f"this output reads {observable!r}, which the chosen backend does not "
                f"serve as configured: {support.reason}",
            )
            if finding not in findings:
                findings.append(finding)
    return findings


def _flow_adapter_for(config: Any) -> Any | None:
    """Return the flow adapter this configuration selects, or ``None``."""
    from hydromodpy.core.exceptions import SolverInputError
    from hydromodpy.solver.base.registry import solvers

    backend = getattr(getattr(config, "solver", None), "backend_name", None)
    backend = getattr(backend, "value", backend)
    if not backend:
        return None
    try:
        return solvers.create("flow", str(backend))
    except (SolverInputError, ValueError):
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
            calibration.parallel_for(phase),
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
) -> list[tuple[str, Mapping[str, Any], bool]]:
    """Return, per search whose width is linearized, its label, the outputs it scores, and more.

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
                False,
            )
        ]
    result: list[tuple[str, Mapping[str, Any], bool]] = []
    for phase in calibration.phases:
        if calibration.uncertainty_for(phase).method != "linearized":
            continue
        where = f"[[calibration.phases]] {phase.name!r}"
        if phase.is_single_metric:
            result.append((where, {}, True))
            continue
        outputs = dict(calibration.outputs or {})
        blocks = _phase_named_blocks(calibration, list(phase.objective_blocks))
        if phase.outputs:
            outputs = {name: outputs[name] for name in phase.outputs if name in outputs}
        elif phase.objective_blocks:
            read = {name for block in blocks for name in block.uses_outputs}
            outputs = {name: value for name, value in outputs.items() if name in read}
        result.append((where, outputs, False))
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
    for phase, where, names in _search_candidates(calibration):
        if len(names) <= 1:
            continue
        outputs = _outputs_scored_by_search(calibration, phase)
        if not outputs:
            continue
        if not all(output.support == "network" for output in outputs.values()):
            continue
        moved = _resolved_paths(calibration, names)
        exact_ridge = (
            RECHARGE_FACTOR_PATH in moved
            and moves_a_hydraulic_conductivity(moved)
            and _search_regime(_config_of(searched, phase), phase) == "steady"
        )
        findings.append(
            _finding(
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


def _check_a_minimiser_on_two_bounds(calibration: Any) -> list[Diagnostic]:
    """Refuse a minimiser on one parameter and two weighted bounds.

    A root search combines two roots and a minimiser returns the lowest weighted
    cost, so the value would depend on the method. Several parameters leave no root
    search to differ from: K and the porosity together on the two maps stay open
    for the twin to measure.
    """
    from hydromodpy.calibration.optim.optimizer import engine_traits

    findings: list[Diagnostic] = []
    for (phase, where, names), search in zip(
        _search_candidates(calibration), _searches(calibration), strict=True
    ):
        method = calibration.method_for(phase)[0]
        if (
            len(names) == 1
            and not engine_traits(method).needs_signed_residual
            and _roots_of_the_search(calibration, phase) == 2
            and any(_publishes_a_signed_residual(metric) for metric in search[3])
        ):
            findings.append(
                _finding(
                    "error",
                    where,
                    f"{method!r} would return the lowest weighted cost over two bounds, where "
                    "a root search returns the mean of two roots, so the value would depend "
                    "on the method. Search with bisection on distance_gap, or weigh one bound "
                    "zero in map.calibrate_on.",
                )
            )
    return findings


def _check_the_network_search_can_trust_its_release_packages(
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
    for phase, where, names in _search_candidates(calibration):
        config = _config_of(searched, phase)
        if config is None:
            continue
        flow = getattr(config, "flow", None)
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
            findings.append(_finding("error", where, message))
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
        for name, output in sorted(_outputs_scored_by_search(calibration, phase).items())
        if output.support == "network" and output.model.extent is not None
    ]


def _check_an_extent_is_scored_on_a_transient_run(
    calibration: Any, searched: Mapping[str | None, Any]
) -> list[Diagnostic]:
    """Refuse an extent table on a network output a steady search scores.

    The two-bound mode reads the timesteps of a transient run. A steady run
    holds one period, and the criterion refuses it at the first trial, after
    the phases before it have spent their budget.
    """
    findings: list[Diagnostic] = []
    for phase, where, _ in _search_candidates(calibration):
        config = _config_of(searched, phase)
        if config is None or _search_regime(config, phase) != "steady":
            continue
        for name, _extent in _extents_scored_by(calibration, phase):
            ran_by = "[flow] flow_regime" if phase is None else where
            findings.append(
                _finding(
                    "error",
                    f"[calibration.outputs.{name}]",
                    f"declares an extent table and is scored by a steady search "
                    f"({ran_by}). The two-bound mode reads the timesteps of a transient "
                    "run, and a steady run holds one period. Score this output in one "
                    "state, without the extent table, or run the search transient.",
                )
            )
    return findings


def _check_the_extent_durations_fit_the_timestep(
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
    for phase, _where, _ in _search_candidates(calibration):
        config = _config_of(searched, phase)
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
                    _finding(
                        "error",
                        f"[calibration.outputs.{name}.model.extent]",
                        f"flowing_at_least = {extent.flowing_at_least!r} and "
                        f"dry_at_most = {extent.dry_at_most!r} cannot be "
                        f"read on a timestep of {step_days:g} days: " + "; ".join(problems) + ".",
                    )
                )
    return findings


def _check_a_network_estimator_names_its_network_output(
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
            _finding(
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


def _check_the_scoring_windows_hold_what_they_score(
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
    for phase, where, _ in _search_candidates(calibration):
        if phase is not None and phase.is_single_metric:
            continue
        blocks = (
            _phase_named_blocks(calibration, list(phase.objective_blocks))
            if phase is not None
            else list(calibration.objective_blocks or [])
        )
        if not blocks:
            continue
        outputs = _outputs_scored_by_search(calibration, phase)
        config = _config_of(searched, phase)
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
                    _finding(
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
                    _finding(
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
            findings.append(_finding("error", where, str(exc)))
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
                document.append(_raw_document(project_config, source))
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


def _missing(
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
        _finding(
            "error",
            where,
            f"{key} names {', '.join(unknown)}, which {section} does not declare. "
            f"Declared: {available}.",
        )
    ]
