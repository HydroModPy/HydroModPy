"""Fast regression test for launcher_simulation with Boussinesq flow only."""

from __future__ import annotations

import pytest

from tests.regression.launcher_simulation_helpers import (
    run_launcher_simulation_boussinesq_regression,
)


@pytest.mark.regression
@pytest.mark.fast
@pytest.mark.xfail(
    reason="Boussinesq runtime API mismatch (imposed_head_m_by_edge vs "
    "prescribed_head_m_by_cell) — same debt tracked by "
    "tests/unit/simulation/test_boussinesq_flow_adapter.py xfail.",
    strict=True,
    raises=AssertionError,
)
def test_launcher_simulation_fast_boussinesq_regression(update_goldens) -> None:
    run_launcher_simulation_boussinesq_regression(
        test_file=__file__,
        golden_filename="launcher_simulation_fast_boussinesq_npy_signatures.json",
        run_name="launcher_simulation_fast_boussinesq_outputs",
        update_goldens=update_goldens,
        timeout=1800,
    )
