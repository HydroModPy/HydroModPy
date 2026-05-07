"""``hmp run`` - execute a workflow declared by the TOML.

Single CLI entry point. The TOML must carry a top-level
``[workflow] mode = "..."`` field (one of ``simulation``, ``calibration``,
``batch``, ``overview``, ``mesh``, ``comparison``, ``testbed``). Absence
raises ``WorkflowMissingError``.

Overrides are merged as defaults < base_config < --overlay < --set < env.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_USER_ABORT,
    auto_scan_workspace,
)

NAME: str = "run"
HELP: str = "Run a workflow from a TOML config"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "config",
        type=Path,
        help="Path to a TOML config",
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
    checkpoint_group = parser.add_mutually_exclusive_group()
    checkpoint_group.add_argument(
        "--checkpoint",
        action="store_true",
        dest="checkpoint",
        help="Persist pipeline checkpoints so the run can be resumed.",
    )
    checkpoint_group.add_argument(
        "--no-checkpoint",
        action="store_true",
        dest="no_checkpoint",
        help=argparse.SUPPRESS,
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
    parser.add_argument(
        "--overlay",
        action="append",
        default=[],
        type=Path,
        help="TOML overlay applied after base_config inheritance. Repeatable.",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        dest="set_overrides",
        metavar="PATH=VALUE",
        help="Dotted TOML override applied after overlays, e.g. workspace.project_root=out.",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    target = Path(args.config).expanduser().resolve()
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    if target.suffix == ".toml":
        _run_toml(target, args=args)
    elif target.suffix == ".py":
        print(
            "Python scripts are not supported by 'hmp run'. "
            "Use 'hmp dev run-script <script.py>' for prototypes.",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)
    else:
        print(
            f"Unsupported file type: {target.suffix} (expected .toml)",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)


def _run_toml(config_path: Path, *, args: argparse.Namespace) -> None:
    """Run a workflow from a TOML file.

    The TOML MUST declare ``[workflow] mode = "..."`` - otherwise
    :class:`~hydromodpy.workflow.dispatch.WorkflowMissingError` is raised and
    the CLI exits with ``EXIT_CONFIG``. No implicit detection from sections.
    """
    from hydromodpy.display.banner import print_hydromodpy
    from hydromodpy.workflow.dispatch import (
        DISPATCH,
        WorkflowError,
        resolve_workflow,
    )

    print_hydromodpy()
    auto_scan_workspace(config_path)

    effective_path: Path | None = None
    try:
        effective_path, raw_toml = _materialize_effective_toml(config_path, args=args)
    except ValueError as exc:
        print(f"Invalid override: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as exc:
        print(f"Invalid TOML: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    run_path = effective_path or config_path

    dry_run = bool(getattr(args, "dry_run", False))
    try:
        workflow = resolve_workflow(
            run_path,
            cli_workflow=None,
            require_toml_field=True,
        )
    except WorkflowError as exc:
        if dry_run:
            workflow = _infer_workflow_from_sections(raw_toml)
        else:
            print(str(exc), file=sys.stderr)
            _cleanup_effective_toml(effective_path, source=config_path)
            sys.exit(EXIT_CONFIG)

    resume = getattr(args, "resume", None)
    from_step = getattr(args, "from_step", None)
    until_step = getattr(args, "until_step", None)
    checkpoint = bool(getattr(args, "checkpoint", False))
    no_checkpoint = bool(getattr(args, "no_checkpoint", False))
    no_display = bool(getattr(args, "no_display", False))
    frozen = bool(getattr(args, "frozen", False))
    resume_options_used = resume is not None or from_step is not None or until_step is not None
    checkpoint_enabled = bool(checkpoint or resume_options_used) and not no_checkpoint

    if dry_run:
        _print_dry_run(
            workflow,
            run_path,
            raw_toml,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
            checkpoint=checkpoint_enabled,
        )
        _cleanup_effective_toml(effective_path, source=config_path)
        return

    if resume is not None and workflow != "simulation":
        print(
            f"--resume is only supported for the 'simulation' workflow (detected '{workflow}').",
            file=sys.stderr,
        )
        _cleanup_effective_toml(effective_path, source=config_path)
        sys.exit(EXIT_CONFIG)

    if (from_step is not None or until_step is not None or checkpoint or no_checkpoint) and (
        workflow != "simulation"
    ):
        print(
            f"--from / --until / --checkpoint are only supported for the "
            f"'simulation' workflow (detected '{workflow}').",
            file=sys.stderr,
        )
        _cleanup_effective_toml(effective_path, source=config_path)
        sys.exit(EXIT_CONFIG)

    if no_checkpoint and resume_options_used:
        print(
            "--no-checkpoint cannot be combined with --resume, --from or --until.",
            file=sys.stderr,
        )
        _cleanup_effective_toml(effective_path, source=config_path)
        sys.exit(EXIT_CONFIG)

    runner = DISPATCH[workflow]

    try:
        if workflow == "simulation":
            summary = runner(
                run_path,
                resume=resume,
                from_step=from_step,
                until_step=until_step,
                checkpoint=checkpoint_enabled,
                no_checkpoint=no_checkpoint,
                no_display=no_display,
                frozen=frozen,
            )
        else:
            summary = runner(run_path)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        sys.exit(EXIT_USER_ABORT)
    except ValidationError as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        _cleanup_effective_toml(effective_path, source=config_path)
        sys.exit(EXIT_NOT_FOUND)
    finally:
        _cleanup_effective_toml(effective_path, source=config_path)

    print(f"Workflow '{workflow}' complete: {config_path.name}", file=sys.stderr)
    if summary:
        for key, value in summary.items():
            print(f"  {key}: {value}", file=sys.stderr)


def _materialize_effective_toml(
    config_path: Path,
    *,
    args: argparse.Namespace,
) -> tuple[Path | None, dict[str, Any]]:
    """Return the source TOML or a temporary TOML with CLI overlays applied."""
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.core.toml_io.merge import merge_toml_payloads
    from hydromodpy.core.toml_io.writer import dumps

    overlays = [Path(path).expanduser().resolve() for path in getattr(args, "overlay", []) or []]
    set_items = list(getattr(args, "set_overrides", []) or [])
    cli_overrides = _parse_cli_set_overrides(set_items)
    env_overrides = _parse_env_set_overrides(os.environ)

    base_payload = load_toml_with_base_config(config_path)
    overlay_payloads = [load_toml_with_base_config(path) for path in overlays]
    raw_toml = merge_toml_payloads(
        {},
        base_chain=[base_payload],
        overlays=overlay_payloads,
        cli_overrides=cli_overrides,
        env_overrides=env_overrides,
    )
    if not overlays and not cli_overrides and not env_overrides:
        return None, raw_toml

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix=f".{config_path.stem}.effective.",
        suffix=".toml",
        dir=config_path.parent,
        delete=False,
    ) as handle:
        handle.write(dumps(raw_toml))
        temp_path = Path(handle.name)
    return temp_path, raw_toml


def _cleanup_effective_toml(path: Path | None, *, source: Path) -> None:
    """Remove a temporary effective TOML if one was created."""
    if path is None or path == source:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _parse_cli_set_overrides(items: list[str]) -> dict[str, Any]:
    """Parse repeatable ``--set dotted.path=value`` overrides."""
    payload: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError("--set expects PATH=VALUE")
        dotted_path, raw_value = item.split("=", 1)
        _assign_dotted_value(payload, dotted_path.strip(), _parse_override_value(raw_value))
    return payload


def _parse_env_set_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    """Parse HYDROMODPY_SET_* environment overrides."""
    payload: dict[str, Any] = {}
    prefix = "HYDROMODPY_SET_"
    for name, raw_value in env.items():
        if not name.startswith(prefix):
            continue
        dotted_path = name[len(prefix) :].replace("__", ".")
        _assign_dotted_value(payload, dotted_path, _parse_override_value(raw_value))
    return payload


def _parse_override_value(raw_value: str) -> Any:
    """Parse one CLI/env override value as TOML when possible."""
    import tomllib

    text = raw_value.strip()
    try:
        return tomllib.loads(f"value = {text}\n")["value"]
    except tomllib.TOMLDecodeError:
        return raw_value


def _assign_dotted_value(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Assign a value into a nested mapping using a dotted path."""
    parts = [part.strip() for part in dotted_path.split(".") if part.strip()]
    if not parts:
        raise ValueError("override path cannot be empty")
    cursor = payload
    for part in parts[:-1]:
        existing = cursor.setdefault(part, {})
        if not isinstance(existing, dict):
            raise ValueError(f"override path {dotted_path!r} collides at {part!r}")
        cursor = existing
    cursor[parts[-1]] = value


def _infer_workflow_from_sections(raw_toml: dict) -> str:
    """Infer the workflow from the TOML sections present.

    Mirrors the dispatch table in :mod:`hydromodpy.workflow.dispatch` - used
    only when ``--dry-run`` is set and the user has not declared
    ``[workflow] mode = "..."``.
    """
    if "calibration" in raw_toml:
        return "calibration"
    if "batch" in raw_toml:
        return "batch"
    if "overview" in raw_toml and "simulation" not in raw_toml:
        return "overview"
    if "mesh_catchment" in raw_toml and "simulation" not in raw_toml:
        return "mesh"
    if "comparison" in raw_toml:
        return "comparison"
    if "testbed" in raw_toml:
        return "testbed"
    return "simulation"


def _print_dry_run(
    workflow: str,
    config_path: Path,
    raw_toml: dict,
    *,
    resume: str | None,
    from_step: str | None,
    until_step: str | None,
    checkpoint: bool,
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
    print(f"[dry-run] checkpoint: {'enabled' if checkpoint else 'disabled'}")
    if workflow == "simulation":
        try:
            from hydromodpy.workflow.orchestrator import standard_steps

            print("[dry-run] steps   :")
            for i, s in enumerate(standard_steps()):
                print(f"  {i:02d}  {type(s).__name__}")
        except Exception as exc:  # pragma: no cover
            print(f"[dry-run]   (could not enumerate steps: {exc})")
