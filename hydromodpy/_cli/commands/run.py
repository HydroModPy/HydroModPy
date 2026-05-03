"""``hmp run`` - execute a workflow declared by the TOML.

Single CLI entry point. The TOML must carry a top-level
``workflow = "..."`` field (one of ``simulation``, ``calibration``,
``batch``, ``overview``, ``mesh``, ``comparison``, ``testbed``). Absence
raises ``WorkflowMissingError``.

Also supports ``.py`` scripts, executed as-is in a subprocess for
prototyping (no workflow involved).
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from pathlib import Path

from hydromodpy._cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_USER_ABORT,
    auto_scan_workspace,
)

NAME = "run"
HELP = "Run a simulation (.toml) or a prototype script (.py)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "config",
        type=Path,
        help="Path to a TOML config or Python script",
    )
    parser.add_argument(
        "script_args",
        nargs="*",
        help="Extra arguments forwarded to .py scripts",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="RUN_ID",
        help="Resume a simulation from its last checkpoint.",
    )
    parser.add_argument(
        "--from",
        dest="from_step",
        default=None,
        metavar="STEP",
        help="Resume from a specific pipeline step (name or index).",
    )
    parser.add_argument(
        "--until",
        dest="until_step",
        default=None,
        metavar="STEP",
        help="Stop after the specified pipeline step (name or index).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print the resolved workflow plan without executing it.",
    )
    parser.add_argument(
        "--no-checkpoint",
        action="store_true",
        dest="no_checkpoint",
        help="Disable pipeline checkpoint persistence for this run.",
    )
    parser.add_argument(
        "--frozen",
        action="store_true",
        help=(
            "Reject any fresh download when hydromodpy.lock is present; "
            "every artefact must already be in the catalog and match its SHA-256."
        ),
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        dest="no_display",
        help="Skip auto-rendering of the figures listed in [display].figures.",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    target = Path(args.config).expanduser().resolve()
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if getattr(args, "frozen", False):
        from hydromodpy.data.lockfile import set_frozen_mode

        set_frozen_mode(True)

    if target.suffix == ".py":
        _run_script(target, getattr(args, "script_args", []))
    elif target.suffix == ".toml":
        _run_toml(target, args=args)
    else:
        print(
            f"Unsupported file type: {target.suffix} (expected .toml or .py)",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)


def _run_toml(config_path: Path, *, args: argparse.Namespace) -> None:
    """Run a workflow from a TOML file.

    The TOML MUST declare ``workflow = "..."`` at the top level - otherwise
    :class:`~hydromodpy._cli.workflows.WorkflowMissingError` is raised and
    the CLI exits with ``EXIT_CONFIG``. No implicit detection from sections.
    """
    import tomllib

    from hydromodpy._cli.workflows import (
        WorkflowError,
        load_raw_toml,
        resolve_workflow,
    )
    from hydromodpy.core.tools.display import print_hydromodpy

    print_hydromodpy()
    auto_scan_workspace(config_path)

    try:
        raw_toml = load_raw_toml(config_path)
    except tomllib.TOMLDecodeError as exc:
        print(f"Invalid TOML: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    dry_run = bool(getattr(args, "dry_run", False))
    try:
        # In --dry-run we only print the plan, so the workflow field becomes
        # advisory: infer from TOML sections when absent rather than refusing.
        workflow = resolve_workflow(
            config_path,
            cli_workflow=None,
            require_toml_field=not dry_run,
        )
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    if workflow is None:
        workflow = _infer_workflow_from_sections(raw_toml)

    resume = getattr(args, "resume", None)
    from_step = getattr(args, "from_step", None)
    until_step = getattr(args, "until_step", None)
    no_checkpoint = bool(getattr(args, "no_checkpoint", False))
    no_display = bool(getattr(args, "no_display", False))

    if dry_run:
        _print_dry_run(
            workflow,
            config_path,
            raw_toml,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            no_checkpoint=no_checkpoint,
        )
        return

    if resume is not None and workflow != "simulation":
        print(
            f"--resume is only supported for the 'simulation' workflow (detected '{workflow}').",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    if (
        from_step is not None or until_step is not None or no_checkpoint
    ) and workflow != "simulation":
        print(
            f"--from / --until / --no-checkpoint are only supported for the "
            f"'simulation' workflow (detected '{workflow}').",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    module = importlib.import_module("hydromodpy._cli.workflows")
    dispatch = {
        "simulation": module.run_simulation,
        "overview": module.run_overview,
        "mesh": module.run_mesh,
        "calibration": module.run_calibration,
        "batch": module.run_batch,
        "comparison": module.run_comparison,
        "testbed": module.run_testbed,
    }
    runner = dispatch[workflow]

    try:
        if workflow == "simulation" and (
            resume is not None or from_step is not None or until_step is not None or no_checkpoint
        ):
            summary = _run_simulation_pipeline(
                config_path,
                resume=resume,
                from_step=from_step,
                until_step=until_step,
                no_checkpoint=no_checkpoint,
                no_display=no_display,
            )
        elif workflow == "simulation":
            summary = runner(config_path, no_display=no_display)
        else:
            summary = runner(config_path)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        sys.exit(EXIT_USER_ABORT)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:
        if type(exc).__name__ == "ValidationError":
            print(f"Config invalid: {exc}", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        raise

    print(f"Workflow '{workflow}' complete: {config_path.name}", file=sys.stderr)
    if summary:
        for key, value in summary.items():
            print(f"  {key}: {value}", file=sys.stderr)


def _run_simulation_pipeline(
    config_path: Path,
    *,
    resume: str | None,
    from_step: str | None,
    until_step: str | None,
    no_checkpoint: bool,
    no_display: bool = False,
) -> dict:
    """Run the simulation workflow through the explicit Pipeline orchestrator.

    Needed to support the --from / --until / --no-checkpoint flags without
    going through the ``Simulation`` façade.
    """
    from hydromodpy._cli.workflows import run_simulation

    if from_step is None and until_step is None and not no_checkpoint:
        # Only --resume triggers the pipeline path directly.
        return run_simulation(config_path, resume=resume, no_display=no_display)

    from hydromodpy.pipeline import Pipeline, PipelineState
    from hydromodpy.pipeline.steps import standard_steps

    steps = standard_steps()
    resume_from = _resolve_step_index(from_step, steps)
    until_index = _resolve_step_index(until_step, steps)

    if until_index is not None:
        steps = tuple(steps[: until_index + 1])

    workspace = _resolve_workspace_for_run(config_path)
    run_id = resume or config_path.stem
    pipeline = Pipeline(
        steps,
        workspace=workspace,
        checkpoint=not no_checkpoint,
    )
    initial = PipelineState(
        run_id=run_id,
        data={"config_path": config_path, "skip_display": no_display},
    )
    final = pipeline.run(
        initial,
        resume_from=resume_from,
    )
    ctx = final.get("ctx")
    return {
        "run_id": run_id,
        "resumed_from": resume_from,
        "sim_id": getattr(ctx, "sim_id", None) if ctx is not None else None,
    }


def _resolve_step_index(step: str | None, steps) -> int | None:
    """Resolve a step name (or digit) to the tuple index."""
    if step is None:
        return None
    if step.isdigit():
        return int(step)
    target = step.lower().removesuffix("step").rstrip("_")
    for idx, obj in enumerate(steps):
        name = type(obj).__name__.lower().removesuffix("step").rstrip("_")
        if name == target:
            return idx
    raise SystemExit(
        f"Unknown pipeline step: {step!r}. "
        f"Known steps: {', '.join(type(s).__name__ for s in steps)}"
    )


def _resolve_workspace_for_run(config_path: Path) -> Path:
    for parent in [config_path.parent, *config_path.parents]:
        if (parent / "hydromodpy.duckdb").exists() or (parent / ".hmp").is_dir():
            return parent
    return config_path.parent


def _run_script(script_path: Path, extra_args: list[str]) -> None:
    """Run a Python prototype script as a subprocess."""
    from hydromodpy.core.tools.display import print_hydromodpy

    print_hydromodpy()
    cmd = [sys.executable, str(script_path), *extra_args]
    result = subprocess.run(cmd, cwd=str(script_path.parent))
    sys.exit(result.returncode)


def _infer_workflow_from_sections(raw_toml: dict) -> str:
    """Infer the workflow from the TOML sections present.

    Mirrors the dispatch table in :mod:`hydromodpy._cli.workflows` - used
    only when ``--dry-run`` is set and the user has not declared
    ``workflow = "..."`` at the top level.
    """
    from hydromodpy._cli.legacy_calibration import normalize_legacy_calibration_section

    raw_toml = normalize_legacy_calibration_section(raw_toml)
    if "testbed" in raw_toml:
        return "testbed"
    if "comparison" in raw_toml:
        return "comparison"
    if "calibration" in raw_toml:
        return "calibration"
    if "batch" in raw_toml:
        return "batch"
    if "overview" in raw_toml and "simulation" not in raw_toml:
        return "overview"
    if "mesh_catchment" in raw_toml and "simulation" not in raw_toml:
        return "mesh"
    return "simulation"


def _print_dry_run(
    workflow: str,
    config_path: Path,
    raw_toml: dict,
    *,
    resume: str | None,
    from_step: str | None,
    until_step: str | None,
    no_checkpoint: bool,
) -> None:
    """Print the resolved workflow plan without executing it."""
    print(f"[dry-run] workflow: {workflow}")
    print(f"[dry-run] config  : {config_path}")
    print(f"[dry-run] sections: {', '.join(sorted(raw_toml))}")
    if resume is not None:
        print(f"[dry-run] resume  : {resume}")
    if from_step is not None:
        print(f"[dry-run] from    : {from_step}")
    if until_step is not None:
        print(f"[dry-run] until   : {until_step}")
    if no_checkpoint:
        print("[dry-run] checkpoint: disabled")
    if workflow == "simulation":
        try:
            from hydromodpy.pipeline.steps import standard_steps

            print("[dry-run] steps   :")
            for i, s in enumerate(standard_steps()):
                print(f"  {i:02d}  {type(s).__name__}")
        except Exception as exc:  # pragma: no cover
            print(f"[dry-run]   (could not enumerate steps: {exc})")
