"""Regression test for the Brutsaert recession calibration case."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.calibration.cases.recession_brutsaert import calibrate_brutsaert

GOLDEN_FILE = (
    Path(__file__).resolve().parent / "golden" / "calibration_brutsaert_methods_golden.json"
)

# ``gp_mapping`` has a looser tolerance because the Expected-Improvement
# acquisition is sensitive to small dependency-level changes on this noisy
# recession case. ``da_mh_gp`` keeps a 6e-2 tolerance for MCMC mixing noise.
METHOD_ABS_TOL: dict[str, float] = {
    "grid_search": 1e-10,
    "random_search": 1e-10,
    "cma_es": 8e-3,
    "scipy_nelder_mead": 2e-4,
    "gp_mapping": 5e-2,
    "da_mh_gp": 6e-2,
}


def _load_golden() -> dict[str, dict]:
    with GOLDEN_FILE.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _has_cmaes_sampler() -> bool:
    """Return True when Optuna's CMA-ES sampler can actually run.

    The class always exists on modern Optuna versions but the underlying
    ``cmaes`` package is an optional dependency; we need both.
    """
    try:
        import cmaes  # noqa: F401
        import optuna  # noqa: F401

        return hasattr(__import__("optuna").samplers, "CmaEsSampler")
    except Exception:
        return False


@pytest.mark.parametrize(
    "method",
    [
        "grid_search",
        "random_search",
        "scipy_nelder_mead",
        pytest.param(
            "cma_es",
            marks=pytest.mark.skipif(
                not _has_cmaes_sampler(),
                reason="optuna's CmaEsSampler requires the 'cmaes' package",
            ),
        ),
        "gp_mapping",
        "da_mh_gp",
    ],
)
def test_brutsaert_method_matches_golden(method: str) -> None:
    """Compare best-parameter vector of each method against the golden."""
    if method == "scipy_nelder_mead":
        pytest.importorskip("scipy")
    if method == "cma_es":
        pytest.importorskip("optuna")
    if method in ("gp_mapping", "da_mh_gp"):
        pytest.importorskip("sklearn")

    # ``da_mh_gp`` uses RMSE because its sampler builds a Gaussian likelihood.
    objective_metric = "rmse" if method == "da_mh_gp" else "kge"

    result = calibrate_brutsaert(method=method, objective_metric=objective_metric)

    expected = _load_golden()[method]
    expected_x = np.asarray(expected["x_best"], dtype=float)
    actual_x = np.asarray(result["x_best"], dtype=float)

    assert actual_x.shape == expected_x.shape, (
        f"x_best shape mismatch: got {actual_x.shape}, expected {expected_x.shape}"
    )
    assert np.allclose(actual_x, expected_x, atol=METHOD_ABS_TOL[method], rtol=0.0), (
        f"x_best mismatch for method {method!r}: "
        f"got {actual_x.tolist()}, expected {expected_x.tolist()} "
        f"(abs_tol={METHOD_ABS_TOL[method]})"
    )
    assert result["method"] == method
    assert {"NSE", "NSElog", "KGE", "r", "alpha", "beta"} <= set(result["metrics"])
