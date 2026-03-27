"""Sequential smoke runner for the mesh-catchment example configurations.

This script is intentionally pragmatic rather than generic. It executes one
curated sequence of example launcher configs and, when relevant, inserts the
paired catchment-identification step just before meshing.

The important design choice is output colocation: for paired scenarios the
temporary override TOMLs force both identification and meshing outputs under
one shared scenario root. That makes post-run inspection much easier because a
single folder contains:

- the precomputed outlets table produced by identification;
- the mesh launcher outputs that consumed that table;
- the transient override TOMLs used to wire those stages together.

In practice this file is used as a local regression smoke runner for the
bundled examples, especially when a mesh scenario depends on derived outlet
tables that are not meant to be maintained by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _ensure_repo_root_on_sys_path() -> Path:
    """Make direct script execution behave like ``python -m`` from the repo root."""
    repo_root = Path(__file__).resolve().parents[2]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    return repo_root


_REPO_ROOT = _ensure_repo_root_on_sys_path()

from hydromodpy_annex.preprocess.catchment_identification_scan.config import (
    CatchmentIdentificationConfig,
)


RUN_SEQUENCE = (
    {
        "mesh_config": "config_headwater_100km2.toml",
        "identification_config": "config_headwater_100km2.toml",
    },
    {
        "mesh_config": "config_1000km2.toml",
        "identification_config": "config_1000km2.toml",
    },
    {
        "mesh_config": "config_s3_10km2.toml",
        "identification_config": "config_s3_10km2.toml",
    },
    {
        "mesh_config": "config_example.toml",
        "identification_config": None,
    },
    {
        "mesh_config": "config_scoped_example.toml",
        "identification_config": None,
    },
    {
        "mesh_config": "config_s3_100km2.toml",
        "identification_config": "config_s3_100km2.toml",
    },
)

def _default_results_root() -> Path:
    """Return one OS-friendly default root for smoke-run outputs."""
    if os.name == "nt":
        return Path("C:/results/Hydromodpy")
    return Path.home() / "HydroModPy"


DEFAULT_RESULTS_ROOT = str(_default_results_root())
_RUNS_SUBDIR = "mesh_catchment_runs"
_IDENTIFICATION_SUMMARY_NAME = "catchment_identification_summary.json"
_OVERRIDE_GLOB = "._run_all_*.toml"


@dataclass(frozen=True)
class _StepPlan:
    scenario_name: str
    scenario_root: Path
    mesh_command: list[str]
    identification_command: list[str] | None
    cleanup_paths: tuple[Path, ...]


def _cleanup_stale_override_configs(*directories: Path) -> tuple[Path, ...]:
    """Delete stale temporary override TOMLs left by interrupted smoke runs."""
    deleted: list[Path] = []
    for directory in directories:
        for path in sorted(directory.glob(_OVERRIDE_GLOB)):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                continue
            deleted.append(path.resolve())
    return tuple(deleted)


def _planned_action_count(
    sequence: tuple[dict[str, str | None], ...] | None = None,
) -> int:
    """Return the number of progress-tracked actions for one smoke run."""
    if sequence is None:
        sequence = RUN_SEQUENCE
    total = 0
    for step in sequence:
        total += 1  # one mesh action always exists
        if step.get("identification_config") is not None:
            total += 1
    return total


def _progress_prefix(*, step_index: int, total_steps: int) -> str:
    """Render one pytest-like percentage prefix for console progress."""
    if total_steps <= 0:
        return "[100%]"
    percentage = int(round((float(step_index) / float(total_steps)) * 100.0))
    percentage = max(0, min(100, percentage))
    return f"[{percentage:>3}%]"


def _results_root() -> Path:
    raw_root = os.environ.get("HYDROMODPY_RESULTS_ROOT", DEFAULT_RESULTS_ROOT)
    return Path(raw_root).expanduser().resolve()


def _scenario_name_from_config_name(config_name: str) -> str:
    stem = Path(config_name).stem.strip()
    return stem.removeprefix("config_") or "default"


def _scenario_root(*, scenario_name: str) -> Path:
    return (_results_root() / _RUNS_SUBDIR / scenario_name).resolve()


def _toml_basic_string(value: str | Path) -> str:
    text = str(value).replace("\\", "/")
    escaped = text.replace('"', '\\"')
    return f'"{escaped}"'


def _write_override_config(
    *,
    original_config_path: Path,
    prefix: str,
    content: str,
) -> Path:
    fd, raw_path = tempfile.mkstemp(
        prefix=prefix,
        suffix=".toml",
        dir=original_config_path.parent,
        text=True,
    )
    os.close(fd)
    path = Path(raw_path)
    path.write_text(content, encoding="utf-8")
    return path


def _render_identification_override_config(
    *,
    original_config_path: Path,
    output_dir: Path,
) -> str:
    return "\n".join(
        [
            f"base_config = {_toml_basic_string(original_config_path.name)}",
            "[catchment_identification_scan]",
            f"output_dir = {_toml_basic_string(output_dir)}",
        ]
    )


def _render_mesh_override_config(
    *,
    original_config_path: Path,
    project_root: Path,
    outlets_table_path: Path | None,
) -> str:
    lines = [
        f"base_config = {_toml_basic_string(original_config_path.name)}",
        "[workspace]",
        f"project_root = {_toml_basic_string(project_root)}",
    ]
    if outlets_table_path is not None:
        lines.extend(
            [
                "[mesh_catchment_batch]",
                f"outlets_table_path = {_toml_basic_string(outlets_table_path)}",
            ]
        )
    return "\n".join(lines)


def _build_step_plan(
    *,
    step: dict[str, str | None],
    mesh_config_dir: Path,
    identification_dir: Path,
) -> _StepPlan:
    """Materialize the commands and temporary overrides for one scenario.

    The original example TOMLs are kept untouched. Instead, this helper writes
    tiny overlay configs next to them so each scenario can be redirected toward
    one dedicated results root and, for paired cases, so the freshly generated
    outlets CSV is passed directly to the mesh launcher.
    """
    mesh_name = str(step["mesh_config"])
    identification_name = step["identification_config"]
    scenario_name = _scenario_name_from_config_name(mesh_name)
    scenario_root = _scenario_root(scenario_name=scenario_name)
    scenario_root.mkdir(parents=True, exist_ok=True)

    cleanup_paths: list[Path] = []
    identification_command: list[str] | None = None
    paired_outlets_csv_path: Path | None = None

    try:
        if identification_name is not None:
            identification_config_path = (identification_dir / identification_name).resolve()
            identification_output_dir = (scenario_root / "identification").resolve()
            identification_summary_path = identification_output_dir / _IDENTIFICATION_SUMMARY_NAME
            identification_cfg = CatchmentIdentificationConfig.from_toml(
                identification_config_path
            )
            # The paired mesh step should consume the outlets generated in the
            # same scenario folder, not any stale CSV baked into the original
            # example config.
            paired_outlets_csv_path = identification_output_dir / identification_cfg.outlets_csv_name
            identification_override_path = _write_override_config(
                original_config_path=identification_config_path,
                prefix=f"._run_all_{scenario_name}_ident_",
                content=_render_identification_override_config(
                    original_config_path=identification_config_path,
                    output_dir=identification_output_dir,
                ),
            )
            cleanup_paths.append(identification_override_path)
            identification_command = [
                sys.executable,
                str(identification_dir / "run_catchment_identification_case.py"),
                "--config",
                str(identification_override_path),
                "--output-json",
                str(identification_summary_path),
            ]

        mesh_config_path = (mesh_config_dir / mesh_name).resolve()
        mesh_override_path = _write_override_config(
            original_config_path=mesh_config_path,
            prefix=f"._run_all_{scenario_name}_mesh_",
            content=_render_mesh_override_config(
                original_config_path=mesh_config_path,
                # Mesh outputs are collocated under one scenario-local root so
                # manual inspection does not require reconstructing which
                # source config produced which result folder.
                project_root=(scenario_root / "mesh").resolve(),
                outlets_table_path=paired_outlets_csv_path,
            ),
        )
        cleanup_paths.append(mesh_override_path)
        mesh_command = [
            sys.executable,
            "-m",
            "launchers",
            "mesh-catchment",
            "run",
            str(mesh_override_path),
        ]
    except Exception:
        for path in cleanup_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        raise

    return _StepPlan(
        scenario_name=scenario_name,
        scenario_root=scenario_root,
        mesh_command=mesh_command,
        identification_command=identification_command,
        cleanup_paths=tuple(cleanup_paths),
    )


def _run_command(
    *,
    label: str,
    command: list[str],
    cwd: Path,
    step_index: int,
    total_steps: int,
) -> int:
    """Execute one child process, suppress blank lines, and report progress."""
    prefix = _progress_prefix(step_index=step_index, total_steps=total_steps)
    print(f"{prefix} {label} ...", flush=True)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip()
        if line.strip() == "":
            continue
        print(f"      {line}", flush=True)

    return_code = int(process.wait())
    if return_code == 0:
        print(f"{prefix} {label} ... OK", flush=True)
        return 0
    print(f"{prefix} {label} ... FAIL (exit code {return_code})", flush=True)
    return return_code


def _print_skipped(
    *,
    label: str,
    step_index: int,
    total_steps: int,
    reason: str,
) -> None:
    """Report one intentionally skipped action in the progress stream."""
    prefix = _progress_prefix(step_index=step_index, total_steps=total_steps)
    print(f"{prefix} {label} ... SKIP ({reason})", flush=True)


def main() -> int:
    """Run the configured identification/meshing sequence and return one exit code."""
    repo_root = Path(__file__).resolve().parents[2]
    mesh_config_dir = Path(__file__).resolve().parent
    identification_dir = (
        repo_root / "hydromodpy_annex" / "preprocess" / "catchment_identification_scan"
    )
    failures = 0
    cleanup_paths: list[Path] = []
    total_steps = _planned_action_count()
    step_index = 0

    try:
        _cleanup_stale_override_configs(mesh_config_dir, identification_dir)
        for step in RUN_SEQUENCE:
            plan = _build_step_plan(
                step=step,
                mesh_config_dir=mesh_config_dir,
                identification_dir=identification_dir,
            )
            cleanup_paths.extend(plan.cleanup_paths)

            if plan.identification_command is not None:
                # Paired scenarios now write identification outputs under the
                # same scenario root as the mesh results for easier inspection.
                step_index += 1
                exit_code = _run_command(
                    label=f"identify {plan.scenario_name}",
                    command=plan.identification_command,
                    cwd=repo_root,
                    step_index=step_index,
                    total_steps=total_steps,
                )
                if exit_code != 0:
                    failures += 1
                    step_index += 1
                    _print_skipped(
                        label=f"mesh {plan.scenario_name}",
                        step_index=step_index,
                        total_steps=total_steps,
                        reason="identify failed",
                    )
                    continue

            # Only launch meshing after the optional identification step has
            # succeeded, so each config sees the freshest derived inputs.
            step_index += 1
            exit_code = _run_command(
                label=f"mesh {plan.scenario_name}",
                command=plan.mesh_command,
                cwd=repo_root,
                step_index=step_index,
                total_steps=total_steps,
            )
            if exit_code != 0:
                failures += 1
    finally:
        for path in cleanup_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
