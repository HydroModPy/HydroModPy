"""Fast solver intercomparison regression on a shared irregular mesh."""

from __future__ import annotations

import pytest

from tests.regression.golden_utils import REPO_ROOT
from tests.regression.intercomparison_helpers import (
    metric_key,
    run_intercomparison_regression,
)

COMPARISON_DIR = REPO_ROOT / "tests" / "regression" / "fixtures" / "projects" / "intercomparison"


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.intercomparison
@pytest.mark.mf6
@pytest.mark.boussinesq
@pytest.mark.binary
@pytest.mark.timeout(900)
def test_dupuit_irregular_mesh_mf6_boussinesq_intercomparison_regression(
    update_goldens,
) -> None:
    """Lock MF6 and Boussinesq against each other on the same irregular mesh."""
    run_intercomparison_regression(
        test_file=__file__,
        source_config=COMPARISON_DIR / "compare_dupuit_irregular_mf6_bouss.toml",
        base_simulation_config=COMPARISON_DIR / "base_dupuit_shared_mesh.toml",
        golden_filename="intercomparison/intercomparison_dupuit_irregular_mf6_bouss_signatures.json",
        run_name="intercomparison_dupuit_irregular_mf6_bouss_outputs",
        update_goldens=update_goldens,
        require_modflow6=True,
        limits={
            metric_key(
                variant_id="bouss_candidate",
                observable="head_map_last",
            ): {
                "mae": 0.03,
                "rmse": 0.04,
                "max_abs_error": 0.12,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_west_last",
            ): {
                "max_abs_error": 0.01,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_middle_last",
            ): {
                "max_abs_error": 0.01,
            },
            metric_key(
                variant_id="bouss_candidate",
                observable="head_east_last",
            ): {
                "max_abs_error": 0.01,
            },
        },
    )
