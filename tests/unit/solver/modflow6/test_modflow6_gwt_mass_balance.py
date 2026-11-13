"""Audit item 12 - MODFLOW 6 GWT solute mass balance persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.modflow6.extractors.transport import (
    Modflow6GwtOutputAdapter,
    find_gwt_listing,
    parse_gwt_mass_balance,
)

_GWT_LST = """\
  VOLUME BUDGET line that must be ignored
 MASS BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    1, STRESS PERIOD   1
           IN:                                      IN:
     STORAGE-AQUEOUS =     70.0000       STORAGE-AQUEOUS =       0.7000
                RCHA =     30.0000                  RCHA =       0.3000
            TOTAL IN =      100.0000              TOTAL IN =           1.0000
          OUT:                                     OUT:
     STORAGE-AQUEOUS =      9.0000       STORAGE-AQUEOUS =       0.0900
       DECAY-AQUEOUS =     90.0000         DECAY-AQUEOUS =       0.8100
           TOTAL OUT =       99.0000             TOTAL OUT =           0.9000
            IN - OUT =        1.0000              IN - OUT =           0.1000
 PERCENT DISCREPANCY =           0.50     PERCENT DISCREPANCY =          10.53
 MASS BUDGET FOR ENTIRE MODEL AT END OF TIME STEP    2, STRESS PERIOD   1
            TOTAL IN =      200.0000              TOTAL IN =           2.0000
           TOTAL OUT =      198.0000             TOTAL OUT =           1.8000
 PERCENT DISCREPANCY =           0.30     PERCENT DISCREPANCY =           0.20
"""


class _CaptureStore:
    def __init__(self) -> None:
        self.mass: list[dict] | None = None

    def write_mass_balances(self, sim_id, records) -> None:
        self.mass = records


def _write_listing(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_gwt_mass_balance_keeps_rates_column(tmp_path) -> None:
    lst = _write_listing(tmp_path, "trans.lst", _GWT_LST)
    records = parse_gwt_mass_balance(lst)

    assert [r["timestep"] for r in records] == [0, 1]
    # The RATES (rightmost) column is kept, not the CUMULATIVE column.
    # The storage terms are split by side, and the discrepancy is recomputed
    # from IN - OUT rather than read from its column rounded to 0.01 %.
    assert records[0] == {
        "timestep": 0,
        "total_in": 1.0,
        "total_out": 0.9,
        "storage_in": 0.7,
        "storage_out": 0.09,
        "percent_error": pytest.approx(100.0 * 0.1 / 0.95),
    }
    assert records[1]["total_in"] == 2.0
    # A block without IN - OUT keeps the listed discrepancy.
    assert records[1]["percent_error"] == 0.2


def test_find_gwt_listing_skips_the_volume_budget_file(tmp_path) -> None:
    _write_listing(tmp_path, "flow.lst", "VOLUME BUDGET FOR ENTIRE MODEL\nTOTAL IN = 5.0\n")
    gwt = _write_listing(tmp_path, "trans.lst", _GWT_LST)

    assert find_gwt_listing(tmp_path) == gwt


def test_gwt_adapter_persists_solute_rows(tmp_path) -> None:
    _write_listing(tmp_path, "trans.lst", _GWT_LST)
    store = _CaptureStore()

    Modflow6GwtOutputAdapter._extract_solute_mass_balance("sim", tmp_path, store)

    assert store.mass is not None
    assert len(store.mass) == 2
    for row in store.mass:
        assert row["quantity"] == "solute"
        assert row["unit"] == "kg s-1"
    assert store.mass[0]["total_in"] == 1.0
