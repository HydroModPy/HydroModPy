"""Runtime helpers shared by validation cases and validation tests."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from validation_cases.shared.loaders import load_case_metadata

REPO_ROOT = Path(__file__).resolve().parents[2]

_WINDOWS_VALIDATION_PATH_LIMIT = 240
_VALIDATION_GENERATED_PATH_HEADROOM = 96
_VALIDATION_COMPONENT_LENGTHS = (28, 24, 20, 16, 12)

_NWT_VALIDATION_PROFILE_SIMPLE = """[modflownwt.runtime.nwt]
version = "mfnwt"
listunit = 2
verbose = false
headtol = 1e-6
fluxtol = 1e-4
maxiterout = 500
thickfact = 1e-5
linmeth = 1
iprnwt = 0
ibotav = 1
options = "SIMPLE"
continue_run = false
backflag = 0
stoptol = 1e-10

[modflownwt.runtime.dis]
itmuni = 1

[modflownwt.runtime.bas]
hnoflo = -9999.0

[modflownwt.runtime.upw]
iphdry = 1
hdry = -100.0
layvka = 1

[modflownwt.runtime.evt]
nevtop = 3
ievt = 1
ipakcb = 1

[modflownwt.runtime.oc]
compact = true

[modflownwt.runtime.wel]
ipakcb = 1

[modflownwt.runtime.lmt]
output_file_name = "mt3d_link.ftl"
extension = "lmt8"
output_format = "unformatted"

[modflownwt.process_specific]
vka = 1.0
exdp = "1.0 m"
"""

_NWT_VALIDATION_PROFILE_COMPLEX = """[modflownwt.runtime.nwt]
version = "mfnwt"
listunit = 2
verbose = false
headtol = 1e-6
fluxtol = 1e-4
maxiterout = 1000
thickfact = 1e-5
linmeth = 1
iprnwt = 0
ibotav = 1
options = "COMPLEX"
continue_run = false
backflag = 0
stoptol = 1e-10

[modflownwt.runtime.dis]
itmuni = 1

[modflownwt.runtime.bas]
hnoflo = -9999.0

[modflownwt.runtime.upw]
iphdry = 1
hdry = -100.0
layvka = 1

[modflownwt.runtime.evt]
nevtop = 3
ievt = 1
ipakcb = 1

[modflownwt.runtime.oc]
compact = true

[modflownwt.runtime.wel]
ipakcb = 1

[modflownwt.runtime.lmt]
output_file_name = "mt3d_link.ftl"
extension = "lmt8"
output_format = "unformatted"

[modflownwt.process_specific]
vka = 1.0
exdp = "1.0 m"
"""

_VALIDATION_PROFILES_BY_SOLVER_AND_CASE: dict[str, dict[str, str]] = {
    "modflow_nwt": {
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
    # When the override changes a discriminator (``kind``), drop the inherited
    # body so leftover sibling keys do not leak into the new variant. Pydantic
    # v2 ``extra='forbid'`` rejects them on the next load otherwise.
    if "kind" in override and "kind" in base and override["kind"] != base["kind"]:
        return {key: _clone_toml_value(value) for key, value in override.items()}
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if (
            isinstance(existing, Mapping)
            and isinstance(value, Mapping)
            and "kind" in existing
            and "kind" in value
            and existing.get("kind") != value.get("kind")
        ):
            merged[key] = dict(value)
            continue
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


def _clone_toml_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _clone_toml_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_toml_value(item) for item in value]
    return value


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


def _resolve_path_best_effort(path: Path) -> Path:
    """Resolve *path* without failing only because the target is not creatable yet."""
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()


def _default_validation_results_root() -> Path:
    return Path(tempfile.gettempdir()) / "hydromodpy_validation_outputs"


def _fallback_validation_results_root(base_out_path: str) -> Path:
    digest = hashlib.sha1(str(base_out_path).encode("utf-8")).hexdigest()[:10]
    return Path(tempfile.gettempdir()) / f"hydromodpy_validation_outputs_{digest}"


def _windows_path_budget_exceeded(path: Path, *, headroom: int = 0) -> bool:
    """Return True when *path* is likely to exceed Windows path limits."""
    if os.name != "nt":
        return False
    return len(str(path)) + int(headroom) >= _WINDOWS_VALIDATION_PATH_LIMIT


def _candidate_validation_results_dir(
    *,
    results_root: Path,
    test_file: str | Path,
    run_name: str,
    component_length: int,
) -> Path:
    test_stem = _short_validation_name(
        Path(test_file).resolve().stem,
        max_length=component_length,
    )
    safe_run_name = _short_validation_name(run_name, max_length=component_length)
    return results_root / test_stem / safe_run_name


def _resolve_budgeted_validation_results_dir(
    *,
    results_root: Path,
    test_file: str | Path,
    run_name: str,
) -> Path:
    last_candidate: Path | None = None
    for component_length in _VALIDATION_COMPONENT_LENGTHS:
        candidate = _candidate_validation_results_dir(
            results_root=results_root,
            test_file=test_file,
            run_name=run_name,
            component_length=component_length,
        )
        last_candidate = candidate
        if not _windows_path_budget_exceeded(
            candidate,
            headroom=_VALIDATION_GENERATED_PATH_HEADROOM,
        ):
            return candidate
    assert last_candidate is not None
    return last_candidate


def resolve_validation_results_dir(*, test_file: str | Path, run_name: str) -> Path:
    """Create one deterministic output directory for a validation run."""
    base_out_path = os.environ.get("HMP_OUT_PATH")
    if base_out_path:
        results_root = _resolve_path_best_effort(Path(base_out_path)) / "validation"
        probe_dir = results_root / f".__probe_{os.getpid()}_{time.time_ns()}"
        try:
            results_root.mkdir(parents=True, exist_ok=True)
            probe_dir.mkdir()
        except OSError:
            results_root = _fallback_validation_results_root(base_out_path)
        else:
            probe_dir.rmdir()
    else:
        results_root = _default_validation_results_root()

    out_dir = _resolve_budgeted_validation_results_dir(
        results_root=results_root,
        test_file=test_file,
        run_name=run_name,
    )
    if base_out_path and _windows_path_budget_exceeded(
        out_dir,
        headroom=_VALIDATION_GENERATED_PATH_HEADROOM,
    ):
        results_root = _fallback_validation_results_root(base_out_path)
        out_dir = _resolve_budgeted_validation_results_dir(
            results_root=results_root,
            test_file=test_file,
            run_name=run_name,
        )

    parent_dir = out_dir.parent
    safe_run_name = out_dir.name
    if parent_dir.is_dir():
        stale_prefix = f"{safe_run_name}_"
        for sibling in parent_dir.iterdir():
            if (
                sibling == out_dir
                or not sibling.is_dir()
                or not sibling.name.startswith(stale_prefix)
            ):
                continue
            stale_suffix = sibling.name[len(stale_prefix) :]
            if len(stale_suffix) == 8 and all(
                char in "0123456789abcdef" for char in stale_suffix.lower()
            ):
                remove_tree_with_retry(sibling)
    if out_dir.exists():
        remove_tree_with_retry(out_dir)
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
                p for p in results_dir.iterdir() if p.is_dir() and p.name.lower() == target
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
    """Try to open a Catalog from a project directory and find its sim_id.

    Returns ``(store, sim_id)`` on success, ``(None, None)`` on failure.
    The caller is responsible for closing the store when done.
    """
    from hydromodpy.core.state.paths import catalog_path_for

    if not catalog_path_for(project_path).exists():
        return None, None
    from hydromodpy.results.catalog import Catalog

    store = Catalog(project_path)
    sims = store.list_simulations()
    if sims.empty:
        store.close()
        return None, None
    sim_id = str(sims.iloc[-1]["sim_id"])
    return store, sim_id


def _normalize_validation_field_series(
    fields: Mapping[str, Any],
) -> dict[str, list[tuple[int, np.ndarray]]]:
    """Normalize validation field payloads to sorted timestep series."""
    payloads: dict[str, list[tuple[int, np.ndarray]]] = {}
    for variable, raw_series in fields.items():
        if isinstance(raw_series, Mapping):
            raw_items = raw_series.items()
        else:
            raw_items = raw_series
        series = [
            (int(time_key), np.asarray(values, dtype="float64")) for time_key, values in raw_items
        ]
        if not series:
            continue
        payloads[str(variable)] = sorted(series, key=lambda item: item[0])
    return payloads


def write_validation_fields_to_store(
    *,
    out_path: Path,
    fields: Mapping[str, Any],
    solver_name: str,
    flow_regime: str = "steady",
) -> tuple[Any, str | None]:
    """Write in-memory validation field series to a Catalog."""
    payloads = _normalize_validation_field_series(fields)
    if not payloads:
        return None, None

    first_values_by_variable = [series[0][1] for series in payloads.values()]
    shape_reference = next(
        (values for values in first_values_by_variable if values.ndim == 2),
        first_values_by_variable[0],
    )
    n_cells = int(shape_reference.size)
    n_timesteps = max(len(series) for series in payloads.values())
    sim_id = str(uuid.uuid4())

    from hydromodpy.results.catalog import Catalog

    store = Catalog(out_path)
    registration = store.register_simulation(
        sim_id,
        project=Path(out_path).name,
        solver=solver_name,
        name=f"{Path(out_path).name}_{solver_name}",
        solver_category="distributed",
        flow_regime=flow_regime,
        n_cells=n_cells,
        n_layers=1,
        n_timesteps=n_timesteps,
    )
    if registration.zarr is not None:
        registration.zarr.close()

    if shape_reference.ndim == 2:
        nrow, ncol = shape_reference.shape
        store.write_geographic_metadata(
            sim_id,
            {
                "nrow": int(nrow),
                "ncol": int(ncol),
            },
        )

    try:
        for variable, series in payloads.items():
            for write_index, (_time_key, values) in enumerate(series):
                store.write_field(
                    sim_id,
                    variable,
                    write_index,
                    np.asarray(values, dtype="float64").reshape(-1),
                    n_timesteps=n_timesteps if write_index == 0 else None,
                    subgroup="derived",
                )
    except Exception:
        store.close()
        raise

    return store, sim_id


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
    env["HMP_PROJECT_ROOT"] = str(out_path)
    env["HMP_WORKSPACE"] = str(out_path)
    env["HMP_AUTO_REGISTER_WORKSPACE"] = "0"
    env.setdefault("MPLBACKEND", "Agg")
    if extra_env:
        for key, value in extra_env.items():
            env[key] = str(value)

    run_args = [] if script_args is None else list(script_args)
    if os.environ.get("HMP_COVERAGE"):
        wrapper = Path(__file__).resolve().parent / "coverage_runner.py"
        command = [sys.executable, str(wrapper), str(script_path), *run_args]
    else:
        command = [sys.executable, str(script_path), *run_args]

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
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
    """Materialize one temporary launcher config with validation-only overrides.

    Always materializes a temp file so ``hmp run`` sees validation-only
    runtime overrides without mutating the source TOML.
    """
    metadata = load_case_metadata(case_dir)
    base_config_name = str(metadata.get("base_config", "")).strip()
    profile_block = _VALIDATION_PROFILES_BY_SOLVER_AND_CASE.get(solver_name, {}).get(case_dir.name)

    use_base = bool(base_config_name)
    base_config_path = case_dir / base_config_name if use_base else None

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

    # Inject a stable simulation name so the model folder name is predictable
    # (derived from case_dir name + solver) instead of the temp TOML filename.
    # ``[simulation] name`` is the run identity (``run_id`` was removed by the
    # simulation-management v2 schema); it must stay unique per solver.
    case_id = str(metadata.get("case_id", case_dir.name))
    stable_name = _short_validation_name(f"{case_id}_{solver_name}", max_length=48)
    sim_section = merged_payload.setdefault("simulation", {})
    sim_section["name"] = stable_name

    if "workflow" not in merged_payload:
        raise ValueError(f"{config_path} must define [workflow] or inherit it from base_config.")

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
            raise ValueError(
                "validation metadata 'config_files' cannot contain an empty solver name"
            )
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
    raw_default_solver = metadata.get("default_solver", "modflow_nwt")
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

    Uses ``python -m hydromodpy run`` through the production CLI entry point.
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
    env["HMP_PROJECT_ROOT"] = str(out_path)
    env["HMP_WORKSPACE"] = str(out_path)
    env["HMP_AUTO_REGISTER_WORKSPACE"] = "0"
    env.setdefault("MPLBACKEND", "Agg")

    # Validation runs never persist ``hydromodpy.lock``: the lockfile would
    # land inside ``validation_cases/<case>/`` and pollute git status after
    # every test invocation. Reproducibility info already lives in the case
    # config and result store.
    command = [
        sys.executable,
        "-m",
        "hydromodpy",
        "run",
        "--no-lock",
        str(run_config_path),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
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
                results_folder_name=str(
                    workspace_cfg.get("results_folder_name", "results_simulations")
                ),
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
            results_folder_name=str(
                workspace_cfg.get("results_folder_name", "results_simulations")
            ),
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
                        f"Results folder not found and no Catalog available at {out_path}"
                    ),
                )
            ) from None

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
