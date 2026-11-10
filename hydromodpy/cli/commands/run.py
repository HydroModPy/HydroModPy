"""``hmp run`` - execute the workflow of a TOML file or of a JSON run request.

Single CLI entry point. The file names its workflow with ``[workflow] mode``
(``simulation``, ``calibration`` or ``overview``) or leaves it to its sections
(:func:`hydromodpy.project.request.workflow_of`). A ``.json`` file is a run
request, the serialized form of :class:`~hydromodpy.project.request.RunRequest`,
and a Docker image runs it with the same command.

Overrides are merged as defaults < base_config < --overlay < --set < env. A run
launched with ``--set`` or ``--overlay`` keeps its name: the surcharge is sealed
in ``lineage.overrides`` and ``.vN`` handles the collision. Nothing is written
beside the file the user named: the changes ride in the request.

The relative paths of a request are read from its base: the project root above a
file, or the folder ``--base`` names, or the project ``-w`` names.

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
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from hydromodpy.cli.conventions import (
    format_parser,
    profile_parser,
    verbosity_parser,
    workspace_parser,
)
from hydromodpy.cli.helpers import (
    EXIT_CASES_FAILED,
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    EXIT_USAGE,
    add_override_arguments,
    apply_verbosity,
    base_named_by_w,
    changes_of_args,
    exit_code_for,
    exit_if_session_unfinished,
    fail,
    profile_arg_from_toml,
    profile_run,
    refuse,
    resolve_profile_output,
    with_changes,
)
from hydromodpy.cli.output import emit
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.portable import display_path
from hydromodpy.core.state.result_dirs import refuse_a_sealed_run_as_project, resolve_project_root
from hydromodpy.core.toml_io.overrides import set_overrides

if TYPE_CHECKING:
    from hydromodpy.project.request import RunOutcome, RunRequest

logger = get_logger(__name__)

NAME: str = "run"
HELP: str = "Run a workflow from a TOML config or a JSON run request"

REQUEST_SUFFIXES = (".toml", ".json")
"""The files ``hmp run`` reads: a TOML configuration, or a JSON run request."""

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
    from hydromodpy.cli.environment import add_environment_arguments

    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=[format_parser(), profile_parser(), verbosity_parser(), workspace_parser()],
        epilog="Examples:\n  hmp run run.toml\n  hmp run run.toml --dry-run\n  hmp run run.toml --set flow.param.K.field.value=2e-5\n  hmp run run.toml --overlay daily.toml --case baseline_daily\n  hmp run run.toml --from setup_process --until run_solver\n  hmp run --resume baseline_monthly\n  hmp run run.toml --fresh\n  hmp run request.json --base /project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_arg = parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=None,
        help="Path to a TOML config or to a JSON run request (omit when using --resume REF)",
    )
    parser.add_argument(
        "--base",
        default=None,
        metavar="DIR",
        help=(
            "The folder the relative paths of the configuration are read from, and the "
            "project the run is written in. It wins over -w and over the project root above "
            "the file."
        ),
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

        config_arg.completer = FilesCompleter(("toml", "json"))
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
            "On a project TOML, reject any fresh download: every file must already be "
            "in the data cache and match hydromodpy.lock. The config.toml of a sealed run "
            "is refused: hmp replay plays a run again."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Go past what the command refuses because of what is there: recompute when a "
            "completed run with an identical resolved config and the same name already "
            "exists, and claim a stale case whose process cannot be proven dead. Without it "
            "an identical run is not recomputed: the command stops and names it. A "
            "calibration searches again instead of giving back its completed session. Not "
            "for an overview. On a [sites] project it also lifts the budget ceilings (parallel, "
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
    add_environment_arguments(parser)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.cli.environment import environment_from_args
    from hydromodpy.project.launch.env import apply_thread_budget

    try:
        apply_thread_budget()
    except ValueError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    environment = environment_from_args(args)
    base = _base_of_args(args)
    config = getattr(args, "config", None)
    if config is None:
        resume = getattr(args, "resume", None)
        if not resume:
            refuse("Provide a TOML config, or --resume REF to resume a catalog run.", EXIT_CONFIG)
        _resume_from_ref(str(resume), args=args, base=base)
        return

    target = Path(config).expanduser().resolve()
    if not target.is_file():
        refuse(f"File not found: {target}", EXIT_NOT_FOUND)

    if target.suffix in REQUEST_SUFFIXES:
        _run_toml(target, args=args, environment=environment, base=base)
    elif target.suffix == ".py":
        refuse(
            "Python scripts are not supported by 'hmp run'. Run the script with python directly.",
            EXIT_CONFIG,
        )
    else:
        refuse(f"Unsupported file type: {target.suffix} (expected .toml or .json)", EXIT_CONFIG)


def _base_of_args(args: argparse.Namespace) -> Path | None:
    """Return the base the command names: ``--base``, else the project ``-w`` names, else ``None``.

    ``None`` leaves the base to the file: the project root above it.
    """
    named = getattr(args, "base", None)
    if named:
        folder = Path(named).expanduser().resolve()
        if not folder.is_dir():
            refuse(f"--base is not a folder: {folder}", EXIT_NOT_FOUND)
        return folder
    return base_named_by_w(getattr(args, "workspace", None))


def _resume_from_ref(ref: str, *, args: argparse.Namespace, base: Path | None = None) -> None:
    """Continue an interrupted case from the config frozen in its own run directory.

    Resolves REF as a case name under ``runs/`` of the project ``-w`` names, else
    the one around the current directory (``baseline`` is its latest version,
    ``baseline.v2`` that one) and replays ``runs/<name>/config.toml`` - the resolved configuration
    the run was executed with - through the same path as
    ``hmp run config.toml --resume NAME``.
    """
    from hydromodpy.cli.environment import environment_from_args
    from hydromodpy.results.record.manifest import is_sealed, read_seal
    from hydromodpy.results.storage.attempt import run_dir_for_name
    from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME

    workspace = base if base is not None else resolve_project_root(Path.cwd().resolve())
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
    # The resume branch reads the same three Environment options the operator
    # named on the command line; None keeps the default of the machine.
    _run_toml(config_path, args=args, environment=environment_from_args(args), base=base)


def _request_of(
    config_path: Path,
    *,
    args: argparse.Namespace,
    base: Path | None,
    changes: Mapping[str, Any],
) -> RunRequest:
    """Return the request of ``config_path`` and the options of the command, or stop.

    The file is read once, with its chain and its overlays. A ``.json`` file is
    the request itself, and the options of the command add to it. The options a
    workflow refuses are checked later, once a ``[sites]`` project is told apart
    (:func:`_checked`).
    """
    from hydromodpy.project.request import request_of

    try:
        return request_of(
            config_path,
            base=base,
            overlays=getattr(args, "overlay", None) or (),
            set=changes,
            name=getattr(args, "case", None),
            resume=getattr(args, "resume", None),
            from_step=getattr(args, "from_step", None),
            until_step=getattr(args, "until_step", None),
            force=bool(getattr(args, "force", False)),
            fresh=bool(getattr(args, "fresh", False)),
            frozen=bool(getattr(args, "frozen", False)),
            dry_run=True,
            no_display=bool(getattr(args, "no_display", False)),
        )
    except ConfigError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)
    except FileNotFoundError as exc:
        refuse(f"Missing file: {exc}", EXIT_NOT_FOUND, cause=exc)
    except ValueError as exc:
        refuse(f"Invalid override: {exc}", EXIT_CONFIG, cause=exc)


def _refuse_frozen_replay(config_path: Path) -> None:
    """Refuse ``--frozen`` on the configuration of a sealed run or a published copy.

    A run or a copy is played again by ``hmp replay``, which pins its inputs at
    the digests of its record and classes the values it computes. ``--frozen``
    keeps its lockfile sense on a project file.
    """
    from hydromodpy.project.exchange.replay import published_copy_of
    from hydromodpy.workflow.replay_checks import sealed_run_of

    source = published_copy_of(config_path) or sealed_run_of(config_path)
    if source is None:
        return
    shown = display_path(source)
    refuse(
        f"--frozen does not play a run again. {shown} is a sealed run or a published "
        f"copy: run 'hmp replay {shown}'.",
        EXIT_CONFIG,
    )


def _run_toml(
    config_path: Path,
    *,
    args: argparse.Namespace,
    environment=None,
    base: Path | None = None,
) -> None:
    """Run a workflow from a TOML file or from a JSON run request.

    The workflow is the declared ``[workflow] mode`` or the one the sections
    imply; a retired mode exits with ``EXIT_CONFIG`` and names its replacement.
    ``--frozen`` of the configuration of a sealed run or of a published copy is
    refused, and names ``hmp replay``: a run is played again by its own verb.
    *base* is the folder the relative paths are read from, when the command
    names one.
    """
    if getattr(args, "frozen", False) and not getattr(args, "resume", None):
        _refuse_frozen_replay(config_path)

    profile_output = resolve_profile_output(getattr(args, "profile", None), config_path)

    from hydromodpy.project.launch.sites.plan import refuse_env_overrides

    refuse_env_overrides(os.environ, config_path)
    try:
        changes = changes_of_args(args, os.environ)
    except ValueError as exc:
        refuse(f"Invalid override: {exc}", EXIT_CONFIG, cause=exc)

    request = _request_of(config_path, args=args, base=base, changes=changes)
    _run_request(
        config_path,
        request,
        args=args,
        profile_output=profile_output,
        environment=environment,
        base=base,
    )


def _checked(request: RunRequest, config_path: Path) -> None:
    """Stop when the options of *request* do not go with its workflow.

    The request is read before the workflow is told, and a ``[sites]`` project
    takes the options its launcher reads whatever its sections imply. A run then
    asks the request of its own document the same question
    :func:`~hydromodpy.project.request.request_of` asks of a file, which refuses
    ``--from`` on a calibration or ``--force`` on an overview with the words of
    ``hmp run``.
    """
    from hydromodpy.project.request import request_of

    try:
        request_of(
            request.config,
            set=request.set,
            name=request.name,
            resume=request.resume,
            from_step=request.from_step,
            until_step=request.until_step,
            force=request.force,
            fresh=request.fresh,
            frozen=request.frozen,
            no_display=request.no_display,
            phase=request.phase,
        )
    except ConfigError as exc:
        # The refusal names the file the user typed, not a document in memory.
        refuse(str(exc).replace("hmp run <file>", f"hmp run {config_path.name}"), EXIT_CONFIG)


def _run_request(
    config_path: Path,
    request: RunRequest,
    *,
    args: argparse.Namespace,
    profile_output: Path | None,
    environment=None,
    base: Path | None = None,
) -> None:
    """Run the workflow of *request*, read from *config_path*, and say what came out."""
    from hydromodpy.cli.banner import print_hydromodpy
    from hydromodpy.config.sites import is_sites_project
    from hydromodpy.project.launch.env import LAUNCHED_ENV
    from hydromodpy.project.request import base_of, workflow_of
    from hydromodpy.workflow.dispatch import WorkflowError

    raw_toml = with_changes(request.config, request.set)
    dry_run = bool(getattr(args, "dry_run", False))

    # Before the first line is printed: the banner and every step below obey
    # the level this resolves.
    verbosity = apply_verbosity(args, raw_toml)

    if verbosity != "quiet":
        print_hydromodpy()

    if profile_output is None:
        profile_output = resolve_profile_output(profile_arg_from_toml(raw_toml), config_path)

    if is_sites_project(raw_toml):
        if config_path.suffix != ".toml":
            refuse(
                f"{config_path.name} is a run request, and a [sites] project is planned from "
                "its TOML files: run its project.toml.",
                EXIT_CONFIG,
            )
        if not dry_run:
            _launch_sites_project(config_path, args=args, environment=environment)
            return
        _print_sites_dry_run(config_path, args=args)
        return

    run_base = base_of(config_path, base)
    project_root = resolve_project_root(run_base)
    try:
        _check_single_site(config_path, raw_toml, request=request, base=run_base)
    except ValidationError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    except ConfigError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)

    try:
        workflow = workflow_of(request)
    except WorkflowError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)

    resume = request.resume
    if resume == "":
        resume = _case_name(request, raw_toml, config_path)
    until_step = request.until_step

    if dry_run:
        if profile_output is not None:
            print("[dry-run] --profile ignored (nothing is executed)", file=sys.stderr)
        if workflow == "calibration":
            from hydromodpy.calibration.preflight import preflight_launch

            try:
                if _held_in_memory(request):
                    preflight_launch(config_path, config=_config_of(request, config_path, run_base))
                else:
                    preflight_launch(config_path)
            except ConfigError as exc:
                refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
        plan = _dry_run_plan(
            workflow,
            config_path,
            raw_toml,
            resume=resume,
            from_step=request.from_step,
            until_step=until_step,
        )
        emit(
            args,
            "run",
            {"workflow": workflow, "config": config_path, "dry_run": True, "result": plan},
            table=lambda: _print_dry_run(plan),
        )
        return

    _checked(request, config_path)
    # The request was read as a draft, so no option was refused before the sites were told
    # apart. The run it asks for is no dry run: it is the one request.json will say.
    request = request.model_copy(update={"dry_run": False})
    try:
        refuse_a_sealed_run_as_project(project_root)
    except ConfigError as exc:
        refuse(str(exc), exit_code_for(exc), cause=exc)
    if request.frozen:
        from hydromodpy.workflow.replay_checks import sealed_run_of

        # A project TOML answers to its lockfile. The configuration of a sealed run
        # reaches this point only under --resume, which reads the record of that
        # run, so no lockfile is read for it. Frozen mode itself travels with
        # ``frozen=frozen`` into the simulation dispatch, which binds and
        # releases it around that one run instead of leaving the process frozen.
        if sealed_run_of(config_path) is None:
            try:
                _verify_frozen_inputs_strict(config_path, raw_toml, project_root=project_root)
            except FrozenVerificationError as exc:
                refuse(f"--frozen: {exc}", EXIT_CONFIG, cause=exc)

    try:
        with profile_run(profile_output, description=f"hmp run {config_path.name} ({workflow})"):
            if workflow == "simulation":
                from hydromodpy.project.dispatch.workflow import run_simulation

                # The command keeps the outcome of the run: the "identical run
                # skipped" message and the name of the run it gave back.
                # hmp.run exposes the same run as a Run object for the Python API.
                summary = _summary_of(
                    run_simulation(request, base=run_base, environment=environment)
                )
            else:
                from hydromodpy.project.dispatch.workflow import dispatch_workflow

                summary = dispatch_workflow(
                    workflow, request, base=run_base, environment=environment
                )
                if workflow == "overview":
                    summary = summary.to_dict()
    except ValidationError as exc:
        refuse(f"Config invalid: {exc}", EXIT_CONFIG, cause=exc)
    except FileNotFoundError as exc:
        refuse(f"Missing file: {exc}", EXIT_NOT_FOUND, cause=exc)
    except BaseException as exc:
        _close_dead_attempt(project_root, exc)
        raise
    finally:
        if workflow in INDEXED_WORKFLOWS and not os.environ.get(LAUNCHED_ENV):
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

    identical = _identical_of(summary)
    if identical is not None:
        from hydromodpy.project.dispatch.workflow import identical_run_message

        print(identical_run_message(*identical), file=sys.stderr)
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


def _case_name(request: RunRequest, raw_toml: Mapping[str, Any], config_path: Path) -> str:
    """Return the name of the run: ``--case``, else ``[simulation] name``, else the file's.

    The name of the file is the one a run of it takes, folded from its stem, so a
    bare ``--resume`` names the run the file made.
    """
    from hydromodpy.config.hydromodpy_config import run_name_of_file

    if request.name:
        return request.name
    simulation = raw_toml.get("simulation") if isinstance(raw_toml, Mapping) else None
    declared = simulation.get("name") if isinstance(simulation, Mapping) else None
    return str(declared) if declared else run_name_of_file(config_path)


def _identical_of(summary: Any) -> tuple[str | None, str] | None:
    """Return the name and the id of the completed work *summary* gave back, or None.

    A simulation says it by ``skipped``. A calibration gives back the report of the
    session, whose ``extra.identical_to`` names the session folder.
    """
    if not isinstance(summary, Mapping):
        return None
    if summary.get("skipped"):
        return summary.get("name"), str(summary.get("sim_id") or "")
    extra = summary.get("extra")
    folder = extra.get("identical_to") if isinstance(extra, Mapping) else None
    if folder:
        return str(folder), str(summary.get("session_id") or "")
    return None


def _summary_of(outcome: RunOutcome | None) -> dict[str, Any]:
    """Return what the command says of the outcome of a simulation, as a mapping.

    A run given back for an identical completed one is told by ``skipped``, with the
    name and the id of the run it gave back. A window that keeps no run is empty.
    """
    if outcome is None:
        return {}
    summary: dict[str, Any] = {
        "name": outcome.identical_to or outcome.name,
        "sim_id": outcome.sim_id,
        "project_root": str(outcome.project_root),
        "run_dir": str(outcome.run_dir),
        "status": outcome.status,
    }
    if outcome.identical_to is not None:
        summary["skipped"] = True
    # A run that built a mesh says it, key by key, as the --verbose recap and --json show.
    summary.update(outcome.mesh_summary or {})
    return summary


def _held_in_memory(request: RunRequest) -> bool:
    """Whether the calibration of *request* runs on a configuration held in memory.

    A plain TOML file reaches the runners by its path. A request in JSON and a file
    changed by ``--set`` or ``--overlay`` are loaded against their base and run
    as a project held in memory, as :func:`~hydromodpy.project.dispatch.workflow.run_calibration`
    runs them.
    """
    return bool(request.form != "toml" or request.set or request.overlays)


def _config_of(request: RunRequest, config_path: Path, run_base: Path) -> Any:
    """Return the configuration *request* asks for, validated against its base."""
    from hydromodpy.config.loading import load

    return load(
        request.config,
        run_base,
        changes=request.set,
        source_path=config_path if config_path.suffix == ".toml" else None,
    )


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


def _verify_frozen_inputs_strict(
    config_path: Path, raw_toml: dict[str, Any], *, project_root: Path | None = None
) -> Path:
    """Verify the project lockfile before launching a ``--frozen`` run of a project TOML.

    Resolves the same project root as the lockfile writer and the data folder
    that :class:`~hydromodpy.core.workspace.config.WorkspaceConfig` resolves, then
    calls :func:`hydromodpy.data.provenance.lockfile.verify_lockfile` in strict
    mode against the project's ``hydromodpy.lock``. Any mismatch aborts the run.
    Returns the project root it verified, so a caller can assert it is the
    address the post-run write uses.
    """
    from hydromodpy.core.toml_io.paths import resolve_declared_path
    from hydromodpy.core.workspace.config import WorkspaceConfig
    from hydromodpy.data.provenance.lockfile import project_lockfile_path, verify_lockfile

    workspace_payload = raw_toml.get("workspace") if isinstance(raw_toml, dict) else None
    if project_root is None:
        project_root = _resolve_project_root(config_path)

    lockfile_path = project_lockfile_path(project_root)
    if not lockfile_path.is_file():
        raise FrozenVerificationError(
            f"hydromodpy.lock not found at {lockfile_path}; --frozen on a project TOML reads "
            "that file: write it with `hmp data lock`, or play a sealed run again with "
            "`hmp replay REF`."
        )

    declared = {
        key: str(resolve_declared_path(workspace_payload[key], base_dir=project_root))
        for key in ("root", "data_dir")
        if isinstance(workspace_payload, dict) and workspace_payload.get(key)
    }
    try:
        data_dir = WorkspaceConfig.model_validate(
            {**declared, "project_root": str(project_root)}
        ).data_dir
        mismatches = verify_lockfile(
            data_dir, lockfile_path, project_root=project_root, strict=True
        )
    except Exception as exc:  # noqa: BLE001 - any lockfile or data folder error aborts the run
        raise FrozenVerificationError(f"Could not verify lockfile {lockfile_path}: {exc}") from exc
    if mismatches:
        first = mismatches[0]
        raise FrozenVerificationError(
            f"{len(mismatches)} lockfile mismatch(es); first: "
            f"{first.kind} on {first.path} (variable={first.variable})"
        )
    return project_root


def _close_dead_attempt(project_root: Path, exc: BaseException) -> None:
    """Write ``failed`` for the attempt of this process when it died without writing its outcome.

    The worker of ``hmp run`` is this very process, so only an outcome that
    names this host and this pid is closed: a run another worker holds, which
    refused our claim, is left exactly as it is. The run is found by that
    claim, never by the name the command guessed.
    """
    import socket

    from hydromodpy.core.state.layout import runs_dir_for
    from hydromodpy.results.outcome import read_outcome
    from hydromodpy.results.storage.attempt import finish_dead_attempt, signal_of
    from hydromodpy.results.storage.json_io import readable
    from hydromodpy.results.storage.run_log import read_log_tail

    runs = runs_dir_for(project_root)
    if not runs.is_dir():
        return
    host, pid = socket.gethostname(), os.getpid()
    for run_dir in sorted(runs.iterdir()):
        # An outcome that cannot be read (corrupt, or of another schema) is not the
        # attempt of this process, and reading it must never hide the error of the run.
        outcome = readable(read_outcome, run_dir) if run_dir.is_dir() else None
        if (
            outcome is None
            or outcome.status != "running"
            or (outcome.host, outcome.pid) != (host, pid)
        ):
            continue
        finish_dead_attempt(
            run_dir,
            host=host,
            pid=pid,
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
    """Return the project root of this config when the command names no base.

    Same rule as :func:`~hydromodpy.config.loading.load`: the folder holding
    ``project.toml`` above the file, else the folder of the root file of its
    ``base_config`` chain. ``[workspace] project_root`` is refused in a file, so
    the file never names it.
    """
    from hydromodpy.core.toml_io.loader import config_base_dir

    return resolve_project_root(config_base_dir(config_path))


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


def _launch_sites_project(config_path: Path, *, args: argparse.Namespace, environment=None) -> None:
    """Plan a ``[sites]`` project from *config_path*, then launch its current plan.

    ``environment`` is the one the command built from its own options; its
    check runs before the plan is written, so a credentials file the table
    refuses stops the launch before a single case departs, and its three
    flags ride the command line of every case, the worker of a case building
    the same Environment from them.
    """
    from hydromodpy.cli.environment import environment_flags_of
    from hydromodpy.core.exceptions import HydroModPyError
    from hydromodpy.core.workspace.resolve import find_data_workspace
    from hydromodpy.project.environment import Environment
    from hydromodpy.project.launch import plan_project, run_plan

    if environment is None:
        environment = Environment.default()
    force = bool(getattr(args, "force", False))
    root = resolve_project_root(config_path.parent)
    environment.check(project_root=root, workspace_root=find_data_workspace(root) or root)
    resume = getattr(args, "resume", None)
    if resume:
        refuse(
            f"--resume {resume}: on a [sites] project --resume takes no case name; name the "
            "case with --only and pass a bare --resume.",
            EXIT_USAGE,
        )
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
            environment_flags=environment_flags_of(args),
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


def _check_single_site(
    config_path: Path, raw_toml: Mapping[str, Any], *, request: RunRequest, base: Path
) -> None:
    """Refuse a ``[site]`` the workspace site catalog knows as another catchment.

    Raises :class:`~hydromodpy.data.sites.single_site.SiteMismatchError`.
    A file without ``[site]``, or a workspace without a catalog, passes.
    """
    if "site" not in raw_toml:
        return
    from hydromodpy.config.loading import load
    from hydromodpy.data.sites.single_site import resolve_single_site

    cfg = load(
        request.config,
        base,
        changes=request.set,
        source_path=config_path if config_path.suffix == ".toml" else None,
    )
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
