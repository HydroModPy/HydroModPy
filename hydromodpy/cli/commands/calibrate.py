"""``hmp calibrate`` - run a calibration from a TOML file.

Thin wrapper around :func:`hydromodpy.calibrate`. A file declaring
``[calibration]`` calibrates; ``[workflow] mode`` may say so or be left out.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hydromodpy.calibration.runners.recap import result_lines, staged_result_lines
from hydromodpy.cli.conventions import (
    format_parser,
    profile_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.effective_toml import (
    ConfigFileError,
    add_override_arguments,
    cleanup_effective_toml,
    materialize_effective_toml,
    profile_output_of,
    toml_target,
)
from hydromodpy.cli.helpers import (
    EXIT_CALIBRATION,
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
    apply_verbosity,
    exit_if_session_unfinished,
    profile_run,
    project_named_by_w,
    refuse,
)
from hydromodpy.cli.output import emit
from hydromodpy.core.exceptions import CalibrationError, ConfigError

NAME: str = "calibrate"
HELP: str = "Run a calibration from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[workspace_parser(), format_parser(), profile_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n  hmp calibrate calibration.toml\n"
            "  hmp calibrate calibration.toml --dry-run\n"
            "  hmp calibrate calibration.toml --resume\n"
            "  hmp calibrate calibration.toml --list-phases\n"
            "  hmp calibrate calibration.toml --resume --phase phase_name\n"
            "  hmp calibrate calibration.toml --expand\n"
            "  hmp calibrate calibration.toml --set calibration.seed=7\n"
            "  hmp calibrate calibration.toml --overlay daily.toml --case calage_daily\n"
            "  hmp calibrate calibration.toml --format json\n"
            "Every launch, --dry-run included, runs the checks of\n"
            "hmp config check calibration.toml before anything is prepared.\n"
            "--format json prints the result, the phases or the plan once the command is over,\n"
            "as the page on what a program reads describes them."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("config", type=Path, help="Path to a calibration TOML file")
    parser.add_argument(
        "--phase",
        default=None,
        help="Run only this phase of a staged calibration, in the session of the case. "
        "Its dependency must have completed there, otherwise the phase would "
        "calibrate against un-frozen parameters.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reopen the latest session of the case: the phases that completed with the "
        "same fingerprint are read back, the cut phase is solved again with its "
        "trials preloading the cache.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Say which case, which session folder and which phases would run, and write nothing.",
    )
    parser.add_argument(
        "--list-phases",
        action="store_true",
        help="List the declared phases and exit without running anything. A file "
        "without phases gets one line for its single search.",
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        help="Print the [calibration] section a protocol writes, as TOML, and exit "
        "without running anything. A file naming no protocol prints its own section. "
        "Refused together with --phase, --list-phases, --resume or --dry-run.",
    )
    parser.add_argument(
        "--case",
        default=None,
        metavar="NAME",
        help=(
            "Name of the case: its session is sessions/<name>. Defaults to [simulation] "
            "name, else the stem of the TOML. A calibration launched with --set or "
            "--overlay keeps that name; use --case to name the variant."
        ),
    )
    add_override_arguments(parser)
    parser.set_defaults(_handler=run)
    return parser


def _expand_only(args: argparse.Namespace, target: Path, *, shown_as: str) -> None:
    """Print the ``[calibration]`` section a protocol unfolds into, as TOML, and exit.

    Formatting only: :func:`hydromodpy.calibrate` does the unfolding and
    returns the whole section, pasteable in place of the protocol. A file
    naming no protocol gets a header saying so instead of a protocol line, and
    its own section is printed unchanged. The ``protocol__delete`` hint is
    printed only when the protocol comes from the ``base_config``: that is the
    one case where a file pasting the section under the same base has an
    inherited protocol to drop.
    """
    import hydromodpy as hmp

    try:
        expanded = hmp.calibration_phases(target)
    except ConfigError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    emit(args, "calibrate phases", expanded, table=lambda: _print_expanded(expanded, shown_as))


def _print_expanded(expanded: Mapping[str, Any], shown_as: str) -> None:
    import io

    from hydromodpy.core.toml_io.writer import dump

    protocol = expanded["protocol"]
    if protocol is None:
        print(f"# {shown_as} declares no protocol: this is its [calibration] section as declared.")
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
    interval with and where it comes from, then the bounds the phase narrows its
    parameters to, when it writes any. A column names what the phase takes
    from ``[calibration]`` among its budget, precision and options, when it takes
    any. Another is added only for a phase that moves again what an earlier phase
    passed on: which parameters, from which phase, and whether the search starts
    there.
    """
    method = phase["method"]
    search = phase.get("search", {})
    if phase.get("method_reason"):
        method = f"{method} ({phase['method_reason']})"
    elif search.get("method", {}).get("source") == "section":
        method = f"{method} (from [calibration])"
    line = f"{index}\t{phase['name']}\t{method}\t{phase['description']}"
    if phase.get("interval_width"):
        line = f"{line}\t{_width_text(phase['interval_width'])}"
    if phase.get("bounds"):
        narrowed = ", ".join(f"{name} {interval}" for name, interval in phase["bounds"].items())
        line = f"{line}\tbounds {narrowed}"
    taken = [
        f"{key} {search[key]['value']}"
        for key in ("max_trials", "precision", "method_options")
        if search.get(key, {}).get("source") == "section"
    ]
    if taken:
        line = f"{line}\ttakes from [calibration]: {', '.join(taken)}"
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


def _print_single_search(target: Path) -> None:
    """Print the ``--list-phases`` line of a file without phases, and what it compares.

    The file still runs one search. Its line names the method, and why when the
    file leaves it to be chosen, under ``[calibration]`` where a phase line has
    its index and name.
    """
    from hydromodpy.calibration.preflight import comparison_line
    from hydromodpy.calibration.runners.document import (
        declared_window_text,
        load_toml_calibration,
        resolve_stream_geometry_paths,
    )
    from hydromodpy.calibration.runners.staged_runner import objective_comparison_table

    calibration, _raw = load_toml_calibration(target)
    method, reason = calibration.method_for()
    print(f"[calibration]\t{method} ({reason})" if reason else f"[calibration]\t{method}")
    resolve_stream_geometry_paths(calibration, target)
    for row in objective_comparison_table(calibration, None):
        print(f"    {comparison_line(row)}")
    print(f"    scores on: {declared_window_text(calibration)}")


_WRITTEN_IN = {"phase": "written in the phase", "section": "written in [calibration.uncertainty]"}


def _width_text(width: dict[str, Any]) -> str:
    """Return the width a phase reads its interval with, and where it comes from."""
    source = width["source"]
    if source == "default":
        value = width["rule"]
        origin = (
            "default, measured on the mesh when the phase runs"
            if width["margin"] is None
            else "default"
        )
    else:
        margin = float(width["margin"])
        value = (
            f"{margin * 100:g} % of the best cost"
            if width["kind"] == "relative"
            else f"{margin:g} m"
        )
        origin = _WRITTEN_IN[source]
    return f"width {value} ({origin})"


def _print_dry_run(plan: Mapping[str, Any]) -> None:
    """Print what a calibration would do, one line per fact."""
    print(f"case: {plan['case']}", file=sys.stderr)
    print(f"session: {plan['session_dir']}", file=sys.stderr)
    print(f"calibrated run: {plan['run_dir']} (save_runs = {plan['save_runs']})", file=sys.stderr)
    for phase in plan["phases"]:
        print(
            f"  phase {phase['name']}: {', '.join(phase['parameters'])}, {phase['max_trials']} "
            f"trials, scores on {phase['window']}",
            file=sys.stderr,
        )
    print(f"solves in parallel: {plan['solves_in_parallel']}", file=sys.stderr)


def run(args: argparse.Namespace) -> None:
    expand = getattr(args, "expand", False)
    resume = getattr(args, "resume", False)
    dry_run = getattr(args, "dry_run", False)
    if expand and (args.list_phases or args.phase is not None or resume or dry_run):
        refuse(
            "--expand cannot be combined with --list-phases, --phase, --resume or "
            "--dry-run: it prints what a protocol writes, it runs nothing.",
            EXIT_USAGE,
        )

    target = toml_target(args.config)
    with project_named_by_w(getattr(args, "workspace", None)):
        _run_named(args, target)


def _run_named(args: argparse.Namespace, target: Path) -> None:
    """Run the verb on ``target``, inside the project ``-w`` names."""
    effective: Path | None = None
    try:
        effective, raw_toml, _lineage = materialize_effective_toml(target, args=args)
    except ConfigFileError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    except FileNotFoundError as exc:
        refuse(f"Missing file: {exc}", EXIT_NOT_FOUND, cause=exc)
    except ValueError as exc:
        refuse(f"Invalid override: {exc}", EXIT_CONFIG, cause=exc)
    try:
        _calibrate(args, target, effective or target, raw_toml)
    finally:
        cleanup_effective_toml(effective, source=target)


def _calibrate(
    args: argparse.Namespace, target: Path, run_path: Path, raw_toml: Mapping[str, Any]
) -> None:
    """Run, list or expand the calibration of ``run_path``, the file the user named or its copy.

    ``target`` is the file the user named: messages say its name, never the
    temporary copy's.
    """
    import hydromodpy as hmp

    expand = getattr(args, "expand", False)
    resume = getattr(args, "resume", False)
    dry_run = getattr(args, "dry_run", False)
    apply_verbosity(args, raw_toml)

    from hydromodpy.config.sites import is_sites_project

    if is_sites_project(raw_toml):
        refuse(
            f"{target.name} belongs to a [sites] project: hmp run {target.name} runs this "
            "recipe on every site.",
            EXIT_CONFIG,
        )

    if expand:
        _expand_only(args, run_path, shown_as=target.name)
        return
    if args.list_phases:
        try:
            expanded = hmp.calibration_phases(run_path)
        except ConfigError as exc:
            refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
        emit(
            args,
            "calibrate phases",
            expanded,
            table=lambda: _print_phases(expanded["phases"], target, run_path),
        )
        return

    profile_output = profile_output_of(args, raw_toml, target)
    try:
        if dry_run:
            plan = hmp.calibration_phases(run_path, check=True)["plan"]
            declared = [item["name"] for item in plan["phases"]]
            if args.phase is not None and args.phase not in declared:
                raise CalibrationError(
                    f"unknown phase {args.phase!r}; the calibration declares {declared}."
                )
            emit(args, "calibrate plan", plan, table=lambda: _print_dry_run(plan))
            return
        with profile_run(profile_output, description=f"hmp calibrate {target.name}"):
            result = hmp.calibrate(run_path, phase=args.phase, resume=resume)
    except (ConfigError, ValidationError) as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    except FileNotFoundError as exc:
        refuse(f"Missing file: {exc}", EXIT_NOT_FOUND, cause=exc)
    except CalibrationError as exc:
        refuse(f"Calibration failed: {exc}", EXIT_CALIBRATION, cause=exc)

    def table() -> None:
        print(f"Calibration finished: {target.name}", file=sys.stderr)
        lines = (
            staged_result_lines(result) if getattr(result, "phases", None) else result_lines(result)
        )
        for line in lines:
            print(line, file=sys.stderr)

    emit(args, "calibrate", result.to_dict(), table=table)
    exit_if_session_unfinished(result)


def _print_phases(phases: list[dict[str, Any]], target: Path, run_path: Path) -> None:
    """Print the ``--list-phases`` page: one line per phase, what it compares and scores on."""
    from hydromodpy.calibration.preflight import comparison_line

    if not phases:
        print(f"{target.name} declares no phases; it runs one search.", file=sys.stderr)
        _print_single_search(run_path)
        return
    for index, phase in enumerate(phases):
        print(_phase_line(index, phase))
        for row in phase.get("comparisons", []):
            print(f"    {comparison_line(row)}")
        if phase.get("window"):
            print(f"    scores on: {phase['window']}")
