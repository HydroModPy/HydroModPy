"""``hmp run`` - execute a workflow declared by the TOML.

Single CLI entry point. The TOML must carry a top-level
``[workflow] mode = "..."`` field (one of ``simulation``, ``calibration``,
``overview``, ``comparison``, ``testbed``, ``site_selection``). Absence
raises ``WorkflowMissingError``.

Overrides are merged as defaults < base_config < --overlay < --set < env.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hydromodpy.cli._conventions import profile_parser
from hydromodpy.cli.helpers import (
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SIGINT,
    auto_scan_workspace,
    profile_run,
    resolve_profile_output,
)

NAME: str = "run"
HELP: str = "Run a workflow from a TOML config"


def _step_choices() -> list[str]:
    """Return the canonical 12-step pipeline names for shell completion."""
    try:
        from hydromodpy.workflow.orchestrator import standard_steps

        return [getattr(s, "name", type(s).__name__) for s in standard_steps()]
    except Exception:
        return []


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP, parents=[profile_parser()])
    config_arg = parser.add_argument(
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
    from_arg = parser.add_argument(
        "--from",
        dest="from_step",
        default=None,
        metavar="STEP",
        help="Resume from a specific pipeline step (name or index).",
    )
    until_arg = parser.add_argument(
        "--until",
        dest="until_step",
        default=None,
        metavar="STEP",
        help="Stop after the specified pipeline step (name or index).",
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
            "Reject any fresh download when hydromodpy.lock is present; "
            "every artefact must already be in the catalog and match its SHA-256."
        ),
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        dest="no_lock",
        help="Skip the post-run hydromodpy.lock write (default: write).",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        dest="no_display",
        help="Skip auto-rendering of the figures listed in [display].figures.",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        dest="no_parallel",
        help=(
            "Force the Pipeline to run cohorts sequentially. Useful for "
            "debugging or to keep deterministic step ordering."
        ),
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
    import hydromodpy as hmp
    from hydromodpy.display.banner import print_hydromodpy
    from hydromodpy.workflow.dispatch import (
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
    no_display = bool(getattr(args, "no_display", False))
    frozen = bool(getattr(args, "frozen", False))
    no_lock = bool(getattr(args, "no_lock", False))
    parallel = not bool(getattr(args, "no_parallel", False))

    if dry_run:
        _print_dry_run(
            workflow,
            run_path,
            raw_toml,
            resume=resume,
            from_step=from_step,
            until_step=until_step,
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

    if (from_step is not None or until_step is not None) and workflow != "simulation":
        print(
            f"--from / --until are only supported for the "
            f"'simulation' workflow (detected '{workflow}').",
            file=sys.stderr,
        )
        _cleanup_effective_toml(effective_path, source=config_path)
        sys.exit(EXIT_CONFIG)

    if resume is not None:
        _emit_config_replay_audit(run_path, resume=str(resume))

    if frozen:
        try:
            _verify_frozen_inputs_strict(run_path, raw_toml)
        except FrozenVerificationError as exc:
            print(f"--frozen: {exc}", file=sys.stderr)
            _cleanup_effective_toml(effective_path, source=config_path)
            sys.exit(EXIT_CONFIG)

    profile_output = resolve_profile_output(getattr(args, "profile", None), config_path)
    try:
        with profile_run(profile_output):
            if workflow == "simulation":
                summary = hmp.run(
                    run_path,
                    resume=resume,
                    from_step=from_step,
                    until_step=until_step,
                    no_display=no_display,
                    frozen=frozen,
                    parallel=parallel,
                )
            else:
                summary = hmp.run(run_path)
    except KeyboardInterrupt:
        print("Aborted by user.", file=sys.stderr)
        sys.exit(EXIT_SIGINT)
    except ValidationError as exc:
        print(f"Config invalid: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        _cleanup_effective_toml(effective_path, source=config_path)
        sys.exit(EXIT_NOT_FOUND)
    finally:
        _cleanup_effective_toml(effective_path, source=config_path)

    if not no_lock:
        _post_run_lockfile_write(run_path, raw_toml)

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


class FrozenVerificationError(RuntimeError):
    """Raised when ``--frozen`` finds a lockfile drift before running anything."""


def _verify_frozen_inputs_strict(config_path: Path, raw_toml: dict[str, Any]) -> None:
    """Verify the workspace lockfile before launching a ``--frozen`` run.

    Walks the same workspace-resolution logic as the post-run lockfile
    writer, opens the data cache, and calls
    :func:`hydromodpy.data.data_freeze.verify_inputs_strict` against the
    project's ``hydromodpy.lock``. Any mismatch aborts the run.
    """
    from hydromodpy.data.data_freeze import (
        LOCKFILE_NAME,
        verify_inputs_strict,
    )
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

    workspace_payload = raw_toml.get("workspace") if isinstance(raw_toml, dict) else None
    project_root = config_path.parent
    if isinstance(workspace_payload, dict):
        declared = workspace_payload.get("project_root")
        if declared:
            candidate = Path(declared).expanduser()
            if not candidate.is_absolute():
                candidate = (config_path.parent / candidate).resolve()
            project_root = candidate

    lockfile_path = project_root / LOCKFILE_NAME
    if not lockfile_path.is_file():
        raise FrozenVerificationError(
            f"hydromodpy.lock not found at {lockfile_path}; --frozen requires a prior run."
        )

    data_dir = _resolve_workspace_data_dir(workspace_payload, project_root)
    db_path = data_dir / "cache.duckdb"
    if not db_path.is_file():
        raise FrozenVerificationError(
            f"Data cache not found at {db_path}; --frozen requires a populated workspace."
        )

    try:
        with DataCatalogDuckDB(db_path) as catalog:
            mismatches = verify_inputs_strict(catalog, lockfile_path)
    except Exception as exc:  # noqa: BLE001 - any catalog error aborts the run
        raise FrozenVerificationError(f"Could not verify lockfile {lockfile_path}: {exc}") from exc
    if mismatches:
        first = mismatches[0]
        raise FrozenVerificationError(
            f"{len(mismatches)} lockfile mismatch(es); first: "
            f"{first.kind} on {first.path} (variable={first.variable})"
        )


def _emit_config_replay_audit(config_path: Path, *, resume: str) -> None:
    """Emit one ``config.replay`` audit row when ``hmp run --resume`` fires.

    Best-effort: looks for a catalog next to the config and, failing that,
    walks up to find a workspace. Any exception is swallowed.
    """
    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.core.state.paths import CATALOG_FILENAME
    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.catalog.audit import emit_audit_event

    try:
        workspace = find_catalog_root(config_path.parent)
    except Exception:
        return
    catalog_path = workspace / CATALOG_FILENAME
    if not catalog_path.is_file():
        return
    try:
        with SimulationCatalog(workspace) as catalog:
            emit_audit_event(
                catalog.connection,
                event_type="config.replay",
                actor_kind="cli",
                payload={"resume": resume, "config": str(config_path)},
            )
    except Exception:
        pass


def _post_run_lockfile_write(config_path: Path, raw_toml: dict[str, Any]) -> None:
    """Persist ``hydromodpy.lock`` next to the project after a successful run.

    Best-effort: any failure here is logged and does not bubble up so the run
    output stays the source of truth. Skipped silently when no workspace
    data catalog is present.
    """
    from hydromodpy.config.schema_export import schema_sha256
    from hydromodpy.data.data_freeze import LOCKFILE_NAME, write_lockfile
    from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
    from hydromodpy.results.parquet_schemas import PARQUET_SCHEMA_VERSION
    from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION

    workspace_payload = raw_toml.get("workspace") if isinstance(raw_toml, dict) else None
    project_root = config_path.parent
    if isinstance(workspace_payload, dict):
        declared = workspace_payload.get("project_root")
        if declared:
            candidate = Path(declared).expanduser()
            if not candidate.is_absolute():
                candidate = (config_path.parent / candidate).resolve()
            project_root = candidate

    data_dir = _resolve_workspace_data_dir(workspace_payload, project_root)
    db_path = data_dir / "cache.duckdb"
    if not db_path.is_file():
        return

    dest = project_root / LOCKFILE_NAME
    solvers = _collect_solver_binaries(raw_toml)
    try:
        with DataCatalogDuckDB(db_path) as catalog:
            write_lockfile(
                catalog,
                dest,
                project_root=project_root,
                solvers=solvers,
                schema_sha256=schema_sha256(),
                zarr_schema_version=str(ZARR_SCHEMA_VERSION),
                parquet_schema_version=str(PARQUET_SCHEMA_VERSION),
            )
    except Exception as exc:  # pragma: no cover - defensive logging only
        print(f"  WARNING: hydromodpy.lock write failed: {exc}", file=sys.stderr)
        return
    print(f"  Lockfile written: {dest}", file=sys.stderr)


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


def _collect_solver_binaries(raw_toml: dict[str, Any]) -> dict[str, Path]:
    """Best-effort discovery of solver binaries declared in the config."""
    payload: dict[str, Path] = {}
    solver_section = raw_toml.get("solver") if isinstance(raw_toml, dict) else None
    if not isinstance(solver_section, dict):
        return payload

    candidates: list[tuple[str, Any]] = []
    for solver_name, sub in solver_section.items():
        if isinstance(sub, dict):
            for key in ("bin_path", "binary_path", "exe", "executable"):
                if key in sub:
                    candidates.append((str(solver_name), sub.get(key)))

    for solver_name, raw in candidates:
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if path.is_file():
            payload[solver_name] = path
    return payload


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
    """Parse HMP_SET_* environment overrides."""
    payload: dict[str, Any] = {}
    prefix = "HMP_SET_"
    for name, raw_value in env.items():
        if not name.startswith(prefix):
            continue
        # Windows normalizes environment variable names to uppercase. TOML keys
        # are case-sensitive, so normalize the override path back to the
        # lowercase key convention used by HydroModPy config files.
        dotted_path = name[len(prefix) :].lower().replace("__", ".")
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

    Mirrors the dispatch table in :mod:`hydromodpy.project.dispatch.workflow` -
    used only when ``--dry-run`` is set and the user has not declared
    ``[workflow] mode = "..."``.
    """
    if "calibration" in raw_toml:
        return "calibration"
    if "overview" in raw_toml and "simulation" not in raw_toml:
        return "overview"
    if "comparison" in raw_toml:
        return "comparison"
    if "testbed" in raw_toml:
        return "testbed"
    if "site_selection" in raw_toml:
        return "site_selection"
    return "simulation"


def _print_dry_run(
    workflow: str,
    config_path: Path,
    raw_toml: dict,
    *,
    resume: str | None,
    from_step: str | None,
    until_step: str | None,
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
    if workflow == "simulation":
        try:
            from hydromodpy.workflow.orchestrator import standard_steps

            print("[dry-run] steps   :")
            for i, s in enumerate(standard_steps()):
                print(f"  {i:02d}  {type(s).__name__}")
        except Exception as exc:  # pragma: no cover
            print(f"[dry-run]   (could not enumerate steps: {exc})")
