"""Wrapper minimal pour lancer une exécution HydroModPy entourée par RuntimeAutoCapture.

Usage:
  python scripts/run_with_capture.py --project-toml /path/to/hydromodpy.toml [--run-id RUN_ID]
  python scripts/run_with_capture.py --callable module.path:callable [--run-id RUN_ID]

Le snapshot est écrit dans:
  <workspace>/execution_knowledge/<run_id>/raw/runtime_capture.jsonl
ou dans `--output-dir` si fourni.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.validity_frame.auto_capture import ExecutionContext, RuntimeAutoCapture


def resolve_callable(spec: str) -> Callable[..., Any]:
    module_path, _, attr = spec.partition(":")
    if not module_path:
        raise ValueError("callable specification must be module:attr")
    mod = importlib.import_module(module_path)
    if not attr:
        if hasattr(mod, "main"):
            return getattr(mod, "main")
        raise ValueError("callable specification missing attribute after ':'")
    if not hasattr(mod, attr):
        raise AttributeError(f"module {module_path} has no attribute {attr}")
    return getattr(mod, attr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-toml", type=str, help="Path to hydromodpy TOML config")
    parser.add_argument("--callable", type=str, help="Dotted module:callable to invoke, e.g. mypkg.mymod:run")
    parser.add_argument("--run-id", type=str, help="Optional run id to use (otherwise uuid4)")
    parser.add_argument("--output-dir", type=str, help="Optional output dir for capture snapshots")
    parser.add_argument(
        "--reset-data-cache",
        action="store_true",
        help="Remove the project data/cache.duckdb before running",
    )
    args = parser.parse_args()

    run_id = args.run_id or str(uuid.uuid4())
    output_dir = Path(args.output_dir) if args.output_dir else None

    # Ensure HydroModPy runtime registries are initialized (bootstrap)
    # Some core components require explicit bootstrap before creating Project
    try:
        importlib.import_module("hydromodpy._bootstrap").bootstrap()
    except Exception:
        # If bootstrap fails, continue and let the later code raise a clear error
        pass

    workspace_path = None
    if args.project_toml:
        config_path = Path(args.project_toml).expanduser().resolve()
        if not config_path.exists():
            print("project toml not found:", config_path, file=sys.stderr)
            sys.exit(2)
        workspace_path = config_path.parent
        if args.reset_data_cache:
            cache_dirs: list[Path] = [workspace_path / "data"]
            if workspace_path.parent.name == "projects":
                cache_dirs.append(workspace_path.parent.parent / "data")
            for cache_dir in cache_dirs:
                for suffix in ("", ".wal", ".lock"):
                    cache_file = cache_dir / f"cache.duckdb{suffix}"
                    if cache_file.exists():
                        try:
                            if cache_file.is_dir():
                                shutil.rmtree(cache_file)
                            else:
                                os.remove(cache_file)
                        except OSError:
                            pass

    if output_dir is None and workspace_path is not None:
        output_dir = workspace_path / "execution_knowledge" / run_id / "raw"
    elif output_dir is None:
        output_dir = Path.cwd() / "execution_knowledge" / run_id / "raw"

    context = ExecutionContext(run_id=run_id, workspace=str(workspace_path) if workspace_path is not None else None)
    capturer = RuntimeAutoCapture(context=context, output_dir=output_dir)

    def _call_project() -> Any:
        from hydromodpy import Project

        if args.project_toml:
            project = Project(args.project_toml)
            return project.run()
        raise RuntimeError("no project toml provided")

    try:
        if args.callable:
            func = resolve_callable(args.callable)
            _, snapshot = capturer.run_with_capture(lambda: func(), solver_source=None, logs=None)
        else:
            _, snapshot = capturer.run_with_capture(_call_project, solver_source=None, logs=None)
    except BaseException as exc:
        print("Execution failed:", exc, file=sys.stderr)
        raise

    jsonl_file = output_dir / "runtime_capture.jsonl"
    output_dir.mkdir(parents=True, exist_ok=True)
    with jsonl_file.open("a", encoding="utf-8") as handle:
        try:
            payload = asdict(snapshot) if is_dataclass(snapshot) else snapshot.__dict__
        except Exception:
            payload = {"run_id": run_id, "status": "unknown"}
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    print("Run complete. Capture written to:", jsonl_file)


if __name__ == "__main__":
    main()