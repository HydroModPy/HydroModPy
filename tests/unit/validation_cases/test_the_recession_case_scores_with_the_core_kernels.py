"""The Brutsaert recession case scores with the core kernels, not its own copies.

The case kept its own NSE, NSElog, KGE and RMSE, with the argument order
inverted (observed first). NSElog there had no epsilon, so the same pair of
series did not score the same in the case and in the run score.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core import metrics as core
from validation_cases.calibration.recession_hillslope_aquifer import experiment as case

_OBSERVED = np.array([5.0, 3.0, 2.0, 1.2, 0.8, 0.5, 0.3, 0.2, 0.15, 0.1])
_SIMULATED = _OBSERVED * np.array([1.1, 0.9, 1.05, 0.95, 1.2, 0.85, 1.1, 0.9, 1.3, 0.8])


def test_the_bundle_reads_the_core_kernels() -> None:
    bundle = case._compute_metrics(_OBSERVED, _SIMULATED)

    kge = core.kge(sim=_SIMULATED, obs=_OBSERVED)
    assert bundle["NSE"] == pytest.approx(core.nse(sim=_SIMULATED, obs=_OBSERVED))
    assert bundle["NSElog"] == pytest.approx(core.log_nse(sim=_SIMULATED, obs=_OBSERVED))
    assert bundle["KGE"] == pytest.approx(kge["kge"])
    assert bundle["r"] == pytest.approx(kge["r"])
    assert bundle["alpha"] == pytest.approx(kge["alpha"])
    assert bundle["beta"] == pytest.approx(kge["beta"])


def test_the_case_defines_no_kernel_of_its_own() -> None:
    for name in ("_nse", "_nse_log", "_kge_with_components"):
        assert not hasattr(case, name)


def test_a_non_positive_value_follows_the_shared_nse_log_rule() -> None:
    observed = np.array([2.0, 0.0, 1.0, 3.0])
    simulated = np.array([2.1, -0.5, 0.9, 2.8])

    bundle = case._compute_metrics(observed, simulated)

    assert np.isfinite(bundle["NSElog"])
    assert bundle["NSElog"] == pytest.approx(core.log_nse(sim=simulated, obs=observed))
    assert np.isfinite(bundle["NSE"])


def test_the_costs_keep_their_value_and_their_failure_marker() -> None:
    assert case._rmse_cost(_OBSERVED, _SIMULATED) == pytest.approx(
        core.rmse(sim=_SIMULATED, obs=_OBSERVED)
    )
    assert case._kge_cost(_OBSERVED, _SIMULATED) == pytest.approx(
        1.0 - core.kge(sim=_SIMULATED, obs=_OBSERVED)["kge"]
    )
    nothing = np.full(3, np.nan)
    assert case._rmse_cost(nothing, nothing) == 1e12
    assert case._kge_cost(np.full(3, 2.0), _SIMULATED[:3]) == 1e12
