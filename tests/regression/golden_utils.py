"""Shared helpers for regression tests based on golden JSON references."""

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


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_golden_reference(path: Path) -> dict:
    """Read a golden JSON file."""
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_golden_reference(path: Path, payload: dict) -> None:
    """Write a golden JSON file with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def load_npy_dict(path: Path) -> dict:
    """Load a .npy file that stores a Python dict."""
    return np.load(path, allow_pickle=True).item()


def array_stats(values) -> dict:
    """Build stable summary stats while ignoring NaN/Inf values."""
    arr = np.asarray(values, dtype=float)
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
    """Compare stats with numerical tolerance."""
    assert actual["count"] == expected["count"]
    for key in ("mean", "p50", "p95"):
        if expected[key] is None:
            assert actual[key] is None
        else:
            assert actual[key] == pytest.approx(expected[key], rel=1e-4, abs=1e-6)


def modflow_signature(path: Path) -> dict:
    """Build a compact signature from a MODFLOW .npy output on last timestep."""
    data = load_npy_dict(path)
    assert len(data) > 0

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
    """Build a MODPATH signature from a .dbf file using the 'time' column."""
    table = gpd.read_file(path)
    assert "time" in table.columns, f"Column 'time' not found in {path}"
    return {
        "n_rows": int(len(table)),
        "time": array_stats(np.asarray(table["time"], dtype=float)),
    }


def collect_modflow_signatures(postprocess_dir: Path, names: list[str]) -> dict:
    """Compute MODFLOW signatures for a list of output names."""
    return {name: modflow_signature(postprocess_dir / f"{name}.npy") for name in names}


def collect_modpath_signatures(particles_dir: Path, filenames: list[str]) -> dict:
    """Compute MODPATH signatures for a list of snapshot filenames."""
    return {name: snapshot_signature(particles_dir / name) for name in filenames}


def assert_modflow_signatures(actual_by_name: dict, expected_by_name: dict) -> None:
    """Compare MODFLOW signatures against golden expectations."""
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
    """Compare MODPATH .dbf time signatures against golden expectations."""
    assert set(actual_by_name) == set(expected_by_name)
    for filename, expected in expected_by_name.items():
        actual = actual_by_name[filename]
        assert actual["n_rows"] == expected["n_rows"]
        assert_stats(actual["time"], expected["time"])


def assert_required_executables(repo_root: Path = REPO_ROOT) -> None:
    """Skip test when bundled MODFLOW/MODPATH executables are missing."""
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


def run_example_script(
    *,
    script_path: Path,
    out_path: Path,
    out_env_var: str,
    extra_env: dict | None = None,
    timeout: int = 1200,
    cwd: Path = REPO_ROOT,
) -> None:
    """Run a full example script and fail with full logs if it crashes."""
    env = os.environ.copy()
    env[out_env_var] = str(out_path)
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

