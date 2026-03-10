"""Analytical validation test using the standard launcher on a synthetic domain."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    load_npy_dict,
    resolve_model_workspace,
    resolve_tiered_results_dir,
    run_example_script,
)

LAUNCHER_SIMULATION_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "launcher_simulation"
    / "launcher_simulation.py"
)
LINEAR_HEAD_CONFIG = (
    REPO_ROOT
    / "examples"
    / "launcher_simulation"
    / "config_validation_linear_head.toml"
)


def _expected_dupuit_profile(*, xmin: float, xmax: float, ncol: int, west: float, east: float) -> np.ndarray:
    """Return the steady unconfined 1D solution with fixed heads at both ends."""
    x = np.linspace(float(xmin), float(xmax), int(ncol), dtype=float)
    return np.sqrt(
        float(west) ** 2
        + ((float(east) ** 2 - float(west) ** 2) * ((x - float(xmin)) / float(xmax - xmin)))
    )


@pytest.mark.regression
@pytest.mark.normal
@pytest.mark.fast
def test_launcher_simulation_matches_dupuit_fixed_head_solution() -> None:
    """Validate a steady unconfined fixed-head profile against the analytical solution."""
    assert_required_executables(require_modpath=False, require_mt3dms=False)

    out_path = resolve_tiered_results_dir(
        test_file=__file__,
        run_name="launcher_simulation_analytical_validation_outputs",
    )
    run_example_script(
        script_path=LAUNCHER_SIMULATION_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={
            "HYDROMODPY_NO_DISPLAY": "1",
            "HYDROMODPY_NO_SAVE": "1",
        },
        script_args=[str(LINEAR_HEAD_CONFIG)],
        timeout=1800,
    )

    model_ws, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        watershed_name="validation_linear_head",
        results_folder_name="results_simulations",
        model_name="Analytical_linear_head_validation",
    )
    del model_ws
    simulated = load_npy_dict(postprocess_dir / "watertable_elevation.npy")
    assert simulated, "watertable_elevation.npy is empty."

    last_key = sorted(simulated)[-1]
    heads = np.asarray(simulated[last_key], dtype=float)
    assert heads.shape == (5, 40)

    expected = _expected_dupuit_profile(
        xmin=0.0,
        xmax=400.0,
        ncol=heads.shape[1],
        west=10.0,
        east=5.0,
    )

    column_profile = heads.mean(axis=0)
    rms_error = float(np.sqrt(np.mean((column_profile - expected) ** 2)))
    max_error = float(np.max(np.abs(column_profile - expected)))
    row_spread = float(np.max(np.std(heads, axis=0)))

    assert rms_error < 0.05, f"RMS error too high against analytical profile: {rms_error:.6f} m"
    assert max_error < 0.10, f"Max error too high against analytical profile: {max_error:.6f} m"
    assert row_spread < 1e-6, f"Unexpected y-direction variability for 1D case: {row_spread:.6e} m"
