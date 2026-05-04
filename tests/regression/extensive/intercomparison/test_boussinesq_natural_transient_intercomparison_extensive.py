"""Extensive MF6/Boussinesq intercomparison on a natural transient mesh."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import REPO_ROOT
from tests.regression.intercomparison_helpers import (
    metric_key,
    run_intercomparison_regression,
)


EXAMPLE_DIR = REPO_ROOT / "examples" / "projects" / "09_comparison_workflow"


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.intercomparison
@pytest.mark.mf6
@pytest.mark.boussinesq
@pytest.mark.binary
@pytest.mark.timeout(2400)
def test_natural_mesh_transient_pulse_mf6_boussinesq_intercomparison_regression(
    update_goldens,
) -> None:
    """Lock the controlled natural transient pulse comparison against regressions."""
    run_intercomparison_regression(
        test_file=__file__,
        source_config=EXAMPLE_DIR / "compare_10km2_natural_mesh_transient_pulse_mf6_bouss.toml",
        base_simulation_config=EXAMPLE_DIR / "base_10km2_natural_mesh_transient_pulse.toml",
        golden_filename=(
            "intercomparison/"
            "intercomparison_natural_mesh_10km2_transient_pulse_mf6_bouss_signatures.json"
        ),
        run_name="intercomparison_natural_mesh_10km2_transient_pulse_mf6_bouss_outputs",
        update_goldens=update_goldens,
        require_modflow6=True,
        timeout_seconds=2400.0,
        allowed_audit_status=("pass", "warn"),
        limits={
            metric_key(
                variant_id="bouss_candidate",
                observable="head_map_initial",
            ): {
                "rmse": 0.001,
                "max_abs_error": 0.001,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_map_pulse",
            ): {
                "mae": 0.03,
                "rmse": 0.04,
                "max_abs_error": 0.08,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_map_last",
            ): {
                "mae": 0.05,
                "rmse": 0.06,
                "max_abs_error": 0.60,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_west_series",
            ): {
                "rmse": 0.04,
                "max_abs_error": 0.05,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_middle_series",
            ): {
                "rmse": 0.04,
                "max_abs_error": 0.05,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_east_series",
            ): {
                "rmse": 0.04,
                "max_abs_error": 0.05,
            },
        },
    )
