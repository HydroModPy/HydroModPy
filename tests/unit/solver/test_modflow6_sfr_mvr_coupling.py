"""SFR <-> LAK coupling through MVR records (both directions, 2-package block)."""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow6.builders import (
    build_lake_mover_records,
    build_mvr_period_records,
    mover_package_count,
)
from hydromodpy.solver.modflow6.builders.mvr import MoverRecord


def test_lake_outlet_mover_reach_targets_sfr() -> None:
    # The spillway-release direction: a LAK outlet mover carrying `reach` becomes
    # a LAK -> SFR record (receiver id = 1-based reach - 1).
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "couttype": "WEIR",
                    "invert": 95.0,
                    "width": 5.0,
                    "lakeout": 0,
                    "mover": {"reach": 3, "mvrtype": "FACTOR", "value": 1.0},
                }
            ]
        }
    }
    records = build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))
    assert records == [["LAK", 0, "SFR", 2, "FACTOR", 1.0]]


def test_outlet_numbering_stays_in_lockstep_with_mover_less_outlets() -> None:
    # A direct outlet without a mover still advances the shared outlet counter,
    # so the mover on the SECOND outlet provides from outletno 1.
    lakes = {
        "lac0": {
            "outlets": [
                {"couttype": "WEIR", "invert": 95.0, "width": 5.0, "lakeout": 0},
                {
                    "couttype": "SPECIFIED",
                    "lakeout": 0,
                    "mover": {"reach": 1, "mvrtype": "UPTO", "value": 0.5},
                },
            ]
        }
    }
    records = build_mvr_period_records(build_lake_mover_records(None, lakes=lakes))
    assert records == [["LAK", 1, "SFR", 0, "UPTO", 0.5]]


def test_lake_outlet_mover_reach_zero_raises() -> None:
    lakes = {
        "lac0": {
            "outlets": [
                {
                    "couttype": "WEIR",
                    "invert": 95.0,
                    "width": 5.0,
                    "lakeout": 0,
                    "mover": {"reach": 0},
                }
            ]
        }
    }
    with pytest.raises(ValueError, match="reach"):
        build_lake_mover_records(None, lakes=lakes)


def test_mixed_lak_sfr_records_make_a_two_package_block() -> None:
    # SFR -> LAK (the Cheze feed) merged with LAK -> SFR (spillway): the MVR block
    # references two distinct packages and the packages list is derived from the
    # record rows, exactly as build.py assembles it.
    rows = build_mvr_period_records(
        [
            MoverRecord(provider="SFR", provider_id=7, receiver="LAK", receiver_id=0),
            MoverRecord(
                provider="LAK",
                provider_id=0,
                receiver="SFR",
                receiver_id=8,
                mvrtype="UPTO",
                value=0.1,
            ),
        ]
    )
    assert mover_package_count(rows) == 2
    packages = sorted({(str(row[0]),) for row in rows} | {(str(row[2]),) for row in rows})
    assert packages == [("LAK",), ("SFR",)]
