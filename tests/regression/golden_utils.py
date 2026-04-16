"""
Shared utilities for regression tests based on golden references.

Why this file exists
--------------------
Most regression tests follow the exact same pattern:

1. run an example workflow,
2. read a subset of generated outputs,
3. compute compact numeric "signatures",
4. compare them against a JSON golden reference.

Without this module, each test file would duplicate process management,
path-resolution logic, signature code, and comparison rules.

Design principles
-----------------
- Keep individual tests short and readable.
- Fail with explicit, actionable assertion messages.
- Be robust to small floating-point noise.
- Skip (instead of fail) when the environment is missing required binaries
  or external network access.
"""

from __future__ import annotations

import json
import os
import platform
import gc
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from hydromodpy.solver.modflow_common import ensure_platform_executable


# Repository root for every path assembled in the regression helpers.
REPO_ROOT = Path(__file__).resolve().parents[2]
REGRESSION_GOLDENS_ROOT = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
)

# Common MODFLOW outputs checked by many tests.
# Individual tests can override this list when needed.
DEFAULT_MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
]


def _rmtree_onerror(func, path, exc_info) -> None:
    """Retry one failed ``rmtree`` step after clearing a read-only bit.

    Windows test runs sometimes inherit read-only flags on generated artefacts.
    ``shutil.rmtree`` can recover from that case by marking the current path
    writable and replaying the failed removal callback once.
    """

    del exc_info
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        # Some locked files reject direct bit flips. Keep the cleanup loop alive
        # and let the outer retry logic handle the transient lock.
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
    try:
        func(path)
    except OSError:
        # Let ``remove_tree_with_retry`` retry the whole tree once the lock clears.
        pass


def remove_tree_with_retry(
    path: Path,
    *,
    retries: int = 12,
    base_delay_s: float = 0.5,
) -> None:
    """Remove one directory tree with a few retries for transient Windows locks.

    HydroModPy regression outputs contain GIS artefacts (`.shp`, `.dbf`, `.tif`)
    that can remain briefly locked on Windows after a previous run, even though
    the producing process has already exited. Retrying the cleanup avoids
    spurious test failures when the lock clears a fraction of a second later.
    """

    if not path.exists():
        return

    last_error: OSError | None = None
    for attempt in range(retries):
        try:
            gc.collect()
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


def load_golden_reference(path: Path) -> dict:
    """
    Load a golden reference JSON file.

    Parameters
    ----------
    path:
        Path to the golden JSON file.

    Returns
    -------
    dict
        Parsed JSON payload.
    """
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def load_json_payload(path: Path) -> dict:
    """Load one JSON file into a plain dictionary."""
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def resolve_tiered_golden_file(
    *,
    test_file: str | Path,
    filename: str,
) -> Path:
    """
    Build the canonical golden path for one regression test file.

    Goldens are tiered by test location:
    - tests under ``tests/regression/extensive`` -> ``.../golden_references/extensive/``
    - tests under ``tests/regression/fast`` -> ``.../golden_references/fast/``
    """
    file_path = Path(test_file).resolve()
    file_parts = set(file_path.parts)
    tier = "extensive" if "extensive" in file_parts else "fast"
    return REGRESSION_GOLDENS_ROOT / tier / str(filename)


def resolve_tiered_results_dir(
    *,
    test_file: str | Path,
    run_name: str,
) -> Path:
    """
    Build and prepare one deterministic output directory for a regression test.

    Outputs are tiered by test location under ``HYDROMODPY_OUT_PATH`` when set:
    - ``.../fast/<run_name>/``
    - ``.../extensive/<run_name>/``

    If ``HYDROMODPY_OUT_PATH`` is not set, a deterministic temporary root is
    used: ``<tempdir>/hydromodpy_regression_outputs``.

    The target directory is cleaned before each run to avoid stale artifacts.
    """
    base_out_path = os.environ.get("HYDROMODPY_OUT_PATH")
    if base_out_path:
        results_root = Path(base_out_path).expanduser().resolve()
    else:
        results_root = (
            Path(tempfile.gettempdir())
            / "hydromodpy_regression_outputs"
        )
    file_path = Path(test_file).resolve()
    file_parts = set(file_path.parts)
    tier = "extensive" if "extensive" in file_parts else "fast"
    out_dir = results_root / tier / str(run_name)
    if out_dir.exists():
        remove_tree_with_retry(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def write_golden_reference(path: Path, payload: dict) -> None:
    """
    Persist a golden reference JSON file using stable formatting.

    Notes
    -----
    - Parent folders are created automatically.
    - Pretty printing is kept stable to make diffs review-friendly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def load_npy_dict(path: Path) -> dict:
    """
    Load a `.npy` file that contains a serialized Python dictionary.

    Expected format in this project is typically:
        {timestep_index: 2D_or_3D_array, ...}

    Notes
    -----
    `allow_pickle=True` is required because HydroModPy stores dictionaries
    directly in `.npy` files for several post-processing outputs.
    """
    return np.load(path, allow_pickle=True).item()


def array_stats(values) -> dict:
    """
    Compute compact, stable statistics from a numeric array-like input.

    The function explicitly ignores non-finite values (`NaN`, `+/-Inf`) so
    signatures remain robust across minor runtime/environment differences.

    Returned metrics are intentionally small and interpretable:
    - `count`: number of finite values,
    - `mean`: arithmetic mean,
    - `p50`: median,
    - `p95`: upper-tail indicator.
    """
    arr = np.asarray(values, dtype=float)
    # Keep only finite values to avoid unstable statistics when outputs include
    # masked cells or undefined values.
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"count": 0, "mean": None, "p50": None, "p95": None}
    return {
        "count": int(finite.size),
        "mean": float(finite.mean()),
        "p50": float(np.percentile(finite, 50)),
        "p95": float(np.percentile(finite, 95)),
    }


def array_signature(values) -> dict:
    """Build one compact signature from a generic numeric array."""
    arr = np.asarray(values, dtype=float)
    sig = array_stats(arr)
    sig["shape"] = list(arr.shape)
    if sig["count"] == 0:
        sig["sum"] = None
    else:
        finite = arr[np.isfinite(arr)]
        sig["sum"] = float(finite.sum())
    return sig


def assert_stats(
    actual: dict,
    expected: dict,
    *,
    rel: float = 1e-4,
    abs_tol: float = 1e-6,
) -> None:
    """
    Compare two statistical signatures with a small numeric tolerance.

    `count` must match exactly, while floating statistics are compared with
    `pytest.approx` to tolerate tiny floating-point noise.

    This keeps tests stable across platforms and BLAS implementations while
    still detecting meaningful regressions.

    Parameters
    ----------
    rel:
        Relative tolerance forwarded to ``pytest.approx``.
    abs_tol:
        Absolute tolerance forwarded to ``pytest.approx``.
    """
    assert actual["count"] == expected["count"]
    for key in ("mean", "p50", "p95"):
        if expected[key] is None:
            assert actual[key] is None
        else:
            assert actual[key] == pytest.approx(expected[key], rel=rel, abs=abs_tol)


def modflow_signature(path: Path) -> dict:
    """
    Build a compact signature from a MODFLOW `.npy` output.

    Convention used here:
    - each file stores a dictionary `{timestep -> array}`,
    - regression compares the *last* available timestep because that usually
      captures accumulated model behavior.
    """
    data = load_npy_dict(path)
    assert len(data) > 0

    # Use the final timestep to summarize the end state of the run.
    last_timestep = sorted(data.keys())[-1]
    arr = np.asarray(data[last_timestep], dtype=float)

    sig = array_stats(arr)
    sig["shape"] = list(arr.shape)
    sig["timestep"] = int(last_timestep)
    sig["available_timesteps"] = len(data)

    if sig["count"] == 0:
        sig["sum"] = None
    else:
        finite = arr[np.isfinite(arr)]
        sig["sum"] = float(finite.sum())
    return sig


def snapshot_signature(path: Path) -> dict:
    """
    Build a MODPATH signature from a `.dbf` snapshot file.

    Only a compact subset is retained:
    - row count,
    - statistics of the `time` column.

    This is intentionally lightweight: DBF row ordering can vary, but count
    and time distribution are stable high-value indicators for regressions.
    """
    table = gpd.read_file(path)
    assert "time" in table.columns, f"Column 'time' not found in {path}"
    return {
        "n_rows": int(len(table)),
        "time": array_stats(np.asarray(table["time"], dtype=float)),
    }


def collect_store_modpath_signatures(store, sim_id: str) -> dict:
    """Collect MODPATH signatures from the SimulationCatalog pathlines group."""
    result = {}
    try:
        grp = store.open_zarr_group(sim_id)
        pathlines_grp = grp.get("pathlines")
        if pathlines_grp is None:
            return result

        # Starting endpoints (like starting.dbf)
        if "endpoint_x" in pathlines_grp:
            time_arr = np.asarray(pathlines_grp["endpoint_time"][:], dtype=float)
            result["starting.dbf"] = {
                "n_rows": int(len(time_arr)),
                "time": array_stats(time_arr),
            }
            # Ending endpoints = same data for backward tracking
            result["ending.dbf"] = result["starting.dbf"]

        # Full pathlines (if available)
        if "time" in pathlines_grp:
            time_arr = np.asarray(pathlines_grp["time"][:], dtype=float)
            n_particles = time_arr.shape[0]
            valid_times = time_arr[np.isfinite(time_arr)]
            result["pathlines"] = {
                "n_rows": n_particles,
                "time": array_stats(valid_times),
            }
    except (KeyError, Exception):
        pass

    return result


def collect_modflow_signatures(postprocess_dir: Path, names: list[str]) -> dict:
    """
    Collect MODFLOW signatures for a list of output base names.

    Each name is a base filename (without extension). For example:
    `watertable_elevation` -> `<postprocess_dir>/watertable_elevation.npy`.
    """
    return {name: modflow_signature(postprocess_dir / f"{name}.npy") for name in names}


def collect_modpath_signatures(particles_dir: Path, filenames: list[str]) -> dict:
    """
    Collect MODPATH signatures for a list of particle snapshot filenames.
    """
    return {name: snapshot_signature(particles_dir / name) for name in filenames}


def collect_npz_signatures(
    npz_path: Path,
    names: list[str] | None = None,
) -> dict:
    """Collect compact signatures for arrays stored in one `.npz` file."""
    with np.load(npz_path) as payload:
        ordered_names = sorted(payload.files) if names is None else list(names)
        return {
            name: array_signature(np.asarray(payload[name], dtype=float))
            for name in ordered_names
        }


def collect_json_signatures(
    json_path: Path,
    *,
    keys: list[str] | None = None,
) -> dict:
    """Collect selected scalar/list JSON fields for regression comparison."""
    payload = load_json_payload(json_path)
    ordered_keys = sorted(payload) if keys is None else list(keys)
    return {key: payload[key] for key in ordered_keys}


# -- SimulationCatalog-based signature collection ----------------------------


def _open_result_store(workspace_path: Path):
    """Open a read-only SimulationCatalog for golden comparison."""
    from hydromodpy.results.catalog import SimulationCatalog
    return SimulationCatalog(workspace_path)


def _resolve_sim_id(store, sim_name: str | None = None) -> str:
    """Return the sim_id of the most recent (or only) simulation as a string."""
    sims = store.list_simulations()
    if sims.empty:
        raise FileNotFoundError("No simulations in SimulationCatalog")
    if sim_name is not None:
        match = sims[sims["name"] == sim_name]
        if not match.empty:
            return str(match.iloc[0]["sim_id"])
    # DuckDB may return UUID objects — always convert to str.
    return str(sims.iloc[-1]["sim_id"])


def store_field_signature(store, sim_id: str, variable: str) -> dict:
    """Build a modflow-compatible signature from a SimulationCatalog field.

    Reads the last available timestep and computes the same stats as
    ``modflow_signature`` so golden comparison is identical.
    """
    # Scan all available timesteps for this variable (up to a reasonable max).
    available = 0
    for t in range(10000):
        try:
            store.query_field(sim_id, variable, t)
            available = t + 1
        except (KeyError, IndexError, Exception) as exc:
            # Zarr raises BoundsCheckError (subclass of IndexError) when out of range.
            if "out of bounds" in str(exc).lower() or isinstance(exc, (KeyError, IndexError)):
                break
            break

    if available == 0:
        raise KeyError(f"Variable '{variable}' has no timesteps for sim={sim_id}")

    last_t = available - 1
    arr = np.asarray(store.query_field(sim_id, variable, last_t), dtype=float)
    # Flatten multi-layer to 1D (same as legacy .npy which stored flat arrays).
    if arr.ndim > 1:
        arr = arr.reshape(-1)

    sig = array_stats(arr)
    sig["shape"] = list(arr.shape)
    sig["timestep"] = last_t
    sig["available_timesteps"] = available

    if sig["count"] == 0:
        sig["sum"] = None
    else:
        finite = arr[np.isfinite(arr)]
        sig["sum"] = float(finite.sum())
    return sig


def collect_store_field_signatures(
    store,
    sim_id: str,
    names: list[str],
) -> dict:
    """Collect SimulationCatalog field signatures — drop-in for ``collect_modflow_signatures``."""
    result = {}
    for name in names:
        try:
            result[name] = store_field_signature(store, sim_id, name)
        except KeyError:
            # Variable may not exist (e.g. accumulation_flux when no drain).
            # Mirror legacy behavior: skip silently so golden comparison
            # only covers variables that exist.
            pass
    return result


def collect_store_npz_signatures(
    solver_output_dir: Path,
    names: list[str],
) -> dict:
    """Collect .npz signatures from solver scratch — same as ``collect_npz_signatures``."""
    npz_path = solver_output_dir / "_boussinesq_state_history.npz"
    return collect_npz_signatures(npz_path, names)


def collect_store_json_signatures(
    solver_output_dir: Path,
    *,
    keys: list[str] | None = None,
) -> dict:
    """Collect JSON signatures from solver scratch."""
    json_path = solver_output_dir / "_boussinesq_summary.json"
    return collect_json_signatures(json_path, keys=keys)


def assert_modflow_signatures(
    actual_by_name: dict,
    expected_by_name: dict,
    *,
    rel: float = 1e-4,
    abs_tol: float = 1e-6,
) -> None:
    """
    Validate MODFLOW signatures against golden expectations.

    Comparison strategy:
    1. same set of outputs,
    2. same structural metadata (`shape`, optionally timestep metadata),
    3. same statistics within tolerance.
    """
    assert set(actual_by_name) == set(expected_by_name)
    for name, expected in expected_by_name.items():
        actual = actual_by_name[name]
        assert actual["shape"] == expected["shape"]
        if "timestep" in expected:
            assert actual["timestep"] == expected["timestep"]
        if "available_timesteps" in expected:
            assert actual["available_timesteps"] == expected["available_timesteps"]
        assert_stats(actual, expected, rel=rel, abs_tol=abs_tol)
        if expected["sum"] is None:
            assert actual["sum"] is None
        else:
            assert actual["sum"] == pytest.approx(expected["sum"], rel=rel, abs=abs_tol)


def assert_modpath_signatures(actual_by_name: dict, expected_by_name: dict) -> None:
    """
    Validate MODPATH `.dbf` signatures against golden expectations.

    We compare only the stable parts of the signature:
    - number of rows,
    - summary stats on `time`.
    """
    assert set(actual_by_name) == set(expected_by_name)
    for filename, expected in expected_by_name.items():
        actual = actual_by_name[filename]
        assert actual["n_rows"] == expected["n_rows"]
        assert_stats(actual["time"], expected["time"])


def assert_array_signatures(
    actual_by_name: dict,
    expected_by_name: dict,
    *,
    rel: float = 1e-4,
    abs_tol: float = 1e-6,
) -> None:
    """Validate generic array signatures against golden expectations."""
    assert set(actual_by_name) == set(expected_by_name)
    for name, expected in expected_by_name.items():
        actual = actual_by_name[name]
        assert actual["shape"] == expected["shape"]
        assert_stats(actual, expected, rel=rel, abs_tol=abs_tol)
        if expected["sum"] is None:
            assert actual["sum"] is None
        else:
            assert actual["sum"] == pytest.approx(expected["sum"], rel=rel, abs=abs_tol)


def _assert_json_signature_value(
    actual,
    expected,
    *,
    rel: float,
    abs_tol: float,
) -> None:
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        assert actual == expected
        return
    if isinstance(expected, int) and not isinstance(expected, bool):
        assert actual == expected
        return
    if isinstance(expected, float):
        assert float(actual) == pytest.approx(expected, rel=rel, abs=abs_tol)
        return
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected, strict=True):
            _assert_json_signature_value(
                actual_item,
                expected_item,
                rel=rel,
                abs_tol=abs_tol,
            )
        return
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        assert_json_signatures(actual, expected, rel=rel, abs_tol=abs_tol)
        return
    raise TypeError(f"Unsupported JSON signature value type: {type(expected)!r}")


def assert_json_signatures(
    actual: dict,
    expected: dict,
    *,
    rel: float = 1e-4,
    abs_tol: float = 1e-6,
) -> None:
    """Validate one JSON signature payload with tolerant float comparison."""
    assert set(actual) == set(expected)
    for key, expected_value in expected.items():
        _assert_json_signature_value(
            actual[key],
            expected_value,
            rel=rel,
            abs_tol=abs_tol,
        )


def assert_required_executables(
    repo_root: Path = REPO_ROOT,
    *,
    require_modflow: bool = True,
    require_modflow6: bool = False,
    require_modpath: bool = True,
    require_mt3dms: bool = False,
) -> None:
    """
    Ensure bundled solver executables are available for this platform.

    The function *skips* the test (instead of failing) when binaries are
    missing, because this is an environment issue, not a model-regression
    issue.
    """
    # Resolve executable names from OS-specific bundled folders.
    if platform.system() == "Windows":
        mf_exe = repo_root / "bin" / "win" / "mfnwt.exe"
        mf6_exe = repo_root / "bin" / "win" / "mf6.exe"
        mp_exe = repo_root / "bin" / "win" / "mp6.exe"
        mt_exe = repo_root / "bin" / "win" / "mt3d-usgs_1.1.0_64.exe"
    elif platform.system() == "Linux":
        mf_exe = repo_root / "bin" / "linux" / "mfnwt"
        mf6_exe = repo_root / "bin" / "linux" / "mf6"
        mp_exe = repo_root / "bin" / "linux" / "mp6"
        mt_exe = repo_root / "bin" / "linux" / "mt3dusgs"
    elif platform.system() == "Darwin":
        mf_exe = repo_root / "bin" / "mac" / "mfnwt"
        mf6_exe = repo_root / "bin" / "mac" / "mf6"
        mp_exe = repo_root / "bin" / "mac" / "mp6"
        mt_exe = repo_root / "bin" / "mac" / "mt3dusgs"
    else:
        pytest.skip(f"Unsupported platform for bundled executables: {platform.system()}")

    required_paths = []
    if require_modflow:
        required_paths.append(mf_exe)
    if require_modflow6:
        required_paths.append(mf6_exe)
    if require_modpath:
        required_paths.append(mp_exe)
    if require_mt3dms:
        required_paths.append(mt_exe)

    missing = [str(p) for p in required_paths if not p.exists()]
    if missing:
        pytest.skip(f"Required executables are missing: {missing}")
    for path in required_paths:
        ensure_platform_executable(path)


def require_url_available(url: str, *, timeout: float = 15.0, attempts: int = 3) -> None:
    """
    Require an external HTTP endpoint to be reachable, otherwise skip the test.

    This keeps network-dependent regression tests stable in CI/environments
    where outbound internet connectivity is not guaranteed.

    The helper is intentionally permissive:
    - try a few times,
    - skip instead of fail if the endpoint is unavailable.
    """
    try:
        import requests
    except Exception as exc:  # pragma: no cover - import failure is environment-specific
        pytest.skip(f"Cannot import 'requests' to probe network dependency: {exc}")

    last_error = None
    for _ in range(attempts):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return
        except Exception as exc:  # pragma: no cover - depends on network conditions
            last_error = exc

    pytest.skip(f"External service unavailable ({url}): {last_error}")


def resolve_model_workspace(
    out_path: Path,
    *,
    watershed_name: str | None = None,
    results_folder_name: str = "results_simulations",
    model_name: str | None = None,
    model_name_prefix: str | None = None,
) -> tuple[Path, Path, Path]:
    """
    Resolve generated workspace folders for a completed example run.

    Searches ``results_folder_name`` first, then falls back to
    ``.solver_scratch/`` (new DB-only layout).

    Returns
    -------
    tuple
        (model_ws, postprocess_dir, particles_dir)
    """
    # Try new layout first (.solver_scratch), then legacy (results_simulations).
    for folder_name in (".solver_scratch", results_folder_name):
        results_dir = out_path / folder_name
        if not results_dir.is_dir():
            continue

        if model_name is not None:
            model_ws = results_dir / model_name
            if model_ws.is_dir():
                postprocess_dir = model_ws / "_postprocess"
                particles_dir = postprocess_dir / "_particles"
                return model_ws, postprocess_dir, particles_dir
        else:
            model_dirs = sorted(
                p for p in results_dir.iterdir()
                if p.is_dir()
                and not p.name.startswith("_")
                and (model_name_prefix is None or p.name.startswith(model_name_prefix))
            )
            if model_dirs:
                model_ws = model_dirs[0]
                postprocess_dir = model_ws / "_postprocess"
                particles_dir = postprocess_dir / "_particles"
                return model_ws, postprocess_dir, particles_dir

    # Neither layout found — give a clear error.
    raise AssertionError(
        f"Results folder not found in {out_path} "
        f"(checked .solver_scratch/ and {results_folder_name}/)"
    )


def resolve_first_model_workspace(
    out_path: Path,
    *,
    results_folder_name: str = "results_simulations",
) -> tuple[Path, Path, Path]:
    """
    Backward-compatible wrapper that selects first watershed/model folders.
    """
    return resolve_model_workspace(out_path, results_folder_name=results_folder_name)


def update_or_assert_goldens(
    *,
    actual: dict,
    golden_reference_file: Path,
    update_goldens: bool,
) -> None:
    """
    Either refresh golden references or assert current outputs against them.

    Parameters
    ----------
    actual:
        Runtime signature payload built by the test.
    golden_reference_file:
        Path to the JSON golden file.
    update_goldens:
        If True, overwrite the golden file with `actual`.
    """
    # Update mode is explicit (`--update-goldens`) and overwrites JSON files.
    if update_goldens:
        write_golden_reference(golden_reference_file, actual)
        return

    expected = load_golden_reference(golden_reference_file)

    # Validate only sections present in `actual`.
    # This supports tests that check only MODFLOW, only MODPATH, or both.
    if "modflow_expected" in actual:
        assert "modflow_expected" in expected
        assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])

    if "modpath_expected" in actual:
        assert "modpath_expected" in expected
        assert_modpath_signatures(actual["modpath_expected"], expected["modpath_expected"])

    if "transport_expected" in actual:
        expected_transport = expected.get("transport_expected", expected.get("mt3dms_expected"))
        assert expected_transport is not None
        # Transport solvers (advection-dispersion) are inherently noisier
        # than flow solvers; allow a wider tolerance for transport outputs.
        assert_modflow_signatures(
            actual["transport_expected"],
            expected_transport,
            rel=5e-4,
            abs_tol=1e-5,
        )

    if "mt3dms_expected" in actual:
        assert "mt3dms_expected" in expected
        # Transport solvers (advection-dispersion) are inherently noisier
        # than flow solvers; allow a wider tolerance for MT3DMS outputs.
        assert_modflow_signatures(
            actual["mt3dms_expected"],
            expected["mt3dms_expected"],
            rel=5e-4,
            abs_tol=1e-5,
        )

    if "boussinesq_state_history_expected" in actual:
        assert "boussinesq_state_history_expected" in expected
        assert_array_signatures(
            actual["boussinesq_state_history_expected"],
            expected["boussinesq_state_history_expected"],
        )

    if "boussinesq_summary_expected" in actual:
        assert "boussinesq_summary_expected" in expected
        assert_json_signatures(
            actual["boussinesq_summary_expected"],
            expected["boussinesq_summary_expected"],
        )


def run_example_script(
    *,
    script_path: Path,
    out_path: Path,
    out_env_var: str,
    extra_env: dict | None = None,
    script_args: list[str] | None = None,
    timeout: int = 1200,
    cwd: Path = REPO_ROOT,
) -> None:
    """
    Run a "modern" example script as a subprocess.

    Use this helper when the example already supports:
    - output redirection through an environment variable,
    - non-interactive execution without monkeypatching.
    """
    env = os.environ.copy()
    # Redirect outputs into the per-test output directory via project root override.
    env[out_env_var] = str(out_path)
    env["HYDROMODPY_PROJECT_ROOT"] = str(out_path)
    # Force non-interactive plotting backend for headless execution.
    env.setdefault("MPLBACKEND", "Agg")
    if extra_env:
        for key, value in extra_env.items():
            env[key] = str(value)

    # When coverage is active, use a wrapper that starts coverage
    # programmatically before any project imports.  This avoids the numpy
    # double-load crashes caused by .pth files or "coverage run".
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

    assert completed.returncode == 0, (
        f"{script_path.name} failed.\n"
        f"Command: {' '.join(command)}\n"
        f"Stdout:\n{completed.stdout}\n"
        f"Stderr:\n{completed.stderr}"
    )


def run_hmp_cli(
    *,
    config_path: Path,
    out_path: Path,
    extra_env: dict | None = None,
    timeout: int = 1200,
    cwd: Path = REPO_ROOT,
) -> None:
    """Run ``hmp run <config>`` as a subprocess.

    Uses ``python -m hydromodpy run`` which invokes
    :class:`Simulation` — the production entry point.
    """
    env = os.environ.copy()
    env["HYDROMODPY_PROJECT_ROOT"] = str(out_path)
    env.setdefault("MPLBACKEND", "Agg")
    if extra_env:
        for key, value in extra_env.items():
            env[key] = str(value)

    if os.environ.get("HYDROMODPY_COVERAGE"):
        wrapper = Path(__file__).resolve().parent / "coverage_runner.py"
        command = [
            sys.executable, str(wrapper),
            "-m", "hydromodpy", "run", str(config_path),
        ]
    else:
        command = [
            sys.executable, "-m", "hydromodpy", "run", str(config_path),
        ]

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    assert completed.returncode == 0, (
        f"hmp run {config_path.name} failed (returncode={completed.returncode}).\n"
        f"Command: {' '.join(command)}\n"
        f"Stdout:\n{completed.stdout}\n"
        f"Stderr:\n{completed.stderr}"
    )


def run_legacy_example_script(
    *,
    script_path: Path,
    out_path: Path,
    expected_netcdf_calls: int = 1,
    stop_method: str = "postprocessing_netcdf",
    expected_stop_calls: int | None = None,
    patch_ipython_inline: bool = False,
    mirror_example_data_dir: bool = False,
    timeout: int = 1800,
    cwd: Path = REPO_ROOT,
    extra_env: dict | None = None,
) -> None:
    """
    Run a legacy example script that hardcodes `examples_legacy/results`.

    Legacy scripts are executed through an inline wrapper. The wrapper:
    1. redirects only the canonical hardcoded results path,
    2. optionally patches notebook-oriented IPython calls,
    3. monkeypatches one `Watershed` method and exits after N calls.

    Why we stop early:
    many legacy scripts include plotting, calibration loops, or manual
    exploration sections that are not part of regression validation.
    """
    if expected_stop_calls is None:
        # Keep backward compatibility with older tests using only
        # `expected_netcdf_calls`.
        expected_stop_calls = expected_netcdf_calls

    if mirror_example_data_dir:
        # Some legacy workflows derive input-data paths from the temporary
        # output workspace parent (e.g., via `workdir.parents[3]`).
        # Mirror `<example>/data` there so those path assumptions still hold.
        src_data_dir = script_path.parent / "data"
        dst_data_dir = out_path.parent / script_path.parent.name / "data"
        if src_data_dir.is_dir():
            dst_data_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_data_dir, dst_data_dir, dirs_exist_ok=True)

    # Inline wrapper executed via `python -c`.
    # Arguments are passed in fixed order through `sys.argv`.
    wrapper = r"""
import os
import runpy
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

script = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2]).resolve()
stop_method = sys.argv[3]
expected_stop_calls = int(sys.argv[4])
patch_ipython_inline = sys.argv[5] == "1"

orig_join = os.path.join

def patched_join(*parts):
    # Redirect only the canonical hardcoded pattern, keep all other joins intact.
    if len(parts) == 3 and parts[1] == "examples_legacy" and parts[2] == "results":
        return str(out_path)
    return orig_join(*parts)

os.path.join = patched_join

if patch_ipython_inline:
    try:
        import IPython
        class _DummyEvents:
            # Matplotlib may register post-execution hooks on this object.
            def register(self, *args, **kwargs):
                return None

            def unregister(self, *args, **kwargs):
                return None

        class _DummyIPython:
            def __init__(self):
                self.events = _DummyEvents()

            def run_line_magic(self, *args, **kwargs):
                return None
        # Some legacy scripts call IPython magic unconditionally.
        IPython.get_ipython = lambda: _DummyIPython()
    except Exception:
        pass

from hydromodpy.watershed.watershed import Watershed
assert hasattr(Watershed, stop_method), f"Unknown Watershed method: {stop_method}"
orig_method = getattr(Watershed, stop_method)
stop_counter = {"calls": 0}

def patched_stop_method(self, *args, **kwargs):
    # Execute original behavior first, then interrupt after N calls.
    result = orig_method(self, *args, **kwargs)
    stop_counter["calls"] += 1
    if stop_counter["calls"] >= expected_stop_calls:
        raise SystemExit(0)
    return result

setattr(Watershed, stop_method, patched_stop_method)

try:
    runpy.run_path(str(script), run_name="__main__")
except SystemExit as exc:
    code = exc.code if isinstance(exc.code, int) else 0
    if code not in (0, None):
        raise
"""

    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    if extra_env:
        for key, value in extra_env.items():
            env[key] = str(value)

    command = [
        sys.executable,
        "-c",
        wrapper,
        str(script_path),
        str(out_path),
        str(stop_method),
        str(expected_stop_calls),
        "1" if patch_ipython_inline else "0",
    ]
    # Capture logs so assertion messages include full context on failure.
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    assert completed.returncode == 0, (
        f"{script_path.name} failed.\n"
        f"Command: {' '.join(command)}\n"
        f"Stdout:\n{completed.stdout}\n"
        f"Stderr:\n{completed.stderr}"
    )




