"""``hmp run`` - execute the workflow of a TOML file.

Single CLI entry point. The file names its workflow with ``[workflow] mode``
(``simulation``, ``calibration`` or ``overview``) or leaves it to its sections
(:func:`hydromodpy.workflow.dispatch.resolve_workflow`).

Overrides are merged as defaults < base_config < --overlay < --set < env. A run
launched with ``--set`` or ``--overlay`` keeps its name: the surcharge is sealed
in ``lineage.overrides`` and ``.vN`` handles the collision.

The command is the worker of one case: it claims ``runs/<case>/``, runs the
pipeline and seals the run. It never opens the index; once the worker has
returned, the command indexes the run directory, unless a launcher started
it (``HMP_LAUNCHED_CASE``), in which case the launcher indexes.

On a ``[sites]`` project (``project.toml``, or one recipe file of it) the
command is the local launcher instead: it writes the plan, runs the prepare
phase, then one worker per case (:mod:`hydromodpy.project.launch`).
``--only``, ``--site``, ``--parallel``, ``--until data``, ``--fresh``,
``--force`` and a bare ``--resume`` choose what the launch does.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

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
    resolve_case_name,
)
from hydromodpy.cli.helpers import (
    EXIT_CASES_FAILED,
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    EXIT_USAGE,
    PROJECT_ROOT_ENV,
    apply_verbosity,
    exit_code_for,
    exit_if_session_unfinished,
    fail,
    profile_arg_from_toml,
    profile_run,
    project_named_by_w,
    refuse,
    resolve_profile_output,
)
from hydromodpy.cli.output import emit
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import data_cache_path_for
from hydromodpy.core.state.portable import display_path
from hydromodpy.core.state.result_dirs import refuse_a_sealed_run_as_project, resolve_project_root
from hydromodpy.core.toml_io.overrides import set_overrides

logger = get_logger(__name__)

NAME: str = "run"
HELP: str = "Run a workflow from a TOML config"

INDEXED_WORKFLOWS = ("simulation", "overview")
"""Workflows whose run directory the command indexes once the worker has returned."""


HEAD_ONLY_MESSAGE = (
    "window stops before setup_process: no run directory is written, the input cache is filled"
)
"""Said when ``--until`` ends the window before the model phase: nothing else tells it."""


def _stops_before_setup_process(until_step: str | None) -> bool:
    """Return whether ``--until`` ends the window before ``setup_process``."""
    if until_step is None:
        return False
    from hydromodpy.workflow.steps.sequence import standard_steps
    from hydromodpy.workflow.window import model_phase_index, resolve_step_index

    steps = standard_steps()
    try:
        return resolve_step_index(until_step, steps) < model_phase_index(steps)
    except ConfigError:
        # The runner refuses an unknown step by itself; here only the message is at stake.
        return False


def _step_choices() -> list[str]:
    """Return the canonical pipeline step names for shell completion."""
    try:
        from hydromodpy.workflow.steps.sequence import standard_steps

        return [getattr(s, "name", type(s).__name__) for s in standard_steps()]
    except Exception:
        return []


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser(), profile_parser(), verbosity_parser(), workspace_parser()],
        epilog="Examples:\n  hmp run run.toml\n  hmp run run.toml --dry-run\n  hmp run run.toml --set flow.param.K.field.value=2e-5\n  hmp run run.toml --overlay daily.toml --case baseline_daily\n  hmp run run.toml --from setup_process --until run_solver\n  hmp run --resume baseline_monthly\n  hmp run run.toml --fresh",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_arg = parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=None,
        help="Path to a TOML config (omit when using --resume REF)",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="",
        default=None,
        metavar="REF",
        help=(
            "Continue an interrupted case in place, from the journal of its directory. "
            "With a TOML config, REF is the case name to continue (bare: the case the "
            "file names); without a config, REF is the case name and the run replays its "
            "own runs/<name>/config.toml. A calibration takes a bare --resume and reopens "
            "the latest session of its case. On a [sites] project, bare --resume starts "
            "only the cases with an unfinished attempt."
        ),
    )
    from_arg = parser.add_argument(
        "--from",
        dest="from_step",
        default=None,
        metavar="STEP",
        help="Start from this pipeline step, by its name.",
    )
    until_arg = parser.add_argument(
        "--until",
        dest="until_step",
        default=None,
        metavar="STEP",
        help=(
            "Stop after this pipeline step, by its name. On a [sites] "
            "project, --until data stops after the prepare phase."
        ),
    )
    try:
        from argcomplete.completers import ChoicesCompleter, FilesCompleter

        config_arg.completer = FilesCompleter(("toml",))
        step_completer = ChoicesCompleter(_step_choices())
        from_arg.completer = step_completer
        until_arg.completer = step_completer
    except ImportError:
        pass
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print the resolved workflow plan without executing it.",
    )
    parser.add_argument(
        "--frozen",
        action="store_true",
        help=(
            "On a project TOML, reject any fresh download: every artefact must already be "
            "in the catalog and match hydromodpy.lock. On the config.toml of a run, check its "
            "inputs against its record and refuse a value that differs from config.resolved.toml."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Go past what the command refuses because of what is there: recompute when a "
            "completed run with an identical resolved config and the same name already "
            "exists, and claim a stale case whose process cannot be proven dead. Without it "
            "an identical run is not recomputed: the command stops and names it. Simulation "
            "workflow only. On a [sites] project it also lifts the budget ceilings (parallel, "
            "prepare_parallel, calibrations, cores), takes over the lease of a launcher still "
            "alive and plans over a running case."
        ),
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="WHAT",
        help=(
            "[sites] project: start only these cases, named by status (failed, stale, "
            "partial, aborted, planned, completed) or by case id (shell patterns allowed). "
            "Repeatable, or comma separated."
        ),
    )
    parser.add_argument(
        "--site",
        default=None,
        metavar="SITE",
        help="[sites] project: start only the cases of this site.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=None,
        metavar="N",
        help=(
            "[sites] project: solves side by side, a calibration counting its own "
            "[calibration] parallel. Defaults to [sites.run] parallel."
        ),
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Start the case over: everything the previous attempt left in runs/<case>/ "
            "is filed under attempts/<k>/ first. Without it a retry resumes in place."
        ),
    )
    parser.add_argument(
        "--case",
        default=None,
        metavar="NAME",
        help=(
            "Name of the run. Defaults to [simulation] name, else the stem of the TOML. "
            "A run launched with --set or --overlay keeps that name; use --case to name "
            "the variant."
        ),
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        dest="no_display",
        help="Skip auto-rendering of the figures listed in [display].figures.",
    )
    add_override_arguments(parser)
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.project.launch.env import apply_thread_budget

    try:
        apply_thread_budget()
    except ValueError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    config = getattr(args, "config", None)
    if config is None:
        resume = getattr(args, "resume", None)
        if not resume:
            refuse("Provide a TOML config, or --resume REF to resume a catalog run.", EXIT_CONFIG)
        with project_named_by_w(getattr(args, "workspace", None)):
            _resume_from_ref(str(resume), args=args)
        return

    target = Path(config).expanduser().resolve()
    if not target.is_file():
        refuse(f"File not found: {target}", EXIT_NOT_FOUND)

    if target.suffix == ".toml":
        with project_named_by_w(getattr(args, "workspace", None)):
            _run_toml(target, args=args)
    elif target.suffix == ".py":
        refuse(
            "Python scripts are not supported by 'hmp run'. Run the script with python directly.",
            EXIT_CONFIG,
        )
    else:
        refuse(f"Unsupported file type: {target.suffix} (expected .toml)", EXIT_CONFIG)


def _resume_from_ref(ref: str, *, args: argparse.Namespace) -> None:
    """Continue an interrupted case from the config frozen in its own run directory.

    Resolves REF as a case name under ``runs/`` of the project ``-w`` names, else
    the one around the current directory (``baseline`` is its latest version,
    ``baseline.v2`` that one) and replays ``runs/<name>/config.toml`` - the resolved configuration
    the run was executed with - through the same path as
    ``hmp run config.toml --resume NAME``.
    """
    from hydromodpy.results.manifest import is_sealed, read_seal
    from hydromodpy.results.storage.attempt import run_dir_for_name
    from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME

    named = os.environ.get(PROJECT_ROOT_ENV)
    workspace = Path(named) if named else resolve_project_root(Path.cwd().resolve())
    run_dir = run_dir_for_name(workspace, ref)
    if run_dir is None:
        refuse(
            f"No case named {ref!r} under {display_path(workspace)}/runs; run --resume REF "
            "must be invoked from the project, or pass a TOML config explicitly.",
            EXIT_NOT_FOUND,
        )
    config_path = run_dir / RUN_CONFIG_FILENAME
    if not config_path.is_file():
        refuse(
            f"Case '{run_dir.name}' has no frozen {RUN_CONFIG_FILENAME} in "
            f"{display_path(run_dir)}; pass the TOML config explicitly to resume it.",
            EXIT_NOT_FOUND,
        )
    if is_sealed(run_dir) and read_seal(run_dir).lineage.session_id is not None:
        refuse(
            f"{run_dir.name} came out of a calibration, and a run only holds its own solve. "
            "Reopen the session from the file that launched it: hmp run <file>.toml --resume.",
            EXIT_CONFIG,
        )

    args.resume = run_dir.name
    _run_toml(config_path, args=args)


def _replay_project_root() -> Path:
    """Return the project a published copy replays into: ``-w``, else the one around the cwd."""
    from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME

    named = os.environ.get(PROJECT_ROOT_ENV)
    root = Path(named) if named else resolve_project_root(Path.cwd().resolve())
    if not (root / PROJECT_MARKER_FILENAME).is_file():
        refuse(
            f"A published copy replays into a project: no {PROJECT_MARKER_FILENAME} at or above "
            f"{Path.cwd()}. Name the project with -w.",
            EXIT_NOT_FOUND,
        )
    return root


def _replay_published_copy(copy_dir: Path, config_path: Path, *, args: argparse.Namespace) -> None:
    """Replay the frozen configuration of a published copy from the bytes it carries.

    ``--frozen`` on a copy checks every file of its install index against
    ``inputs/`` and points the configuration at those bytes, a declared
    folder rebuilt under ``<project>/.hmp/replay/<copy>/``
    (:mod:`hydromodpy.project.exchange.replay`); the copy holds no lockfile, so
    the run itself is not bound to one. The run is written into the project
    ``-w`` names, or the one around the current directory.
    """
    import shutil

    from hydromodpy.config.hydromodpy_config import ROOT_CONFIG
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.core.toml_io.writer import dumps
    from hydromodpy.project.exchange.replay import ReplayInputError, replay_payload

    root = _replay_project_root()
    folder = root / ".hmp" / "replay"
    workdir = folder / copy_dir.name
    try:
        payload = replay_payload(
            copy_dir, load_toml_with_base_config(config_path, root=ROOT_CONFIG), workdir=workdir
        )
    except ReplayInputError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    folder.mkdir(parents=True, exist_ok=True)
    replay_path = folder / f"{copy_dir.name}.toml"
    replay_path.write_text(dumps(payload), encoding="utf-8")
    args.frozen = False
    previous = os.environ.get(PROJECT_ROOT_ENV)
    os.environ[PROJECT_ROOT_ENV] = str(root)
    try:
        _run_toml(replay_path, args=args, replayed_copy=copy_dir)
    finally:
        replay_path.unlink(missing_ok=True)
        shutil.rmtree(workdir, ignore_errors=True)
        if not any(folder.iterdir()):
            folder.rmdir()
        if previous is None:
            os.environ.pop(PROJECT_ROOT_ENV, None)
        else:
            os.environ[PROJECT_ROOT_ENV] = previous


def _run_toml(
    config_path: Path, *, args: argparse.Namespace, replayed_copy: Path | None = None
) -> None:
    """Run a workflow from a TOML file.

    The workflow is the declared ``[workflow] mode`` or the one the sections
    imply; a retired mode exits with ``EXIT_CONFIG`` and names its replacement.
    The frozen configuration of a published copy, with ``--frozen``, replays
    from the bytes of the copy (:func:`_replay_published_copy`), which is
    *replayed_copy* here.
    """
    from hydromodpy.project.exchange.replay import published_copy_of

    copy_dir = published_copy_of(config_path) if getattr(args, "frozen", False) else None
    if copy_dir is not None:
        _replay_published_copy(copy_dir, config_path, args=args)
        return

    profile_output = resolve_profile_output(getattr(args, "profile", None), config_path)

    from hydromodpy.project.launch.sites.plan import refuse_env_overrides

    refuse_env_overrides(os.environ, config_path)

    effective_path: Path | None = None
    try:
        effective_path, raw_toml, lineage_overrides = materialize_effective_toml(
            config_path, args=args
        )
    except ConfigFileError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    except FileNotFoundError as exc:
        refuse(f"Missing file: {exc}", EXIT_NOT_FOUND, cause=exc)
    except ValueError as exc:
        refuse(f"Invalid override: {exc}", EXIT_CONFIG, cause=exc)
    try:
        _run_effective(
            config_path,
            effective_path,
            raw_toml,
            lineage_overrides,
            args=args,
            profile_output=profile_output,
            replayed_copy=replayed_copy,
        )
    finally:
        cleanup_effective_toml(effective_path, source=config_path)


def _run_effective(
    config_path: Path,
    effective_path: Path | None,
    raw_toml: dict[str, Any],
    lineage_overrides: dict[str, Any],
    *,
    args: argparse.Namespace,
    profile_output: Path | None,
    replayed_copy: Path | None,
) -> None:
    """Run the workflow of *config_path* from its effective copy, which the caller removes."""
    import hydromodpy as hmp
    from hydromodpy.cli.banner import print_hydromodpy
    from hydromodpy.project.dispatch.workflow import dispatch_workflow
    from hydromodpy.project.launch.env import LAUNCHED_ENV
    from hydromodpy.workflow.dispatch import WorkflowError, resolve_workflow

    run_path = effective_path or config_path

    # Before the first line is printed: the banner and every step below obey
    # the level this resolves.
    verbosity = apply_verbosity(args, raw_toml)

    if verbosity != "quiet":
        print_hydromodpy()

    if profile_output is None:
        profile_output = resolve_profile_output(profile_arg_from_toml(raw_toml), config_path)

    dry_run = bool(getattr(args, "dry_run", False))
    from hydromodpy.config.sites import is_sites_project

    if is_sites_project(raw_toml):
        cleanup_effective_toml(effective_path, source=config_path)
        if not dry_run:
            _launch_sites_project(config_path, args=args)
            return
        _print_sites_dry_run(config_path, args=args)
        return

    try:
        _check_single_site(run_path, raw_toml)
    except ValidationError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    except ConfigError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)

    try:
        workflow = resolve_workflow(run_path, cli_workflow=None)
    except WorkflowError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)

    resume = getattr(args, "resume", None)
    resume_ref = resume
    if resume == "":
        resume = resolve_case_name(getattr(args, "case", None), raw_toml, config_path)
    from_step = getattr(args, "from_step", None)
    until_step = getattr(args, "until_step", None)
    no_display = bool(getattr(args, "no_display", False))
    frozen = bool(getattr(args, "frozen", False))
    force = bool(getattr(args, "force", False))
    fresh = bool(getattr(args, "fresh", False))
    case_name = resolve_case_name(getattr(args, "case", None), raw_toml, config_path)

    if dry_run:
        if profile_output is not None:
            print("[dry-run] --profile ignored (nothing is executed)", file=sys.stderr)
        if workflow == "calibration":
            from hydromodpy.calibration.preflight import preflight_launch

            try:
                preflight_launch(run_path)
            except ConfigError as exc:
                refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
        plan = _dry_run_plan(
            workflow,
            config_path,
            raw_toml,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
        )
        emit(
            args,
            "run",
            {"workflow": workflow, "config": config_path, "dry_run": True, "result": plan},
            table=lambda: _print_dry_run(plan),
        )
        return

    steps_given = from_step is not None or until_step is not None
    refusals = (
        (
            resume is not None and workflow not in ("simulation", "calibration"),
            "--resume is only supported for the 'simulation' and 'calibration' workflows "
            f"(detected '{workflow}').",
        ),
        (
            bool(resume_ref) and workflow == "calibration",
            "A calibration reopens the latest session of the case its file names: "
            f"pass a bare --resume, not --resume {resume_ref}.",
        ),
        (
            steps_given and workflow == "calibration",
            "--from / --until are only supported for the 'simulation' workflow "
            "(detected 'calibration'). To run the first steps of this file, for "
            "example to check the soil reservoir alone, add "
            "--set workflow.mode=simulation: "
            f"hmp run {config_path.name} --until load_data --set workflow.mode=simulation",
        ),
        (
            steps_given and workflow != "simulation",
            "--from / --until are only supported for the "
            f"'simulation' workflow (detected '{workflow}').",
        ),
        (
            force and workflow != "simulation",
            f"--force is only supported for the 'simulation' workflow "
            f"(detected '{workflow}'), which is the only one that skips an "
            f"identical completed run.",
        ),
    )
    for refused, message in refusals:
        if refused:
            refuse(message, EXIT_CONFIG)

    project_root = _resolve_project_root(config_path)
    try:
        refuse_a_sealed_run_as_project(project_root)
    except ConfigError as exc:
        refuse(str(exc), exit_code_for(exc), cause=exc)
    if frozen:
        from hydromodpy.workflow.replay_checks import sealed_run_of

        # A project TOML answers to its lockfile. The frozen configuration of a run
        # answers to the record of that run, which the simulation dispatch checks.
        # The pre-check only reports drift. Frozen mode itself travels with
        # ``frozen=frozen`` into the simulation dispatch, which binds and
        # releases it around that one run instead of leaving the process frozen.
        if sealed_run_of(config_path) is None:
            try:
                _verify_frozen_inputs_strict(run_path, raw_toml)
            except FrozenVerificationError as exc:
                refuse(f"--frozen: {exc}", EXIT_CONFIG, cause=exc)

    try:
        with profile_run(profile_output, description=f"hmp run {config_path.name} ({workflow})"):
            if workflow == "simulation":
                # Dispatch through DISPATCH (not hmp.run) so the CLI keeps the
                # summary dict: the "identical run skipped" message and the
                # mesh-process stats. hmp.run exposes the same run as a Run
                # object for the Python API.
                summary = dispatch_workflow(
                    "simulation",
                    run_path,
                    name=case_name,
                    resume=resume,
                    from_step=from_step,
                    until_step=until_step,
                    no_display=no_display,
                    frozen=frozen,
                    force=force,
                    fresh=fresh,
                    overrides=lineage_overrides,
                    replay_of=replayed_copy,
                )
            elif workflow == "calibration" and resume is not None:
                summary = hmp.calibrate(run_path, resume=True).to_dict()
            else:
                summary = dispatch_workflow(workflow, run_path)
                if workflow == "overview":
                    summary = summary.to_dict()
    except ValidationError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    except FileNotFoundError as exc:
        refuse(f"Missing file: {exc}", EXIT_NOT_FOUND, cause=exc)
    except BaseException as exc:
        _close_dead_attempt(project_root, case_name, exc)
        raise
    finally:
        if workflow in INDEXED_WORKFLOWS and not dry_run and not os.environ.get(LAUNCHED_ENV):
            _index_after_worker(project_root)

    if getattr(args, "format", "table") != "table":
        emit(
            args,
            "run",
            {
                "workflow": workflow,
                "config": config_path,
                "dry_run": False,
                "result": _result_of(summary),
            },
        )
        if workflow == "calibration":
            exit_if_session_unfinished(summary)
        return

    if isinstance(summary, Mapping) and summary.get("skipped"):
        from hydromodpy.project.dispatch.workflow import identical_run_message

        sid = str(summary.get("sim_id") or "")
        print(identical_run_message(summary.get("name"), sid), file=sys.stderr)
        print("Re-run with --force to run it again.", file=sys.stderr)
        return

    if workflow == "simulation" and _stops_before_setup_process(until_step):
        print(HEAD_ONLY_MESSAGE, file=sys.stderr)
        return

    # A simulation has already said its name, its id and its duration through
    # the run epilogue. Repeating it, plus the full uuid, is what made the end
    # of a run three screens of the same fact; the recap stays for the other
    # workflows, which have no epilogue of their own, and for --verbose.
    if workflow == "simulation" and verbosity in ("quiet", "normal"):
        return
    # An overview ends on what a reader opens next, not on the list of every
    # PNG it wrote; --verbose keeps the full recap.
    if workflow == "overview" and verbosity in ("quiet", "normal"):
        if verbosity == "normal" and isinstance(summary, Mapping):
            _print_overview_recap(summary)
        return
    # A calibration ends on what it found and where to read it, one line per
    # phase; the full dict of phases, protocol and deviations is --verbose.
    if workflow == "calibration" and verbosity in ("quiet", "normal"):
        if verbosity == "normal" and isinstance(summary, Mapping):
            _print_calibration_recap(summary, config_path)
        exit_if_session_unfinished(summary)
        return

    print(f"Workflow '{workflow}' complete: {config_path.name}", file=sys.stderr)
    if summary is None:
        return
    if isinstance(summary, Mapping):
        items: Iterable[tuple[str, Any]] = summary.items()
    else:
        items = ((k, getattr(summary, k, None)) for k in ("sim_id", "name"))
    for key, value in items:
        if value is None:
            continue
        print(f"  {key}: {value}", file=sys.stderr)
    if workflow == "calibration":
        exit_if_session_unfinished(summary)


def _print_overview_recap(summary: Mapping[str, Any]) -> None:
    """Name the catchment, then the web page and the figures folder."""
    head = f"Overview of {summary.get('name') or 'the catchment'} ready"
    area = summary.get("catchment_area_km2")
    if area is not None:
        head += f" ({float(area):.1f} km²)"
    print(head, file=sys.stderr)
    if summary.get("web_report"):
        print(f"  Report:  {display_path(summary['web_report'])}", file=sys.stderr)
    figures = summary.get("report_paths") or []
    if figures:
        folder = display_path(Path(figures[0]).parent)
        print(f"  Figures: {folder}/ ({len(figures)})", file=sys.stderr)


def _print_calibration_recap(summary: Mapping[str, Any], config_path: Path) -> None:
    """Name the file and its protocol, then each phase as ``hmp calibrate`` prints it.

    A single-phase summary is read as one phase. The lines of a phase are the
    ones of :func:`~hydromodpy.calibration.runners.recap.result_lines`.
    """
    from hydromodpy.calibration.runners.recap import result_lines
    from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

    phases = summary.get("phases")
    if not isinstance(phases, list):
        phases = [{"phase": None, "index": 0, "report": summary}]
    head = f"Calibration {config_path.name} done"
    protocol = summary.get("protocol")
    if isinstance(protocol, Mapping) and protocol.get("name"):
        head += f": protocol {protocol['name']} {protocol.get('version') or ''}".rstrip()
    print(head, file=sys.stderr)

    figures: list[str] = []
    sessions: list[str] = []
    for position, phase in enumerate(phases):
        report = phase.get("report") or {}
        extra = report.get("extra") or {}
        title = f"{int(phase.get('index', position)) + 1}"
        if phase.get("phase"):
            title += f" {phase['phase']}"
        parts = [f"{report.get('method')}, {int(report.get('n_trials') or 0)} runs"]
        if extra.get("reused_from_disk"):
            parts.append("reused from a previous session")
        if extra.get("promotion_failures"):
            parts.append("promotion failed")
        print(f"  {title}: " + ", ".join(parts), file=sys.stderr)
        # The dict form of the uncertainty has no methods, the intervals in extra say the same.
        fields = {key: value for key, value in report.items() if key != "parameter_uncertainty"}
        for line in result_lines(SimpleNamespace(**fields)):
            print(f"  {line}", file=sys.stderr)
        workspace = report.get("workspace")
        if report.get("best_rel_dir") and workspace:
            run_dir = Path(workspace) / report["best_rel_dir"]
            figures.append(display_path(run_dir / RUN_FIGURES_DIRNAME))
        if report.get("session_dir"):
            sessions.append(display_path(report["session_dir"]))

    if figures:
        print(f"  Best runs: {', '.join(figures)}", file=sys.stderr)
    if sessions:
        label = "Sessions:" if len(sessions) > 1 else "Session: "
        print(f"  {label} {', '.join(sessions)}", file=sys.stderr)
    if summary.get("methods_path"):
        print(f"  Methods:   {display_path(summary['methods_path'])}", file=sys.stderr)


class FrozenVerificationError(ConfigError, RuntimeError):
    """Raised when ``--frozen`` finds a lockfile drift before running anything."""


def _result_of(summary: Any) -> Any:
    """Return what a workflow gave as what a program reads: a mapping, or nothing."""
    if summary is None or isinstance(summary, Mapping):
        return summary
    if hasattr(summary, "to_dict"):
        return summary.to_dict()
    return {key: getattr(summary, key, None) for key in ("sim_id", "name")}


def _verify_frozen_inputs_strict(config_path: Path, raw_toml: dict[str, Any]) -> Path:
    """Verify the project lockfile before launching a ``--frozen`` run of a project TOML.

    Resolves the same project root as the lockfile writer, opens the data
    cache read-only, and calls
    :func:`hydromodpy.data.registry.freeze.verify_inputs_strict` against the
    project's ``hydromodpy.lock``. Any mismatch aborts the run. Returns the
    project root it verified, so a caller can assert it is the address the
    post-run write uses.
    """
    from hydromodpy.data.provenance.lockfile import project_lockfile_path
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.data.registry.freeze import verify_inputs_strict

    workspace_payload = raw_toml.get("workspace") if isinstance(raw_toml, dict) else None
    project_root = _resolve_project_root(config_path)

    lockfile_path = project_lockfile_path(project_root)
    if not lockfile_path.is_file():
        raise FrozenVerificationError(
            f"hydromodpy.lock not found at {lockfile_path}; --frozen on a project TOML reads "
            "that file: write it with `hmp lock update`, or replay the config.toml of a run, "
            "which carries its own record."
        )

    data_dir = _resolve_workspace_data_dir(workspace_payload, project_root)
    db_path = data_cache_path_for(data_dir)
    if not db_path.is_file():
        raise FrozenVerificationError(
            f"Data cache not found at {db_path}; --frozen requires a populated workspace."
        )

    try:
        with DataCatalogDuckDB(db_path, read_only=True) as catalog:
            mismatches = verify_inputs_strict(catalog, lockfile_path)
    except Exception as exc:  # noqa: BLE001 - any catalog error aborts the run
        raise FrozenVerificationError(f"Could not verify lockfile {lockfile_path}: {exc}") from exc
    if mismatches:
        first = mismatches[0]
        raise FrozenVerificationError(
            f"{len(mismatches)} lockfile mismatch(es); first: "
            f"{first.kind} on {first.path} (variable={first.variable})"
        )
    return project_root


def _close_dead_attempt(project_root: Path, case_name: str, exc: BaseException) -> None:
    """Write ``failed`` for the attempt of this process when it died without writing its outcome.

    The worker of ``hmp run`` is this very process, so only an outcome that
    names this host and this pid is closed: a run another worker holds, which
    refused our claim, is left exactly as it is.
    """
    import socket

    from hydromodpy.results.storage.attempt import (
        finish_dead_attempt,
        latest_version_dir,
        signal_of,
    )
    from hydromodpy.results.storage.run_log import read_log_tail

    run_dir = latest_version_dir(project_root, case_name)
    if run_dir is None:
        return
    finish_dead_attempt(
        run_dir,
        host=socket.gethostname(),
        pid=os.getpid(),
        exit_code=exit_code_for(exc),
        signal=signal_of(exc),
        log_tail=read_log_tail(run_dir),
        written_by="launcher",
    )


def _index_after_worker(project_root: Path) -> None:
    """Refresh the index of the project from its run directories, after the worker."""
    from hydromodpy.core.state.layout import runs_dir_for
    from hydromodpy.results.catalog.indexer import index_new_runs

    if not runs_dir_for(project_root).is_dir():
        return
    try:
        index_new_runs(project_root)
    except Exception as exc:  # noqa: BLE001 - the run is on disk; the index is derived
        logger.warning("Index not refreshed after the run: %s", exc)


def _resolve_project_root(config_path: Path) -> Path:
    """Return the project root of this config.

    Same rule as :meth:`HydroModPyConfig.from_toml`: ``HMP_PROJECT_ROOT``
    first, then the folder holding ``project.toml`` above the file, else the
    folder of the root file of its ``base_config`` chain. ``[workspace]
    project_root`` is refused in a file, so the file never names it.
    """
    from hydromodpy.core.toml_io.loader import config_base_dir

    env_root = os.environ.get("HMP_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return resolve_project_root(config_base_dir(config_path))


def _resolve_workspace_data_dir(
    workspace_payload: dict[str, Any] | None,
    project_root: Path,
) -> Path:
    """Return the workspace ``data/`` directory used for the lockfile."""
    if isinstance(workspace_payload, dict):
        explicit_data = workspace_payload.get("data_dir")
        if explicit_data:
            data = Path(explicit_data).expanduser()
            if not data.is_absolute():
                data = (project_root / data).resolve()
            return data
        explicit_root = workspace_payload.get("root")
        if explicit_root:
            root = Path(explicit_root).expanduser()
            if not root.is_absolute():
                root = (project_root / root).resolve()
            return root / "data"

    env_root = os.environ.get("HMP_WORKSPACE")
    if env_root:
        return Path(env_root).expanduser().resolve() / "data"

    if project_root.parent.name == "projects":
        candidate = project_root.parent.parent
        if (candidate / "data").is_dir():
            return candidate / "data"
    return project_root / "data"


def _print_sites_dry_run(config_path: Path, *, args: argparse.Namespace) -> None:
    """Print the plan of a ``[sites]`` project and its grouped issues; write nothing."""
    from hydromodpy.project.launch.sites.budget import dry_run_lines, plan_budget
    from hydromodpy.project.launch.sites.expansion import expand_plan
    from hydromodpy.project.launch.sites.issues import group_issues

    try:
        cli_payload = set_overrides(list(getattr(args, "set_overrides", []) or []))
        draft = expand_plan(
            resolve_project_root(config_path.parent),
            config_path,
            set_overrides=cli_payload,
            env=os.environ,
        )
    except (ConfigError, ValueError) as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    lines = dry_run_lines(draft, plan_budget(draft))
    warnings = group_issues(draft.warnings)
    errors = [] if draft.ok else group_issues(draft.errors)
    for line in warnings:
        print(f"[dry-run] warning : {line}", file=sys.stderr)
    for line in errors:
        print(f"[dry-run] error   : {line}", file=sys.stderr)

    def table() -> None:
        for line in lines:
            print(line)

    emit(
        args,
        "run",
        {
            "workflow": "sites",
            "config": config_path,
            "dry_run": True,
            "result": {"lines": list(lines), "warnings": list(warnings), "errors": list(errors)},
        },
        table=table,
    )
    if not draft.ok:
        sys.exit(EXIT_CONFIG)


def _launch_sites_project(config_path: Path, *, args: argparse.Namespace) -> None:
    """Plan a ``[sites]`` project from *config_path*, then launch its current plan."""
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.project.launch import plan_project, run_plan

    resume = getattr(args, "resume", None)
    if resume:
        refuse(
            f"--resume {resume}: on a [sites] project --resume takes no case name; name the "
            "case with --only and pass a bare --resume.",
            EXIT_USAGE,
        )
    force = bool(getattr(args, "force", False))
    root = resolve_project_root(config_path.parent)
    try:
        plan_project(
            root,
            config_path=config_path,
            set_overrides=set_overrides(list(getattr(args, "set_overrides", []) or [])),
            env=os.environ,
            force=force,
        )
        report = run_plan(
            root,
            parallel=getattr(args, "parallel", None),
            only=tuple(getattr(args, "only", []) or ()),
            site=getattr(args, "site", None),
            until=getattr(args, "until_step", None),
            fresh=bool(getattr(args, "fresh", False)),
            force=force,
            resume=resume is not None,
        )
    except KeyboardInterrupt:
        print("Launch aborted by user.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)
    except (HydroModPyError, ValueError) as exc:
        fail(exc)

    def table() -> None:
        if report.until is not None:
            print(
                f"[launch] plan {report.plan_hash}: {len(report.prepared)} case(s) prepared, "
                f"{report.n_failed} failed to prepare; stopped after the prepare phase"
            )
        else:
            print(
                f"[launch] plan {report.plan_hash}: {len(report.cases)} case(s) started, "
                f"{report.n_completed} completed, {report.n_failed} not completed"
            )
        print(f"[launch] journal: {display_path(report.journal)}")

    for case in report.cases:
        if case.status != "completed":
            detail = f" ({case.error})" if case.error else ""
            print(f"[launch]   {case.case_id}: {case.status}{detail}", file=sys.stderr)
    emit(
        args,
        "run",
        {
            "workflow": "sites",
            "config": config_path,
            "dry_run": False,
            "result": {
                "plan_hash": report.plan_hash,
                "until": report.until,
                "n_prepared": len(report.prepared),
                "n_completed": report.n_completed,
                "n_failed": report.n_failed,
                "cases": [
                    {"case_id": case.case_id, "status": case.status, "error": case.error}
                    for case in report.cases
                ],
                "journal": report.journal,
            },
        },
        table=table,
    )
    if report.n_failed:
        sys.exit(EXIT_CASES_FAILED)


def _check_single_site(config_path: Path, raw_toml: Mapping[str, Any]) -> None:
    """Refuse a ``[site]`` the workspace site catalog knows as another catchment.

    Raises :class:`~hydromodpy.data.sites.single_site.SiteMismatchError`.
    A file without ``[site]``, or a workspace without a catalog, passes.
    """
    if "site" not in raw_toml:
        return
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.data.sites.single_site import resolve_single_site

    cfg = HydroModPyConfig.from_toml(config_path)
    workspace_root = getattr(cfg.workspace, "root", None)
    if workspace_root is None:
        return
    resolve_single_site(cfg, workspace_root)


def _dry_run_plan(
    workflow: str,
    config_path: Path,
    raw_toml: dict,
    *,
    resume: str | None,
    from_step: str | None,
    until_step: str | None,
) -> dict[str, Any]:
    """Return the resolved workflow plan, without executing it."""
    steps: list[str] = []
    if workflow == "simulation":
        from hydromodpy.workflow.steps.sequence import standard_steps

        steps = [type(step).__name__ for step in standard_steps()]
    return {
        "workflow": workflow,
        "config": str(config_path),
        "sections": sorted(raw_toml),
        "resume": resume,
        "from": from_step,
        "until": until_step,
        "steps": steps,
    }


def _print_dry_run(plan: Mapping[str, Any]) -> None:
    """Print the plan, one fact per line."""
    print(f"[dry-run] workflow: {plan['workflow']}")
    print(f"[dry-run] config  : {plan['config']}")
    print(f"[dry-run] sections: {', '.join(plan['sections'])}")
    for label, key in (("resume  ", "resume"), ("from    ", "from"), ("until   ", "until")):
        if plan[key] is not None:
            print(f"[dry-run] {label}: {plan[key]}")
    if plan["steps"]:
        print("[dry-run] steps   :")
        for i, step in enumerate(plan["steps"]):
            print(f"  {i:02d}  {step}")
