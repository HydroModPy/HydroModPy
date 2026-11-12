"""``convert_abacus_to_parquet``: a lake abacus (stage m, volume m3, area m2) as a Parquet pivot.

A user abacus, CSV or Parquet, with or without a lake_id column, is validated and
written as the Parquet pivot with the lake_id injected and the values kept.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.ingest.tables import convert_abacus_to_parquet

COLUMNS = ["lake_id", "stage", "volume", "sarea"]


def test_csv_gets_the_lake_id(tmp_path):
    src = tmp_path / "abacus.csv"
    src.write_text(
        "stage,volume,sarea\n85.0,0.0,0.0\n87.0,200000.0,100000.0\n90.0,1200000.0,400000.0\n",
        encoding="utf-8",
    )
    dest = tmp_path / "abacus.parquet"

    out = convert_abacus_to_parquet(src, dest, lake_id="lac0")

    assert out == dest
    assert dest.exists()
    df = pd.read_parquet(dest)
    assert list(df.columns) == COLUMNS
    assert df["lake_id"].unique().tolist() == ["lac0"]
    assert df["stage"].tolist() == pytest.approx([85.0, 87.0, 90.0])
    assert df["volume"].tolist() == pytest.approx([0.0, 200000.0, 1200000.0])
    assert df["sarea"].tolist() == pytest.approx([0.0, 100000.0, 400000.0])


def test_existing_lake_id_is_kept(tmp_path):
    src = tmp_path / "abacus.csv"
    src.write_text(
        "lake_id,stage,volume,sarea\nretenue,85.0,0.0,0.0\nretenue,90.0,1.0e6,4.0e5\n",
        encoding="utf-8",
    )

    out = convert_abacus_to_parquet(src, tmp_path / "out.parquet", lake_id="ignored")

    assert pd.read_parquet(out)["lake_id"].unique().tolist() == ["retenue"]


def test_parquet_source(tmp_path):
    # A Parquet abacus is read with pyarrow, not read_csv, and validated like a CSV.
    src = tmp_path / "raw.parquet"
    pd.DataFrame({"stage": [85.0, 90.0], "volume": [0.0, 1.0e6], "sarea": [0.0, 4.0e5]}).to_parquet(
        src
    )

    out = convert_abacus_to_parquet(src, tmp_path / "pivot.parquet", lake_id="lac0")

    df = pd.read_parquet(out)
    assert list(df.columns) == COLUMNS
    assert df["lake_id"].unique().tolist() == ["lac0"]


def test_invalid_csv_is_refused(tmp_path):
    # A decreasing stage is refused before the pivot is written.
    src = tmp_path / "bad.csv"
    src.write_text("stage,volume,sarea\n90.0,1.0e6,4.0e5\n85.0,0.0,0.0\n", encoding="utf-8")
    dest = tmp_path / "bad.parquet"

    with pytest.raises(DataContractViolation):
        convert_abacus_to_parquet(src, dest, lake_id="lac0")

    assert not dest.exists()


def test_invalid_parquet_is_refused(tmp_path):
    # The contract is the single gate: a decreasing volume is refused too.
    src = tmp_path / "bad.parquet"
    pd.DataFrame(
        {
            "lake_id": ["lac0", "lac0"],
            "stage": [85.0, 90.0],
            "volume": [1.0e6, 0.0],
            "sarea": [4.0e5, 0.0],
        }
    ).to_parquet(src)
    dest = tmp_path / "out.parquet"

    with pytest.raises(DataContractViolation):
        convert_abacus_to_parquet(src, dest, lake_id="lac0")

    assert not dest.exists()
