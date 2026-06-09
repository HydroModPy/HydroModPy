"""SFR + LAK + MVR validation against ex-gwf-lak-p02 (Merritt & Konikow 2000).

The HMP package-agnostic MVR seam (MoverRecord -> build_mvr_period_records ->
mover_package_count -> packages list, the exact assembly ``build.py`` performs)
drives the upstream example's four transfers: two SFR -> LAK feeds and two
LAK -> SFR spillway releases (one at FACTOR 0.5). Two levels:

* STRUCTURAL: the HMP-formatted MVR period block reproduces the published
  ``mvr_spd`` rows verbatim and counts two packages;
* NUMERICAL: real MF6 converges and the final lake stages match the PUBLISHED
  values (116.98 / 111.93 ft) within the documented ``tolerances.toml`` band,
  with all four transfers carrying water and the budget closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validation_cases.numerical.transient.sfr_lak_mvr.case import (
    PUBLISHED_MVR_SPD,
    load_tolerances,
    run_sfr_lak_mvr_scenario,
)


@pytest.mark.validation
@pytest.mark.transient
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
@pytest.mark.allow_subprocess
def test_sfr_lak_mvr_p02_matches_published_stages(tmp_path: Path) -> None:
    scenario = run_sfr_lak_mvr_scenario(workspace=tmp_path)
    tolerances = load_tolerances()
    published = tolerances["published"]
    stage_tol = float(tolerances["stage"]["final_stage_abs_error_ft"])
    min_transfer = float(tolerances["mvr"]["min_transfer_cfd"])
    budget_tol = float(tolerances["budget"]["budget_percent_discrepancy"])

    # STRUCTURAL: the HMP MVR seam reproduces the published period block.
    assert scenario.mvr_rows == PUBLISHED_MVR_SPD
    assert scenario.maxpackages == 2

    # NUMERICAL: published converged stages within the documented band.
    assert scenario.lake1_final_stage_ft == pytest.approx(
        float(published["lake1_final_stage_ft"]), abs=stage_tol
    )
    assert scenario.lake2_final_stage_ft == pytest.approx(
        float(published["lake2_final_stage_ft"]), abs=stage_tol
    )

    # All four movers actually transferred water at the end of the simulation.
    for name, value in scenario.transfers_cfd.items():
        assert value > min_transfer, f"mover '{name}' carried no water ({value} cfd)"

    assert abs(scenario.budget_percent_discrepancy) <= budget_tol
