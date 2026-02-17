"""
Shared utilities for regression tests based on golden references.

This module centralizes the common mechanics used by example-based regression
tests:
1) run an example script (regular or "legacy" script),
2) collect compact signatures from generated outputs,
3) compare signatures against golden JSON references, or refresh them.

Keeping this logic in one place helps make individual tests short and focused
on "what to validate" rather than "how to validate it".
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest


# Repository root used by tests that need stable relative paths.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Most MODFLOW-based regression tests validate this common output subset.
DEFAULT_MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
    "accumulation_flux",
]


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
    """
    return np.load(path, allow_pickle=True).item()


def array_stats(values) -> dict:
    """
    Compute compact, stable statistics from a numeric array-like input.

    The function explicitly ignores non-finite values (`NaN`, `+/-Inf`) so
    signatures remain robust across minor runtime/environment differences.
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


def assert_stats(actual: dict, expected: dict) -> None:
    """
    Compare two statistical signatures with a small numeric tolerance.

    `count` must match exactly, while floating statistics are compared with
    `pytest.approx` to tolerate tiny floating-point noise.
    """
    assert actual["count"] == expected["count"]
    for key in ("mean", "p50", "p95"):
        if expected[key] is None:
            assert actual[key] is None
        else:
            assert actual[key] == pytest.approx(expected[key], rel=1e-4, abs=1e-6)


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

    # Use the last timestep to summarize final model state.
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
    """
    table = gpd.read_file(path)
    assert "time" in table.columns, f"Column 'time' not found in {path}"
    return {
        "n_rows": int(len(table)),
        "time": array_stats(np.asarray(table["time"], dtype=float)),
    }


def collect_modflow_signatures(postprocess_dir: Path, names: list[str]) -> dict:
    """
    Collect MODFLOW signatures for a list of output base names.

    Example
    -------
    If `name` is `watertable_elevation`, this function reads:
    `<postprocess_dir>/watertable_elevation.npy`.
    """
    return {name: modflow_signature(postprocess_dir / f"{name}.npy") for name in names}


def collect_modpath_signatures(particles_dir: Path, filenames: list[str]) -> dict:
    """
    Collect MODPATH signatures for a list of particle snapshot filenames.
    """
    return {name: snapshot_signature(particles_dir / name) for name in filenames}


def assert_modflow_signatures(actual_by_name: dict, expected_by_name: dict) -> None:
    """
    Validate MODFLOW signatures against golden expectations.

    Structure and available keys are checked first, then numeric values are
    compared with tolerances.
    """
    assert set(actual_by_name) == set(expected_by_name)
    for name, expected in expected_by_name.items():
        actual = actual_by_name[name]
        assert actual["shape"] == expected["shape"]
        if "timestep" in expected:
            assert actual["timestep"] == expected["timestep"]
        if "available_timesteps" in expected:
            assert actual["available_timesteps"] == expected["available_timesteps"]
        assert_stats(actual, expected)
        if expected["sum"] is None:
            assert actual["sum"] is None
        else:
            assert actual["sum"] == pytest.approx(expected["sum"], rel=1e-4, abs=1e-6)


def assert_modpath_signatures(actual_by_name: dict, expected_by_name: dict) -> None:
    """
    Validate MODPATH `.dbf` signatures against golden expectations.
    """
    assert set(actual_by_name) == set(expected_by_name)
    for filename, expected in expected_by_name.items():
        actual = actual_by_name[filename]
        assert actual["n_rows"] == expected["n_rows"]
        assert_stats(actual["time"], expected["time"])


def assert_required_executables(repo_root: Path = REPO_ROOT) -> None:
    """
    Ensure bundled MODFLOW/MODPATH executables are available for this platform.

    The function *skips* the test (instead of failing) when binaries are not
    available, because this is an environment capability issue rather than a
    model regression issue.
    """
    # Resolve executable names from OS-specific bundled folders.
    if platform.system() == "Windows":
        mf_exe = repo_root / "bin" / "win" / "mfnwt.exe"
        mp_exe = repo_root / "bin" / "win" / "mp6.exe"
    elif platform.system() == "Linux":
        mf_exe = repo_root / "bin" / "linux" / "mfnwt"
        mp_exe = repo_root / "bin" / "linux" / "mp6"
    elif platform.system() == "Darwin":
        mf_exe = repo_root / "bin" / "mac" / "mfnwt"
        mp_exe = repo_root / "bin" / "mac" / "mp6"
    else:
        pytest.skip(f"Unsupported platform for bundled executables: {platform.system()}")

    missing = [str(p) for p in (mf_exe, mp_exe) if not p.exists()]
    if missing:
        pytest.skip(f"Required executables are missing: {missing}")


def resolve_model_workspace(
    out_path: Path,
    *,
    watershed_name: str | None = None,
    results_folder_name: str = "results_simulations",
    model_name: str | None = None,
    model_name_prefix: str | None = None,
) -> tuple[Path, Path, Path]:
    """
    Resolve the generated workspace folders for a given example run.

    Returns
    -------
    tuple
        (model_ws, postprocess_dir, particles_dir)
    """
    # 1) Resolve watershed folder.
    if watershed_name is None:
        # Most tests produce exactly one watershed folder in `out_path`.
        watershed_dirs = sorted(p for p in out_path.iterdir() if p.is_dir())
        assert watershed_dirs, f"No watershed folder found in {out_path}"
        watershed_dir = watershed_dirs[0]
    else:
        # Some tests prefer explicit watershed naming to avoid ambiguity.
        watershed_dir = out_path / watershed_name
        assert watershed_dir.is_dir(), f"Watershed folder not found: {watershed_dir}"

    # 2) Resolve results folder (`results_simulations` or `results_calibration`).
    results_dir = watershed_dir / results_folder_name
    assert results_dir.is_dir(), f"Results folder not found: {results_dir}"

    # 3) Resolve model folder (exact name or first matching folder).
    if model_name is not None:
        model_ws = results_dir / model_name
        assert model_ws.is_dir(), f"Model folder not found: {model_ws}"
    else:
        model_dirs = sorted(
            p for p in results_dir.iterdir()
            if p.is_dir()
            and not p.name.startswith("_")
            and (model_name_prefix is None or p.name.startswith(model_name_prefix))
        )
        assert model_dirs, f"No model folder found in {results_dir}"
        model_ws = model_dirs[0]

    # 4) Return canonical workspace paths used by most regression tests.
    postprocess_dir = model_ws / "_postprocess"
    particles_dir = postprocess_dir / "_particles"
    return model_ws, postprocess_dir, particles_dir


def resolve_first_model_workspace(
    out_path: Path,
    *,
    results_folder_name: str = "results_simulations",
) -> tuple[Path, Path, Path]:
    """
    Backward-compatible wrapper that selects the first watershed/model folders.
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
    if update_goldens:
        write_golden_reference(golden_reference_file, actual)
        return

    expected = load_golden_reference(golden_reference_file)

    # Validate only sections present in `actual`, which keeps this helper
    # usable for MODFLOW-only and MODFLOW+MODPATH tests.
    if "modflow_expected" in actual:
        assert "modflow_expected" in expected
        assert_modflow_signatures(actual["modflow_expected"], expected["modflow_expected"])

    if "modpath_expected" in actual:
        assert "modpath_expected" in expected
        assert_modpath_signatures(actual["modpath_expected"], expected["modpath_expected"])


def run_example_script(
    *,
    script_path: Path,
    out_path: Path,
    out_env_var: str,
    extra_env: dict | None = None,
    timeout: int = 1200,
    cwd: Path = REPO_ROOT,
) -> None:
    """
    Run a regular example script as a subprocess.

    This path is used for scripts that already expose an output-directory
    environment variable and do not require monkeypatching.
    """
    env = os.environ.copy()
    # Redirect outputs into a pytest temporary directory.
    env[out_env_var] = str(out_path)
    # Force non-interactive plotting backend for headless execution.
    env.setdefault("MPLBACKEND", "Agg")
    if extra_env:
        for key, value in extra_env.items():
            env[key] = str(value)

    command = [sys.executable, str(script_path)]
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


def run_legacy_example_script(
    *,
    script_path: Path,
    out_path: Path,
    expected_netcdf_calls: int = 1,
    stop_method: str = "postprocessing_netcdf",
    expected_stop_calls: int | None = None,
    patch_ipython_inline: bool = False,
    timeout: int = 1800,
    cwd: Path = REPO_ROOT,
    extra_env: dict | None = None,
) -> None:
    """
    Run a legacy example script that hardcodes `examples/results`.

    Legacy scripts are executed through an inline wrapper that:
    1) rewrites only the target `os.path.join(..., "examples", "results")`,
    2) optionally patches notebook-only IPython calls,
    3) monkeypatches one `Watershed` method to stop execution at a controlled
       point (before heavy plotting/interactive sections).
    """
    if expected_stop_calls is None:
        # Keep backward compatibility with older tests using only
        # `expected_netcdf_calls`.
        expected_stop_calls = expected_netcdf_calls

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
    if len(parts) == 3 and parts[1] == "examples" and parts[2] == "results":
        return str(out_path)
    return orig_join(*parts)

os.path.join = patched_join

if patch_ipython_inline:
    try:
        import IPython
        class _DummyIPython:
            def run_line_magic(self, *args, **kwargs):
                return None
        # Some legacy scripts call IPython magic unconditionally.
        IPython.get_ipython = lambda: _DummyIPython()
    except Exception:
        pass

from hydromodpy.watershed_root import Watershed
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

