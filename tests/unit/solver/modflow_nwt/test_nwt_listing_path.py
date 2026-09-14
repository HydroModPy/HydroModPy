"""MODFLOW-NWT listing resolution and mass-balance parsing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.solver.modflow_nwt.extractors.flow import (
    ModflowNwtOutputAdapter,
    _listing_path,
)

_LISTING = """MODFLOW-NWT-SWR1
                     VOLUMETRIC BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1 IN STRESS PERIOD    1
  ---------------------------------------------------------------------------

     CUMULATIVE VOLUMES      L**3       RATES FOR THIS TIME STEP      L**3/T
     ------------------                 ------------------------

           IN:                                      IN:
           ---                                      ---
             STORAGE =           0.0000               STORAGE =           0.0000
       CONSTANT HEAD =           0.0000         CONSTANT HEAD =           0.0000
            RECHARGE =           1.0000              RECHARGE =           2.0000

            TOTAL IN =           1.0000              TOTAL IN =           2.0000

          OUT:                                     OUT:
          ----                                     ----
             STORAGE =           0.0000               STORAGE =           0.5000
       CONSTANT HEAD =           0.0000         CONSTANT HEAD =           1.5000
            RECHARGE =           0.0000              RECHARGE =           0.0000

           TOTAL OUT =           1.0000             TOTAL OUT =           2.0000

            IN - OUT =           0.0000              IN - OUT =           0.0000

 PERCENT DISCREPANCY =           0.00     PERCENT DISCREPANCY =           0.00

          TIME SUMMARY AT END OF TIME STEP    1 IN STRESS PERIOD    1
                    SECONDS     MINUTES      HOURS       DAYS        YEARS
                    -----------------------------------------------------------
   TIME STEP LENGTH  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
 STRESS PERIOD TIME  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
         TOTAL TIME  1.0000      1.66667E-02 2.77778E-04 1.15741E-05 3.16881E-08
"""


class _RecordingStore:
    """Minimal store capturing the mass-balance records."""

    def __init__(self) -> None:
        self.mass_balances: list[dict] = []

    def write_mass_balances(self, sim_id: str, records: list[dict]) -> None:
        self.mass_balances = records


def test_listing_uses_the_flopy_list_extension() -> None:
    # FloPy declares the LIST unit as ``.list``; a ``.lst`` lookup never matches
    # and silently empties the mass balance.
    assert _listing_path(Path("/out"), "canut_steady_nwt") == Path("/out/canut_steady_nwt.list")


def test_mass_balance_reads_rates_and_scales_them(tmp_path: Path) -> None:
    listing = tmp_path / "run.list"
    listing.write_text(_LISTING, encoding="utf-8")
    store = _RecordingStore()

    ModflowNwtOutputAdapter()._extract_mass_balance("sim", store, listing, 1.0 / 86400.0)

    assert len(store.mass_balances) == 1
    record = store.mass_balances[0]
    assert record["timestep"] == 0
    assert record["total_in"] == pytest.approx(2.0 / 86400.0)
    assert record["total_out"] == pytest.approx(2.0 / 86400.0)
    assert record["storage_out"] == pytest.approx(0.5 / 86400.0)
    # PERCENT_DISCREPANCY is unitless and must not be scaled.
    assert record["percent_error"] == pytest.approx(0.0)
    assert np.isfinite(record["percent_error"])


def test_unreadable_listing_fails_loudly(tmp_path: Path) -> None:
    listing = tmp_path / "run.list"
    listing.write_text("not a MODFLOW listing", encoding="utf-8")

    with pytest.raises(ExtractError, match="mass balance"):
        ModflowNwtOutputAdapter()._extract_mass_balance("sim", _RecordingStore(), listing, 1.0)
