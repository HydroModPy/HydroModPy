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

from hydromodpy.cli._conventions import profile_parser, verbosity_parser
from hydromodpy.cli.helpers import (
    EXIT_CALIBRATION,
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    EXIT_USAGE,
    apply_verbosity,
    exit_if_promotion_failed,
    profile_arg_from_toml,
    profile_run,
    resolve_profile_output,
)
from hydromodpy.core.exceptions import CalibrationError, ConfigError

NAME: str = "calibrate"
HELP: str = "Run a calibration from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[profile_parser(), verbosity_parser()],
        epilog=(
            "Examples:\n  hmp calibrate calibration.toml\n"
            "  hmp calibrate calibration.toml --dry-run\n"
            "  hmp calibrate calibration.toml --resume\n"
            "  hmp calibrate calibration.toml --list-phases\n"
            "  hmp calibrate calibration.toml --resume --phase phase_name\n"
            "  hmp calibrate calibration.toml --expand\n"
            "Checks before any solve: hmp config check calibration.toml"
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
    parser.set_defaults(_handler=run)
    return parser


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


def _print_single_search(target: Path) -> None:
    """Print the ``--list-phases`` line of a file without phases, and what it compares.

    The file still runs one search. Its line names the method, and why when the
    file leaves it to be chosen, under ``[calibration]`` where a phase line has
    its index and name.
    """
    from hydromodpy.calibration.preflight import comparison_line
    from hydromodpy.calibration.runners.cli_runner import (
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
    from hydromodpy.calibration.preflight import percent

    return ", ".join(f"{name} {percent(value)}" for name, value in shares.items())


def _format_calibration_result(result: Any) -> list[str]:
    """Return the lines to print for a finished calibration.

    Reads only what :class:`hydromodpy.calibration.report.CalibrationReport`
    already carries: the best value per parameter, the cost it was reached
    at and the metric that cost is (``extra["cost_metric"]``), the interval or
    width beside a value when the run produced one, a
    caution when the trials could not tell two parameters apart, ``k_over_r``
    when a network calibration published one in ``extra``, and, when the
    phase declared two or more objective blocks, the mean share of the cost
    each one actually took (with how many trials the mean covers) and its
    share at the best trial. A phase reused from disk that could not
    recompute a share prints why instead
    (``extra["objective_block_fractions_absent_note"]``). A root search on one
    bound prints its final ``bracket``; a root search on two bounds prints
    ``roots`` instead, one line per bound then the spread and the combined
    value (:func:`_roots_lines`). Returns nothing for a
    result that carries no ``best_parameters`` (a staged calibration's own
    report object, or a run that evaluated no candidate), so the caller stays
    silent rather than guessing.
    """
    from hydromodpy.calibration.report import NO_OTHER_TRIAL, interval_is_degenerate

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
        elif interval is not None and interval_is_degenerate(interval):
            line += f"  ({NO_OTHER_TRIAL})"
        elif interval is not None:
            line += f"  [{interval['lower']:.6g}, {interval['upper']:.6g}]"
        if interval is not None and (
            interval["reaches_lower_bound"] or interval["reaches_upper_bound"]
        ):
            line += "  -- reached the search bound"
        lines.append(line)

    best_objective = getattr(result, "best_objective", None)
    if best_objective is not None:
        # A cost of 0.12 on an NSE reads as a poor score; the metric says it is 1 - NSE.
        metric = extra.get("cost_metric")
        lines.append(f"  cost: {best_objective:.6g}" + (f" ({metric})" if metric else ""))
    best_rel_dir = getattr(result, "best_rel_dir", None)
    if best_rel_dir:
        lines.append(f"  calibrated run: {best_rel_dir}")

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

    shares = getattr(result, "objective_block_fractions", None) or {}
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
    elif "objective_block_fractions_absent_note" in extra:
        lines.append(f"  cost share: {extra['objective_block_fractions_absent_note']}")

    pairing = extra.get("first_trial_pairing")
    if pairing:
        for name, info in pairing.items():
            span = f" from {info['start']} to {info['end']}" if "start" in info else ""
            lines.append(f"  {name}: {info['n_paired']} pair(s){span} (first trial)")

    return lines


def _roptim_line(name: str, verdict: Mapping[str, Any]) -> str:
    """Return the Eq. 4 verdict of one network output, read at the returned trial.

    Eq. 4 bounds ``Doptim`` by the validity length, in metres; ``roptim`` is
    printed beside it as the paper's ratio.
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


def _print_dry_run(plan: Mapping[str, Any]) -> None:
    """Print what a calibration would do, one line per fact."""
    print(f"case: {plan['case']}", file=sys.stderr)
    print(f"session: {plan['session_dir']}", file=sys.stderr)
    print(f"calibrated run: {plan['run_dir']} (save_runs = {plan['save_runs']})", file=sys.stderr)
    for phase in plan["phases"]:
        print(
            f"  phase {phase['name']}: {', '.join(phase['parameters'])}, {phase['max_iter']} trials",
            file=sys.stderr,
        )
    print(f"solves in parallel: {plan['solves_in_parallel']}", file=sys.stderr)


def run(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    expand = getattr(args, "expand", False)
    resume = getattr(args, "resume", False)
    dry_run = getattr(args, "dry_run", False)
    if expand and (args.list_phases or args.phase is not None or resume or dry_run):
        print(
            "--expand cannot be combined with --list-phases, --phase, --resume or "
            "--dry-run: it prints what a protocol writes, it runs nothing.",
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

    from hydromodpy.config.sites.expansion import is_sites_project

    if is_sites_project(raw_toml):
        print(
            f"{target.name} belongs to a [sites] project: hmp run {target.name} runs this "
            "recipe on every site.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    profile_arg = getattr(args, "profile", None)
    if profile_arg is None:
        profile_arg = profile_arg_from_toml(raw_toml) if raw_toml else None
    if expand:
        _expand_only(target)
        return
    if args.list_phases:
        from hydromodpy.calibration.preflight import comparison_line

        try:
            phases = hmp.calibrate(target, list_phases=True)
        except ConfigError as exc:
            print(f"Config invalid: {exc}", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        if not phases:
            print(f"{target.name} declares no phases; it runs one search.", file=sys.stderr)
            _print_single_search(target)
            return
        for index, phase in enumerate(phases):
            print(_phase_line(index, phase))
            for row in phase.get("comparisons", []):
                print(f"    {comparison_line(row)}")
        return

    profile_output = resolve_profile_output(profile_arg, target)
    try:
        with profile_run(profile_output, description=f"hmp calibrate {target.name}"):
            result = hmp.calibrate(target, phase=args.phase, resume=resume, dry_run=dry_run)
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

    if dry_run:
        _print_dry_run(result if isinstance(result, Mapping) else {})
        return
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
    exit_if_promotion_failed(result)
