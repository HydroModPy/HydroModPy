"""Runtime helpers shared by validation cases and validation tests."""

from __future__ import annotations

import gc
import hashlib
import os
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from validation_cases.shared.loaders import load_case_metadata


REPO_ROOT = Path(__file__).resolve().parents[2]

_NWT_VALIDATION_PROFILE_SIMPLE = """[modflownwt.runtime]
mf_version = "mfnwt"
mf_listunit = 2
mf_verbose = false
nwt_headtol = 1e-6
nwt_fluxtol = 1e-4
nwt_maxiterout = 500
nwt_thickfact = 1e-5
nwt_linmeth = 1
nwt_iprnwt = 0
nwt_ibotav = 1
nwt_options = "SIMPLE"
nwt_continue = false
nwt_backflag = 0
nwt_stoptol = 1e-10
dis_itmuni = 1
bas_hnoflo = -9999.0
upw_iphdry = 1
upw_hdry = -100.0
upw_layvka = 1
evt_nevtop = 3
evt_ievt = 1
evt_ipakcb = 1
oc_compact = true
wel_ipakcb = 1
lmt_output_file_name = "mt3d_link.ftl"
lmt_extension = "lmt8"
lmt_output_format = "unformatted"

[modflownwt.process_specific]
vka = 1.0
exdp = "1.0 m"
"""

_NWT_VALIDATION_PROFILE_COMPLEX = """[modflownwt.runtime]
mf_version = "mfnwt"
mf_listunit = 2
mf_verbose = false
nwt_headtol = 1e-6
nwt_fluxtol = 1e-4
nwt_maxiterout = 1000
nwt_thickfact = 1e-5
nwt_linmeth = 1
nwt_iprnwt = 0
nwt_ibotav = 1
nwt_options = "COMPLEX"
nwt_continue = false
nwt_backflag = 0
nwt_stoptol = 1e-10
dis_itmuni = 1
bas_hnoflo = -9999.0
upw_iphdry = 1
upw_hdry = -100.0
upw_layvka = 1
evt_nevtop = 3
evt_ievt = 1
evt_ipakcb = 1
oc_compact = true
wel_ipakcb = 1
lmt_output_file_name = "mt3d_link.ftl"
lmt_extension = "lmt8"
lmt_output_format = "unformatted"

[modflownwt.process_specific]
vka = 1.0
exdp = "1.0 m"
"""

_VALIDATION_PROFILES_BY_SOLVER_AND_CASE: dict[str, dict[str, str]] = {
    "modflownwt": {
        "boussinesq_fixed_head_piecewise_k_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "boussinesq_uniform_recharge_piecewise_k_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "boussinesq_sloping_substratum_constant_thickness_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "boussinesq_sloping_substratum_fixed_head_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "boussinesq_sloping_substratum_uniform_recharge_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "brutsaert_recession_linearized_deep_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "brutsaert_recession_boussinesq_thin_1d": _NWT_VALIDATION_PROFILE_COMPLEX,
        "dupuit_divide_river_1d": _NWT_VALIDATION_PROFILE_COMPLEX,
        "dupuit_fixed_head_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "dupuit_uniform_recharge_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "linearized_unconfined_drainage_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "linearized_unconfined_hillslope_drainage_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
        "linearized_unconfined_boundary_piecewise_1d": _NWT_VALIDATION_PROFILE_SIMPLE,
    },
}

def _read_toml(path: Path) -> dict[str, Any]:
    """Read one TOML payload."""
    with path.open("r", encoding="utf-8") as stream:
        return tomllib.loads(stream.read().lstrip("\ufeff"))


def _merge_toml_payloads(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_toml_payloads(existing, value)
        elif (
            isinstance(existing, list)
            and isinstance(value, list)
            and value
            and all(isinstance(item, Mapping) for item in existing)
            and all(isinstance(item, Mapping) for item in value)
            and len(existing) == len(value)
        ):
            merged[key] = [
                _merge_toml_payloads(base_item, override_item)
                for base_item, override_item in zip(existing, value, strict=False)
            ]
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value
    return merged


def _format_toml_key(parts: list[str] | tuple[str, ...]) -> str:
    return ".".join(parts)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        if any(isinstance(item, Mapping) for item in value):
            raise ValueError("Cannot inline an array containing table dictionaries.")
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    if isinstance(value, tuple):
        return _format_toml_value(list(value))
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


def _dump_toml_table(
    table: Mapping[str, Any],
    lines: list[str],
    *,
    path: list[str] | None = None,
) -> None:
    prefix = path or []
    scalar_entries: list[tuple[str, Any]] = []
    nested_tables: list[tuple[str, Mapping[str, Any]]] = []
    array_tables: list[tuple[str, list[Mapping[str, Any]]]] = []

    for key, value in table.items():
        if isinstance(value, Mapping):
            nested_tables.append((key, dict(value)))
        elif isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
            array_tables.append((key, [dict(item) for item in value]))
        else:
            if value is None:
                continue
            scalar_entries.append((key, value))

    for key, value in scalar_entries:
        lines.append(f"{key} = {_format_toml_value(value)}")

    for key, value in nested_tables:
        if lines:
            lines.append("")
        lines.append(f"[{_format_toml_key(prefix + [key])}]")
        _dump_toml_table(value, lines, path=prefix + [key])

    for key, values in array_tables:
        for value in values:
            if lines:
                lines.append("")
            lines.append(f"[[{_format_toml_key(prefix + [key])}]]")
            _dump_toml_table(value, lines, path=prefix + [key])


def _dump_toml(payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _dump_toml_table(payload, lines)
    return "\n".join(lines).strip() + "\n"


def _rmtree_onerror(func, path, exc_info) -> None:
    """Retry one failed ``rmtree`` step after clearing a read-only bit."""
    del exc_info
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        # Some filesystems or locked files may reject a direct read-only bit change.
        # Try a permissive fallback before giving the retry loop another chance.
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
    try:
        func(path)
    except OSError:
        # Intentionally let the caller retry; this is common on Windows when
        # binaries still hold temporary locks during directory cleanup.
        pass


def remove_tree_with_retry(
    path: Path,
    *,
    retries: int = 5,
    base_delay_s: float = 0.2,
) -> None:
    """Remove one directory tree with retries for transient Windows locks."""
    if not path.exists():
        return

    last_error: PermissionError | None = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_rmtree_onerror)
            return
        except FileNotFoundError:
            return
        except (PermissionError, OSError) as exc:
            last_error = exc
            gc.collect()
            if attempt == retries - 1:
                raise
            time.sleep(base_delay_s * (attempt + 1))

    if last_error is not None:
        raise last_error


def remove_file_with_retry(
    path: Path,
    *,
    retries: int = 5,
    base_delay_s: float = 0.2,
) -> None:
    """Remove one file with retries for transient Windows locks/read-only bits."""
    if not path.exists():
        return

    last_error: PermissionError | None = None
    for attempt in range(retries):
        try:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            if attempt == retries - 1:
                raise
            time.sleep(base_delay_s * (attempt + 1))

    if last_error is not None:
        raise last_error


@dataclass(frozen=True, slots=True)
class ValidationRunResult:
    """Resolved workspace paths for one completed validation run."""

    case_dir: Path
    solver_name: str
    out_path: Path
    model_ws: Path
    postprocess_dir: Path
    particles_dir: Path
    run_returncode: int = 0
    run_stdout: str = ""
    run_stderr: str = ""
    store: Any = None
    sim_id: str | None = None


def _short_validation_name(value: str | Path, *, max_length: int = 28) -> str:
    """Return a deterministic filesystem-friendly validation folder name."""
    text = str(value).strip()
    if len(text) <= max_length:
        return text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    keep = max_length - len(digest) - 1
    return f"{text[:keep]}_{digest}"


def resolve_validation_results_dir(*, test_file: str | Path, run_name: str) -> Path:
    """Create one deterministic output directory for a validation run."""
    base_out_path = os.environ.get("HYDROMODPY_OUT_PATH")
    if base_out_path:
        results_root = Path(base_out_path).expanduser().resolve() / "validation"
        probe_dir = results_root / f".__probe_{os.getpid()}_{time.time_ns()}"
        try:
            results_root.mkdir(parents=True, exist_ok=True)
            probe_dir.mkdir()
        except OSError:
            results_root = Path(tempfile.gettempdir()) / "hydromodpy_validation_outputs"
        else:
            probe_dir.rmdir()
    else:
        results_root = Path(tempfile.gettempdir()) / "hydromodpy_validation_outputs"

    test_stem = _short_validation_name(Path(test_file).resolve().stem)
    safe_run_name = _short_validation_name(run_name)
    parent_dir = results_root / test_stem
    out_dir = parent_dir / safe_run_name
    if out_dir.exists():
        unique_suffix = hashlib.sha1(
            f"{safe_run_name}-{os.getpid()}-{time.time_ns()}".encode("utf-8")
        ).hexdigest()[:8]
        out_dir = parent_dir / f"{safe_run_name}_{unique_suffix}"
    parent_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def resolve_model_workspace(
    out_path: Path,
    *,
    watershed_name: str | None = None,
    results_folder_name: str = "results_simulations",
    model_name: str | None = None,
    model_name_prefix: str | None = None,
) -> tuple[Path, Path, Path]:
    """Resolve generated workspace folders for one completed launcher run.

    With the project-root layout, ``out_path`` IS the project root and
    results live directly at ``out_path/<results_folder>/<model>/...``.
    The ``watershed_name`` parameter is accepted but ignored.
    """
    results_dir = out_path / results_folder_name
    assert results_dir.is_dir(), f"Results folder not found: {results_dir}"

    if model_name is not None:
        model_ws = results_dir / model_name
        if not model_ws.is_dir():
            target = str(model_name).lower()
            case_insensitive_matches = [
                p
                for p in results_dir.iterdir()
                if p.is_dir() and p.name.lower() == target
            ]
            if len(case_insensitive_matches) == 1:
                model_ws = case_insensitive_matches[0]
            else:
                assert model_ws.is_dir(), f"Model folder not found: {model_ws}"
    else:
        model_dirs = sorted(
            p
            for p in results_dir.iterdir()
            if p.is_dir()
            and not p.name.startswith("_")
            and (model_name_prefix is None or p.name.startswith(model_name_prefix))
        )
        assert model_dirs, f"No model folder found in {results_dir}"
        model_ws = model_dirs[0]

    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return model_ws, postprocess_dir, particles_dir


def _discover_result_store(project_path: Path) -> tuple[Any, str | None]:
    """Try to open a SimulationCatalog from a project directory and find its sim_id.

    Returns ``(store, sim_id)`` on success, ``(None, None)`` on failure.
    The caller is responsible for closing the store when done.
    """
    db_path = project_path / "hydromodpy.duckdb"
    if not db_path.exists():
        return None, None
    try:
        from hydromodpy.results.catalog import SimulationCatalog

        store = SimulationCatalog(project_path)
        sims = store.list_simulations()
        if sims.empty:
            store.close()
            return None, None
        # Pick the most recent (last) simulation
        sim_id = str(sims.iloc[-1]["sim_id"])
        return store, sim_id
    except Exception:
        return None, None


def run_example_script(
    *,
    script_path: Path,
    out_path: Path,
    out_env_var: str,
    extra_env: dict | None = None,
    script_args: list[str] | None = None,
    timeout: int = 1200,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Run one HydroModPy launcher script as a subprocess."""
    env = os.environ.copy()
    env[out_env_var] = str(out_path)
    env["HYDROMODPY_PROJECT_ROOT"] = str(out_path)
    env.setdefault("MPLBACKEND", "Agg")
    if extra_env:
        for key, value in extra_env.items():
            env[key] = str(value)

    run_args = [] if script_args is None else list(script_args)
    if os.environ.get("HYDROMODPY_COVERAGE"):
        wrapper = Path(__file__).resolve().parent / "coverage_runner.py"
        command = [sys.executable, str(wrapper), str(script_path), *run_args]
    else:
        command = [sys.executable, str(script_path), *run_args]

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    return completed


def _format_subprocess_failure(
    *,
    script_path: Path,
    command: list[str],
    completed: subprocess.CompletedProcess[str],
    workspace_error: AssertionError | None = None,
) -> str:
    message = (
        f"{script_path.name} failed.\n"
        f"Command: {' '.join(command)}\n"
        f"Return code: {completed.returncode}\n"
        f"Stdout:\n{completed.stdout}\n"
        f"Stderr:\n{completed.stderr}"
    )
    if workspace_error is not None:
        message += f"\nWorkspace resolution failed: {workspace_error}"
    return message


def _build_validation_launcher_config(
    *,
    case_dir: Path,
    config_path: Path,
    solver_name: str,
) -> Path:
    """Materialize one temporary launcher config with validation-only overrides."""
    metadata = load_case_metadata(case_dir)
    base_config_name = str(metadata.get("base_config", "")).strip()
    profile_block = _VALIDATION_PROFILES_BY_SOLVER_AND_CASE.get(solver_name, {}).get(case_dir.name)

    use_base = bool(base_config_name)
    use_profile = profile_block is not None
    if not use_base and not use_profile:
        return config_path
    base_config_path = case_dir / base_config_name if use_base else None
    if base_config_path is not None and not base_config_path.exists() and not use_profile:
        return config_path

    if use_base and base_config_path is not None and base_config_path.exists():
        merged_payload = _merge_toml_payloads(
            _read_toml(base_config_path),
            _read_toml(config_path),
        )
    else:
        merged_payload = _read_toml(config_path)

    if profile_block is not None:
        merged_payload = _merge_toml_payloads(
            merged_payload,
            tomllib.loads(profile_block),
        )

    # Inject a stable run_id so the model folder name is predictable
    # (derived from case_dir name + solver) instead of the temp TOML filename.
    case_id = str(metadata.get("case_id", case_dir.name))
    stable_run_id = _short_validation_name(f"{case_id}_{solver_name}", max_length=48)
    sim_section = merged_payload.setdefault("simulation", {})
    if not sim_section.get("run_id"):
        sim_section["run_id"] = stable_run_id

    tmp_name = f".__validation_runtime_{config_path.stem}_{solver_name}_{os.getpid()}.toml"
    tmp_path = case_dir / tmp_name
    tmp_path.write_text(_dump_toml(merged_payload), encoding="utf-8", newline="\n")
    return tmp_path


def _normalize_validation_config_files(raw_config_files: object) -> dict[str, str] | None:
    """Normalize one optional solver->config mapping from case metadata."""
    if raw_config_files is None:
        return None
    if not isinstance(raw_config_files, Mapping):
        raise TypeError("validation metadata 'config_files' must be a mapping")

    normalized: dict[str, str] = {}
    for key, value in raw_config_files.items():
        solver_name = str(key).strip().lower()
        if solver_name == "":
            raise ValueError("validation metadata 'config_files' cannot contain an empty solver name")
        normalized[solver_name] = str(value)
    return normalized


def _case_has_multiple_solver_configs(metadata: Mapping[str, object]) -> bool:
    """Return True when one case metadata declares more than one solver variant."""
    normalized_config_files = _normalize_validation_config_files(metadata.get("config_files"))
    return normalized_config_files is not None and len(normalized_config_files) > 1


def _resolve_validation_solver_config(
    metadata: dict,
    *,
    solver: str | None = None,
) -> tuple[str, str]:
    """Resolve the solver name and validation config file from case metadata."""
    raw_default_solver = metadata.get("default_solver", "modflownwt")
    default_solver = str(raw_default_solver).strip().lower()
    if default_solver == "":
        raise ValueError("validation default solver name cannot be empty")
    solver_name = default_solver if solver is None else str(solver).strip().lower()
    if solver_name == "":
        raise ValueError("validation solver name cannot be empty")

    normalized_config_files = _normalize_validation_config_files(metadata.get("config_files"))
    if normalized_config_files is None:
        if solver_name != default_solver:
            raise ValueError(
                f"Validation case does not declare a config for solver '{solver_name}'."
            )
        return solver_name, str(metadata.get("config_file", "config_modflownwt.toml"))
    try:
        return solver_name, normalized_config_files[solver_name]
    except KeyError as exc:
        available = ", ".join(sorted(normalized_config_files))
        raise ValueError(
            f"Validation case does not declare a config for solver '{solver_name}'. "
            f"Available solvers: {available}"
        ) from exc


def run_launcher_validation_case(
    *,
    case_dir: Path,
    test_file: str | Path,
    timeout: int = 1800,
    solver: str | None = None,
) -> ValidationRunResult:
    """Run one launcher-based validation case and resolve its output workspace.

    Uses ``python -m hydromodpy run`` (the production CLI entry point)
    instead of the removed ``launcher_simulation.py`` script.
    """
    metadata = load_case_metadata(case_dir)
    solver_name, config_file = _resolve_validation_solver_config(metadata, solver=solver)
    workspace_cfg = dict(metadata.get("workspace", {}))

    case_id = str(metadata.get("case_id", case_dir.name))
    use_solver_suffix = solver is not None or _case_has_multiple_solver_configs(metadata)
    run_name = f"{case_id}_{solver_name}" if use_solver_suffix else case_id
    out_path = resolve_validation_results_dir(test_file=test_file, run_name=run_name)

    config_path = case_dir / config_file
    run_config_path = _build_validation_launcher_config(
        case_dir=case_dir,
        config_path=config_path,
        solver_name=solver_name,
    )

    env = os.environ.copy()
    env["HYDROMODPY_PROJECT_ROOT"] = str(out_path)
    env.setdefault("MPLBACKEND", "Agg")

    command = [
        sys.executable, "-m", "hydromodpy", "run", str(run_config_path),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    finally:
        if run_config_path != config_path and run_config_path.exists():
            try:
                remove_file_with_retry(run_config_path)
            except PermissionError:
                pass

    if completed.returncode != 0:
        workspace_error: AssertionError | None = None
        try:
            resolve_model_workspace(
                out_path,
                watershed_name=workspace_cfg.get("watershed_name"),
                results_folder_name=str(workspace_cfg.get("results_folder_name", "results_simulations")),
                model_name=workspace_cfg.get("model_name"),
            )
        except AssertionError as exc:
            workspace_error = exc
        raise AssertionError(
            _format_subprocess_failure(
                script_path=Path("hydromodpy.__main__"),
                command=command,
                completed=completed,
                workspace_error=workspace_error,
            )
        )

    store, sim_id = _discover_result_store(out_path)

    try:
        model_ws, postprocess_dir, particles_dir = resolve_model_workspace(
            out_path,
            watershed_name=workspace_cfg.get("watershed_name"),
            results_folder_name=str(workspace_cfg.get("results_folder_name", "results_simulations")),
            model_name=workspace_cfg.get("model_name"),
        )
    except AssertionError:
        if store is not None and sim_id is not None:
            model_ws = out_path
            postprocess_dir = out_path
            particles_dir = out_path
        else:
            raise AssertionError(
                _format_subprocess_failure(
                    script_path=Path("hydromodpy.__main__"),
                    command=command,
                    completed=completed,
                    workspace_error=AssertionError(
                        f"Results folder not found and no SimulationCatalog "
                        f"available at {out_path}"
                    ),
                )
            )

    return ValidationRunResult(
        case_dir=case_dir,
        solver_name=solver_name,
        out_path=out_path,
        model_ws=model_ws,
        postprocess_dir=postprocess_dir,
        particles_dir=particles_dir,
        run_returncode=int(completed.returncode),
        run_stdout=str(completed.stdout),
        run_stderr=str(completed.stderr),
        store=store,
        sim_id=sim_id,
    )
