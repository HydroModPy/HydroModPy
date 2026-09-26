"""``hmp calibrate`` - run a calibration workflow from a TOML file.

Thin wrapper around :func:`hydromodpy.calibrate`. The TOML must declare
``[workflow] mode = "calibration"`` (resolved by the workflow dispatcher).
"""

from __future__ import annotations

import argparse
import sys
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


def _check_only(target: Path) -> None:
    """Report everything wrong with the calibration in ``target`` and exit.

    Nothing solves, so this costs a second whatever the model. Every check runs,
    so a file with three mistakes takes one pass to fix rather than three
    overnight runs.
    """
    from hydromodpy.calibration.preflight import PreflightFinding, preflight_calibration
    from hydromodpy.config import HydroModPyConfig

    try:
        cfg = HydroModPyConfig.from_toml(target)
    except Exception as exc:
        # A file that will not load has nothing else to check: every other
        # finding would be about a configuration that does not exist.
        findings = [PreflightFinding("error", target.name, f"the file does not load: {exc}")]
    else:
        _announce_the_protocol(cfg)
        _announce_the_comparisons(cfg, target)
        findings = preflight_calibration(cfg, source=target)
    if not findings:
        print(f"{target.name}: ready to run.", file=sys.stderr)
        return
    for finding in findings:
        print(finding.line(), file=sys.stderr)
    errors = sum(1 for finding in findings if finding.severity == "error")
    print(
        f"{target.name}: {errors} error(s), {len(findings) - errors} warning(s).",
        file=sys.stderr,
    )
    if errors:
        sys.exit(EXIT_CONFIG)


def _announce_the_protocol(cfg) -> None:
    """Say which published method this file runs, and what it rests on.

    A calibrated value that came out of a named method carries the method with
    it. Printing it here is where the reader is already looking, before an
    overnight run rather than after.
    """
    declared = getattr(getattr(cfg, "calibration", None), "protocol", None)
    if declared is None:
        return
    from hydromodpy.calibration.protocols import protocol_record

    record = protocol_record(declared.name, declared)
    print(
        f"protocol: {record['name']}@{record['version']} - {record['title']}",
        file=sys.stderr,
    )
    for index, stage in enumerate(record["stages"], start=1):
        print(f"  stage {index}: {stage}", file=sys.stderr)
    for reference in record["references"]:
        print(f"  cite: {reference}", file=sys.stderr)
    # Where this run departs from the publication it cites. A reader comparing a
    # result to the literature needs this before the run, not after.
    chosen = _values_this_file_set(cfg, [item["key"] for item in record["deviations"]])
    for deviation in record["deviations"]:
        line = (
            f"  differs from the paper on {deviation['key']}: {deviation['here']} "
            f"(paper: {deviation['paper']})"
        )
        if deviation["key"] in chosen:
            line += f" - this file sets {_rendered(chosen[deviation['key']])}"
        print(line, file=sys.stderr)
    # An option moved off the recipe keeps the method but changes what the number
    # rests on, and only the file knows it moved.
    for option in record.get("options_away_from_the_recipe", ()):
        print(
            f"  option away from the recipe: {option['key']} = "
            f"{_rendered(option['here'])} (recipe: {_rendered(option['recipe'])})",
            file=sys.stderr,
        )
    backend = getattr(getattr(cfg, "solver", None), "backend_name", None)
    backend = str(getattr(backend, "value", backend) or "")
    verdict = record["support"].get(backend)
    if verdict is not None and verdict != "tested":
        print(
            f"  on {backend}: {verdict.replace('_', ' ')} - no case in this repository "
            "runs the protocol on that backend.",
            file=sys.stderr,
        )


def _rendered(value: object) -> str:
    """Return a value as a reader of a terminal would want to see it.

    A quantity reprs as ``<Quantity(50, 'meter')>``, which is the object and not
    the number the file wrote.
    """
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
        print(f"compares ({label}):", file=sys.stderr)
        for row in table:
            print(f"  {_comparison_line(row)}", file=sys.stderr)


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
        f"{label}\t{row['metric']}\tshare {row['share'] * 100:.0f}%\t{row['quantity']}\tvs {source}"
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


def _values_this_file_set(cfg, keys: list[str]) -> dict[str, object]:
    """Return, for the keys a protocol departs on, what this file actually wrote.

    The deviation table describes the recipe's defaults. What a reader comparing
    to the publication needs is the value in front of them, which may be the
    paper's or may be the departure.
    """
    calibration = getattr(cfg, "calibration", None)
    outputs = getattr(calibration, "outputs", None) or {}
    found: dict[str, object] = {}
    for key in keys:
        for output in outputs.values():
            value = getattr(output, key, None)
            if value is not None:
                found[key] = value
                break
    return found


def _expand_only(target: Path) -> None:
    """Print the ``[calibration]`` section a protocol writes, as TOML, and exit.

    Formatting only: :func:`hydromodpy.calibrate` does the unfolding and
    decides what belongs in the section and in the header. A file naming no
    protocol gets a header saying so instead of a protocol line, and its own
    section is printed unchanged.
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
        print("# A file inheriting the protocol from its base_config adds:")
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
    return ", ".join(f"{name} {value * 100:.0f}%" for name, value in shares.items())


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
    (``extra["objective_block_shares_absent_note"]``). Returns nothing for a
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
