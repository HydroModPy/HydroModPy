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

from hydromodpy.cli._conventions import profile_parser
from hydromodpy.cli.helpers import (
    EXIT_CALIBRATION,
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    profile_arg_from_toml,
    profile_run,
    resolve_profile_output,
)
from hydromodpy.core.exceptions import CalibrationError, ConfigError

NAME: str = "calibrate"
HELP: str = "Run a calibration workflow from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[profile_parser()])
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


def _format_calibration_result(result: Any) -> list[str]:
    """Return the lines to print for a finished calibration.

    Reads only what :class:`hydromodpy.calibration.report.CalibrationReport`
    already carries: the best value per parameter, the cost it was reached
    at, the interval or width beside a value when the run produced one, a
    caution when the trials could not tell two parameters apart, and
    ``k_over_r`` when a network calibration published one in ``extra``.
    Returns nothing for a result that carries no ``best_parameters`` (a
    staged calibration's own report object, or a run that evaluated no
    candidate), so the caller stays silent rather than guessing.
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

    return lines


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    target = Path(args.config).expanduser().resolve()
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    if target.suffix != ".toml":
        print(f"Expected a .toml file, got: {target.suffix}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    profile_arg = getattr(args, "profile", None)
    if profile_arg is None:
        from hydromodpy.core.toml_io.loader import load_toml_with_base_config

        try:
            profile_arg = profile_arg_from_toml(load_toml_with_base_config(target))
        except Exception:
            profile_arg = None
    if getattr(args, "check", False):
        _check_only(target)
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
            print(f"{index}\t{phase['name']}\t{phase['method']}\t{phase['description']}")
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
    for line in _format_calibration_result(result):
        print(line, file=sys.stderr)
