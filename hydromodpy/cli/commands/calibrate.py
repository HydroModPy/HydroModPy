"""``hmp calibrate`` - run a calibration workflow from a TOML file.

Thin wrapper around :func:`hydromodpy.calibrate`. The TOML must declare
``[workflow] mode = "calibration"`` (resolved by the workflow dispatcher).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hydromodpy.cli._conventions import profile_parser, verbosity_parser
from hydromodpy.cli.helpers import (
    EXIT_CALIBRATION,
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    EXIT_USAGE,
    apply_verbosity,
    profile_arg_from_toml,
    profile_run,
    resolve_profile_output,
)
from hydromodpy.core.exceptions import CalibrationError, ConfigError

NAME: str = "calibrate"
HELP: str = "Run a calibration workflow from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[profile_parser(), verbosity_parser()])
    parser.add_argument("config", type=Path, help="Path to a calibration TOML file")
    parser.add_argument(
        "--phase",
        default=None,
        help="Run only this phase of a staged calibration. Its dependency must have "
        "run, otherwise the phase would calibrate against un-frozen parameters.",
    )
    parser.add_argument(
        "--list-phases",
        action="store_true",
        help="List the declared phases and exit without running anything.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check everything the search needs and exit without solving. Reports every "
        "problem at once rather than the first.",
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        help="Print the [calibration] section a protocol writes, as TOML, and exit "
        "without running anything. A file naming no protocol prints its own section. "
        "Refused together with --phase, --list-phases or --check.",
    )
    parser.set_defaults(_handler=run)
    return parser


def _shows(level: str) -> bool:
    """Say whether the console verbosity in force prints a line of ``level``."""
    from hydromodpy.core.logging import VERBOSITY_LEVELS, current_verbosity

    return VERBOSITY_LEVELS.index(current_verbosity()) >= VERBOSITY_LEVELS.index(level)


def _say(text: str, *, level: str = "normal") -> None:
    """Print one line of ``--check`` to stderr, when the verbosity asks for it.

    ``normal`` lines are what a reader acts on; ``verbose`` ones are the full
    record behind them. ``-q`` keeps the findings only, which are printed
    whatever the level.
    """
    if _shows(level):
        print(text, file=sys.stderr)


def _check_only(target: Path) -> None:
    """Report everything wrong with the calibration in ``target`` and exit.

    Nothing solves, so this costs a second whatever the model. Every check runs,
    so a file with three mistakes takes one pass to fix rather than three
    overnight runs. A warning raised while the file loads, a renamed key for
    instance, is one more finding: it is what the file has to change.
    """
    import warnings

    from hydromodpy.calibration.preflight import PreflightFinding, preflight_calibration
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    with warnings.catch_warnings(record=True) as caught:
        # Only the categories a file's author acts on are forced through; the
        # others keep the filters they had, so nothing ignored today is printed.
        warnings.simplefilter("always", ConfigKeyRenamedWarning)
        warnings.simplefilter("always", UserWarning)
        try:
            cfg = HydroModPyConfig.from_toml(target)
        except Exception as exc:
            cfg = None
            # A file that will not load has nothing else to check: every other
            # finding would be about a configuration that does not exist.
            refused = PreflightFinding("error", target.name, f"the file does not load: {exc}")
    findings = _findings_from_load_warnings(caught, target.name)
    if cfg is None:
        findings.append(refused)
    else:
        _announce_the_protocol(cfg)
        _announce_the_comparisons(cfg, target)
        findings.extend(preflight_calibration(cfg, source=target))
    if not findings:
        _say(f"{target.name}: ready to run.")
        return
    for finding in findings:
        print(finding.line(), file=sys.stderr)
    errors = sum(1 for finding in findings if finding.severity == "error")
    _say(f"{target.name}: {errors} error(s), {len(findings) - errors} warning(s).")
    if errors:
        sys.exit(EXIT_CONFIG)


def _findings_from_load_warnings(caught: list[Any], where: str) -> list[Any]:
    """Turn the warnings this package raised while loading into findings.

    A renamed key warns from a validator, and the console routing would print it
    as a raw warning line, or not at all. Here it is a finding among the others,
    counted in the verdict. A warning a dependency raised is handed back to the
    usual routing, untouched.
    """
    import warnings

    import hydromodpy
    from hydromodpy.calibration.preflight import PreflightFinding
    from hydromodpy.core.config_kit.base import ConfigKeyRenamedWarning

    package = Path(hydromodpy.__file__).resolve().parent
    findings: list[Any] = []
    seen: set[str] = set()
    for item in caught:
        ours = issubclass(item.category, ConfigKeyRenamedWarning) or Path(
            item.filename
        ).resolve().is_relative_to(package)
        if not ours:
            warnings.showwarning(item.message, item.category, item.filename, item.lineno)
            continue
        text = str(item.message)
        if text in seen:
            continue
        seen.add(text)
        findings.append(PreflightFinding("warning", where, text))
    return findings


def _announce_the_protocol(cfg) -> None:
    """Say which published method this file runs, and where this run leaves it.

    A calibrated value that came out of a named method carries the method with
    it. Printing it here is where the reader is already looking, before an
    overnight run rather than after.

    At the normal verbosity, only what moves this run off the publication: a
    departure the run makes, and an option set away from what the recipe runs.
    A value equal to the paper's, or written the way the recipe runs it
    anyway, is not a departure. ``-v`` adds the stages, the references, and
    every reading of the paper this implementation makes.
    """
    declared = getattr(getattr(cfg, "calibration", None), "protocol", None)
    if declared is None:
        return
    from hydromodpy.calibration.protocols import (
        options_the_recipe_already_runs,
        protocol_record,
        why_the_spin_up_year_is_scored,
    )

    record = protocol_record(declared.name, declared)
    time = getattr(getattr(cfg, "simulation", None), "time", None)
    _say(f"protocol: {record['name']}@{record['version']} - {record['title']}")
    for index, stage in enumerate(record["stages"], start=1):
        _say(f"  stage {index}: {stage}", level="verbose")
    # The protocol drops its default window without a word on a short run, so
    # this is where the reader learns the spin-up year is scored.
    whole_run = why_the_spin_up_year_is_scored(cfg.calibration, time)
    if whole_run is not None:
        _say(f"  stage 2 scores the whole run, spin-up year included: {whole_run}")
    for reference in record["references"]:
        _say(f"  cite: {reference}", level="verbose")
    # Where this run departs from the publication it cites. A reader comparing a
    # result to the literature needs this before the run, not after.
    keys = [item["key"] for item in record["deviations"]]
    in_force = _values_in_force(cfg, keys)
    written = _values_this_file_set(cfg, keys)
    for deviation in record["deviations"]:
        key = deviation["key"]
        told = f"{deviation['here']} (paper: {deviation['paper']})"
        suffix = f" - this file sets {_rendered(written[key])}" if key in written else ""
        if key not in in_force or (deviation["paper_value"] is None and key not in written):
            _say(f"  reads the paper on {key}: {told}", level="verbose")
        elif _departs(deviation, in_force[key], key in written):
            _say(f"  differs from the paper on {key}: {told}{suffix}")
        else:
            _say(f"  as the paper on {key}: {told}{suffix}", level="verbose")
    # An option moved off the recipe keeps the method but changes what the number
    # rests on, and only the file knows it moved.
    same = options_the_recipe_already_runs(declared, cfg.calibration, time)
    for option in record.get("options_away_from_the_recipe", ()):
        line = f"{option['key']} = {_rendered(option['here'])}"
        if option["key"] in same:
            _say(f"  option written as the recipe runs it: {line}", level="verbose")
        else:
            _say(f"  option away from the recipe: {line} (recipe: {_rendered(option['recipe'])})")
    backend = getattr(getattr(cfg, "solver", None), "backend_name", None)
    backend = str(getattr(backend, "value", backend) or "")
    verdict = record["support"].get(backend)
    if verdict is not None and verdict != "tested":
        _say(
            f"  on {backend}: {verdict.replace('_', ' ')} - no case in this repository "
            "runs the protocol on that backend."
        )


def _departs(deviation: Mapping[str, Any], value: object, written: bool) -> bool:
    """Say whether the value in force leaves the publication on this deviation.

    A deviation whose paper value is known departs when the value in force is
    another. One whose paper has no value for the key, the paper being silent
    on it, departs only when the file sets it.
    """
    paper = deviation.get("paper_value")
    if paper is None:
        return written and value is not None
    try:
        return bool(value != paper)
    except (TypeError, ValueError):
        # A length compared with the word 'auto': two different things.
        return True


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


def _announce_the_comparisons(cfg, source: Path) -> None:
    """Print what each phase, or the whole section, compares with what.

    One block per line: its criterion, its share, the simulated quantity and
    what it is compared against. A plain calibration with no
    ``[[calibration.phases]]`` still runs one search, so it gets one table
    under ``[calibration]``; ``--list-phases`` has no phase line to print it
    under, but ``--check`` names its one search here.

    ``source`` anchors a relative ``stream_geometry_path`` the same way the
    run would, so a network output's source reads the same path here as in
    ``--list-phases``.
    """
    from hydromodpy.calibration.runners.cli_runner import resolve_stream_geometry_paths
    from hydromodpy.calibration.runners.staged_runner import objective_comparison_table

    calibration = getattr(cfg, "calibration", None)
    if calibration is None:
        return
    resolve_stream_geometry_paths(calibration, source)
    for phase in calibration.phases or [None]:
        label = phase.name if phase is not None else "[calibration]"
        table = objective_comparison_table(calibration, phase)
        if not table:
            continue
        _say(f"compares ({label}):")
        for row in table:
            _say(f"  {_comparison_line(row)}")


def _comparison_line(row: dict[str, Any]) -> str:
    """Return one line of what a block, or the single-metric route, compares.

    ``row`` is one entry of
    :func:`hydromodpy.calibration.runners.staged_runner.objective_comparison_table`.
    Its ``source`` keeps the absolute path a network output resolved to; here
    only, formatting shortens it when it sits under the working directory, so
    the line does not carry one checkout's full path.
    """
    label = row["block"] or "single metric"
    source = _shortened_if_under_cwd(row["source"])
    return (
        f"{label}\t{row['metric']}\tshare {_percent(row['share'])}\t{row['quantity']}\tvs {source}"
    )


def _shortened_if_under_cwd(text: str) -> str:
    """Return ``text`` relative to the working directory, when it is an absolute path under it.

    ``text`` is usually not a path at all (a station name, a data section, a
    count of hard-coded values), and those are left untouched: only an
    absolute path both starts with a root and resolves under the directory
    the command was run from.
    """
    path = Path(text)
    if not path.is_absolute():
        return text
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return text


def _places_the_deviations_are_set(cfg) -> list[Any]:
    """Return where a file sets the keys a protocol departs on.

    The network outputs, then ``[geographic]`` for ``dem_correc_type``. A gauge
    declares its own ``diagonal_neighbors``, false by default, and is not the
    criterion the deviations describe, so it is not read.
    """
    calibration = getattr(cfg, "calibration", None)
    outputs = getattr(calibration, "outputs", None) or {}
    places = [
        output for output in outputs.values() if getattr(output, "support", None) == "network"
    ]
    geographic = getattr(cfg, "geographic", None)
    if geographic is not None:
        places.append(geographic)
    return places


def _declares(place: Any, key: str) -> bool:
    """Say whether a model has a field ``key``, the way its class declares it."""
    return key in getattr(type(place), "model_fields", {})


def _values_in_force(cfg, keys: list[str]) -> dict[str, object]:
    """Return, for the keys a protocol departs on, the value the run will use.

    Written or default alike. A key no model of this file carries is left out:
    the deviation it names is a reading of the paper, not an option.
    """
    found: dict[str, object] = {}
    for key in keys:
        for place in _places_the_deviations_are_set(cfg):
            if _declares(place, key):
                found[key] = getattr(place, key)
                break
    return found


def _values_this_file_set(cfg, keys: list[str]) -> dict[str, object]:
    """Return, for the keys a protocol departs on, what this file actually wrote.

    Read from ``model_fields_set``: a value left unset is the default, which the
    deviation table already states, and saying "this file sets" it would be
    false.
    """
    found: dict[str, object] = {}
    for key in keys:
        for place in _places_the_deviations_are_set(cfg):
            if key in getattr(place, "model_fields_set", set()):
                found[key] = getattr(place, key)
                break
    return found


def _expand_only(target: Path) -> None:
    """Print the ``[calibration]`` section a protocol unfolds into, as TOML, and exit.

    Formatting only: :func:`hydromodpy.calibrate` does the unfolding and
    returns the whole section, pasteable in place of the protocol. A file
    naming no protocol gets a header saying so instead of a protocol line, and
    its own section is printed unchanged. The ``protocol__delete`` hint is
    printed only when the protocol comes from the ``base_config``: that is the
    one case where a file pasting the section under the same base has an
    inherited protocol to drop.
    """
    import io

    import hydromodpy as hmp
    from hydromodpy.core.toml_io.writer import dump

    try:
        expanded = hmp.calibrate(target, expand=True)
    except ConfigError as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    protocol = expanded["protocol"]
    if protocol is None:
        print(
            f"# {target.name} declares no protocol: this is its [calibration] section as declared."
        )
    else:
        print(f"# Expanded from protocol {protocol['name']}, version {protocol['version']}")
        if protocol["citation"]:
            print(f"# ({protocol['citation']}).")
        print("# The whole [calibration] section: pasted in place of the protocol, it runs")
        print("# the same stages.")
        if protocol.get("inherited"):
            print("# The protocol comes from the base_config, so a file pasting this under")
            print("# the same base_config also writes, under [calibration]:")
            print("# protocol__delete = true")

    buffer = io.BytesIO()
    dump({"calibration": expanded["calibration"]}, buffer)
    print(buffer.getvalue().decode(), end="")


def _phase_line(index: int, phase: dict[str, Any]) -> str:
    """Return the ``--list-phases`` line of one phase.

    A method the phase does not name was chosen from its criteria, and the
    reason follows it. After the description, the width the phase reads its
    interval with and where it comes from. A column is added only for a phase
    that moves again what an earlier phase passed on: which parameters, from
    which phase, and whether the search starts there.
    """
    method = phase["method"]
    if phase.get("method_reason"):
        method = f"{method} ({phase['method_reason']})"
    line = f"{index}\t{phase['name']}\t{method}\t{phase['description']}"
    if phase.get("interval_width"):
        line = f"{line}\t{_width_text(phase['interval_width'])}"
    reopens = phase.get("reopens")
    if not reopens:
        return line
    moved = ", ".join(f"{item['parameter']}<-{item['from_phase']}" for item in reopens)
    start = (
        "starts there"
        if phase["starts_from_passed_values"]
        else f"{phase['method']} takes no start point and keeps its own"
    )
    return f"{line}\tre-opens {moved}, {start}"


_WRITTEN_IN = {"phase": "written in the phase", "section": "written in [calibration.uncertainty]"}


def _width_text(width: dict[str, Any]) -> str:
    """Return the width a phase reads its interval with, and where it comes from.

    The origin named is the tolerance's. The mode's is added when it comes from
    elsewhere, for instance a mode written and a tolerance left to the default.
    """
    source = width["source"]
    if source == "default":
        value = width["rule"]
        origin = (
            "default, measured on the mesh when the phase runs"
            if width["tolerance"] is None
            else "default"
        )
    else:
        tolerance = float(width["tolerance"])
        if width["mode"] == "relative":
            value = f"{tolerance * 100:g} % of the best cost"
        elif width["on_distances"]:
            value = f"{tolerance:g} m"
        else:
            value = f"{tolerance:g} in the unit of the cost"
        origin = _WRITTEN_IN[source]
    mode_source = width.get("mode_source", source)
    if mode_source != source:
        origin += f"; mode {width['mode']} {_WRITTEN_IN.get(mode_source, 'by default')}"
    return f"width {value} ({origin})"


def _shares_text(shares: dict[str, float]) -> str:
    """Return one block-per-token rendering of a share mapping, as percentages."""
    return ", ".join(f"{name} {_percent(value)}" for name, value in shares.items())


def _percent(share: float) -> str:
    """Return a share of the cost as a percentage a reader cannot misread.

    Whole per cents, except near the ends: a share below 1 % keeps one
    significant digit, so a block weighted 1000 to 1 reads 0.1 % and not 0 %,
    which would say it is off. A share above 99 % keeps as many decimals as its
    complement, so the two blocks of that pair still add up to 100 %.
    """
    percent = float(share) * 100.0
    if 0.0 < percent < 1.0:
        value, decimals = _one_significant_digit(percent)
        return f"{value:.{decimals}f}%"
    if 99.0 < percent < 100.0:
        value, decimals = _one_significant_digit(100.0 - percent)
        return f"{100.0 - value:.{decimals}f}%"
    return f"{percent:.0f}%"


def _one_significant_digit(value: float) -> tuple[float, int]:
    """Return ``value`` rounded to one significant digit, and its decimals in plain notation."""
    import math

    decimals = max(0, -math.floor(math.log10(value)))
    rounded = round(value, decimals)
    return rounded, max(0, -math.floor(math.log10(rounded)))


def _format_calibration_result(result: Any) -> list[str]:
    """Return the lines to print for a finished calibration.

    Reads only what :class:`hydromodpy.calibration.report.CalibrationReport`
    already carries: the best value per parameter, the cost it was reached
    at, the interval or width beside a value when the run produced one, a
    caution when the trials could not tell two parameters apart, ``k_over_r``
    when a network calibration published one in ``extra``, and, when the
    phase declared two or more objective blocks, the mean share of the cost
    each one actually took (with how many trials the mean covers) and its
    share at the best trial. A phase reused from disk that could not
    recompute a share prints why instead
    (``extra["objective_block_shares_absent_note"]``). A root search on one
    bound prints its final ``bracket``; a root search on two bounds prints
    ``roots`` instead, one line per bound then the spread and the combined
    value (:func:`_roots_lines`). Returns nothing for a
    result that carries no ``best_parameters`` (a staged calibration's own
    report object, or a run that evaluated no candidate), so the caller stays
    silent rather than guessing.
    """
    best_parameters = getattr(result, "best_parameters", None)
    if not best_parameters:
        return []

    widths = {item.parameter: item for item in getattr(result, "parameter_uncertainty", ())}
    extra = getattr(result, "extra", None) or {}
    intervals = {item["name"]: item for item in extra.get("parameter_intervals", [])}

    lines: list[str] = []
    for name, value in best_parameters.items():
        line = f"  {name} = {value:.6g}"
        width = widths.get(name)
        interval = intervals.get(name)
        if width is not None:
            line += f"  (sigma {width.sigma:.3g})"
        elif interval is not None:
            line += f"  [{interval['lower']:.6g}, {interval['upper']:.6g}]"
        if interval is not None and (
            interval["reaches_lower_bound"] or interval["reaches_upper_bound"]
        ):
            line += "  -- reached the search bound"
        lines.append(line)

    best_objective = getattr(result, "best_objective", None)
    if best_objective is not None:
        lines.append(f"  cost: {best_objective:.6g}")

    reported_tradeoff = False
    for name, width in widths.items():
        tradeoff = width.strongest_tradeoff()
        if tradeoff is not None and abs(tradeoff[1]) >= 0.9:
            lines.append(
                f"  caution: {name} and {tradeoff[0]} trade off (r = {tradeoff[1]:+.2f}), "
                "not identified separately."
            )
            reported_tradeoff = True
    if not reported_tradeoff:
        for first, second, coefficient in extra.get("correlated_parameters", []):
            lines.append(
                f"  caution: {first} and {second} moved together (r = {coefficient:+.2f}), "
                "not identified separately."
            )

    if "k_over_r_note" in extra:
        lines.append(f"  {extra['k_over_r_note']}")
    elif "k_over_r" in extra:
        lines.append(f"  k_over_r = {extra['k_over_r']:.4g}")

    for name, verdict in sorted((extra.get("roptim_verdict") or {}).items()):
        lines.append(f"  {_roptim_line(name, verdict)}")
    if extra.get("bracket"):
        lines.append(f"  {_bracket_line(extra['bracket'])}")
    if extra.get("roots"):
        lines.extend(f"  {line}" for line in _roots_lines(extra["roots"]))
    if extra.get("search"):
        lines.append(f"  {_search_line(extra['search'])}")

    shares = getattr(result, "objective_block_shares", None) or {}
    mean_shares = shares.get("mean")
    if mean_shares and len(mean_shares) > 1:
        n_trials = shares.get("mean_n_trials")
        mean_label = (
            f"mean over {n_trials} finished trials"
            if n_trials is not None
            else "mean over the finished trials"
        )
        lines.append(f"  cost share ({mean_label}): {_shares_text(mean_shares)}")
        best_shares = shares.get("best")
        if best_shares:
            lines.append(f"  cost share (best trial): {_shares_text(best_shares)}")
    elif "objective_block_shares_absent_note" in extra:
        lines.append(f"  cost share: {extra['objective_block_shares_absent_note']}")

    pairing = extra.get("first_trial_pairing")
    if pairing:
        for name, info in pairing.items():
            span = f" from {info['start']} to {info['end']}" if "start" in info else ""
            lines.append(f"  {name}: {info['n_paired']} pair(s){span} (first trial)")

    return lines


def _roptim_line(name: str, verdict: Mapping[str, Any]) -> str:
    """Return the Eq. 4 verdict of one network output, read at the returned trial.

    Eq. 4 bounds ``Doptim`` by the validity length, in metres; ``roptim`` is
    printed beside it as the paper's ratio. A failure names its cause: the
    mismatch itself, or the snap displacement bound of ``mode = "apply"``.
    """
    length = verdict.get("validity_length_m")
    provenance = verdict.get("provenance")
    bound = f"{float(length):.4g} m" if length is not None else "not published"
    if provenance:
        bound += f" ({provenance})"
    causes = list(verdict.get("causes") or [])
    value = verdict.get("value")
    optimal = verdict.get("Doptim")
    if "empty" in causes or optimal is None:
        return (
            f"roptim ({name}): not a number, the simulated network is empty at the "
            f"returned trial (validity length {bound})"
        )
    ratio = f"{float(value):.3g}" if value is not None else "not a number"
    sign = ">" if "doptim" in causes else "<="
    head = f"roptim ({name}) = {ratio}, Doptim = {float(optimal):.4g} m {sign} {bound}"
    if verdict.get("valid"):
        return f"{head}, Eq. 4 holds"
    reasons = []
    if "doptim" in causes:
        reasons.append("coarse agreement")
    snap = verdict.get("snap") or {}
    if "snap" in causes:
        reasons.append(
            "the snap moved the map beyond its bound (p90 displacement "
            f"{float(snap.get('displacement_p90_m', float('nan'))):.4g} m against "
            f"{float(snap.get('displacement_bound_m', float('nan'))):.4g} m, "
            f"{float(snap.get('rejected_share', float('nan'))):.1%} rejected against "
            f"{float(snap.get('rejected_share_max', float('nan'))):.0%})"
        )
    return f"{head}, Eq. 4 fails: " + ", and ".join(reasons or ["not qualified"])


def _bracket_line(bracket: Mapping[str, Any]) -> str:
    """Return the root search's final bracket, in the parameter's own units."""
    state = "closed" if bracket.get("closed") else "open, the budget ran out first"
    return (
        f"bracket on {bracket['parameter']}: [{float(bracket['low']):.6g}, "
        f"{float(bracket['high']):.6g}], width {float(bracket['relative_width']):.2%} ({state})"
    )


def _root_line(bound: str, root: Mapping[str, Any]) -> str:
    """Return one bound's root and its final bracket, in the parameter's own units."""
    state = "closed" if root.get("closed") else "open, the budget ran out first"
    return (
        f"K*_{bound} = {float(root['k_star']):.6g}, bracket [{float(root['low']):.6g}, "
        f"{float(root['high']):.6g}], width {float(root['relative_width']):.2%} ({state})"
    )


def _roots_lines(roots: Mapping[str, Any]) -> list[str]:
    """Return the two-root search's per-bound roots, their spread and the combined value.

    One line per bound (:func:`_root_line`), then ``Delta = log10(K*_maximal /
    K*_minimal)``, then the value the search returns, the weighted geometric
    mean of the two roots, with its weights.
    """
    lines = [_root_line("minimal", roots["minimal"]), _root_line("maximal", roots["maximal"])]
    delta = roots.get("delta_log10")
    delta_text = f"{delta:.3g}" if delta is not None else "unknown"
    lines.append(f"Delta = log10(K*_maximal / K*_minimal) = {delta_text} decade(s)")
    weights = f"{float(roots['minimal']['weight']):.3g} / {float(roots['maximal']['weight']):.3g}"
    value = roots.get("value")
    if value is None:
        lines.append(f"{roots['parameter']}: not solved (weighted geometric mean, {weights})")
    else:
        lines.append(
            f"{roots['parameter']} = {float(value):.6g}, weighted geometric mean of the "
            f"two roots ({weights})"
        )
    return lines


def _search_line(search: Mapping[str, Any]) -> str:
    """Return whether the search met its stopping rule, and what it spent."""
    spent = f"{search.get('n_evaluations')} evaluation(s) of {search.get('max_iter')} declared"
    extension = int(search.get("extension") or 0)
    if extension:
        spent += f" + {extension} extension"
    verdict = "converged" if search.get("converged") else "did NOT converge"
    return f"search: {verdict} on its rule ({search.get('stopping_rule')}), {spent}"


def _format_staged_calibration_result(result: Any) -> list[str]:
    """Return the lines to print for a finished staged calibration.

    A :class:`~hydromodpy.calibration.runners.staged_runner.StagedCalibrationReport`
    carries no ``best_parameters`` of its own: each phase does, in its own
    ``report``. Formats each phase's report with :func:`_format_calibration_result`
    and prefixes it with the phase's name, so a staged run prints as much per
    phase (cost, interval, cost share) as a single search prints for itself.
    """
    lines: list[str] = []
    for phase_run in getattr(result, "phases", ()):
        phase_lines = _format_calibration_result(getattr(phase_run, "report", None))
        if not phase_lines:
            continue
        lines.append(f"phase {phase_run.name}:")
        lines.extend(phase_lines)
    return lines


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    expand = getattr(args, "expand", False)
    if expand and (getattr(args, "check", False) or args.list_phases or args.phase is not None):
        print(
            "--expand cannot be combined with --check, --list-phases or --phase: it "
            "prints what a protocol writes, it runs nothing.",
            file=sys.stderr,
        )
        sys.exit(EXIT_USAGE)

    target = Path(args.config).expanduser().resolve()
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    if target.suffix != ".toml":
        print(f"Expected a .toml file, got: {target.suffix}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    from hydromodpy.core.toml_io.loader import load_toml_with_base_config

    try:
        raw_toml = load_toml_with_base_config(target)
    except Exception:
        raw_toml = {}
    apply_verbosity(args, raw_toml)

    profile_arg = getattr(args, "profile", None)
    if profile_arg is None:
        profile_arg = profile_arg_from_toml(raw_toml) if raw_toml else None
    if getattr(args, "check", False):
        _check_only(target)
        return
    if expand:
        _expand_only(target)
        return
    if args.list_phases:
        try:
            phases = hmp.calibrate(target, list_phases=True)
        except ConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        if not phases:
            print(f"{target.name} declares no phases.", file=sys.stderr)
            return
        for index, phase in enumerate(phases):
            print(_phase_line(index, phase))
            for row in phase.get("comparisons", []):
                print(f"    {_comparison_line(row)}")
        return

    profile_output = resolve_profile_output(profile_arg, target)
    try:
        with profile_run(profile_output, description=f"hmp calibrate {target.name}"):
            result = hmp.calibrate(target, phase=args.phase)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)
    except (ConfigError, ValidationError) as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except CalibrationError as exc:
        print(f"Calibration failed: {exc}", file=sys.stderr)
        sys.exit(EXIT_CALIBRATION)

    print(f"Calibration finished: {target.name}", file=sys.stderr)
    if result is None:
        return
    lines = (
        _format_staged_calibration_result(result)
        if getattr(result, "phases", None)
        else _format_calibration_result(result)
    )
    for line in lines:
        print(line, file=sys.stderr)
