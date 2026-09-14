"""convert_abacus_to_parquet: CSV/Parquet round-trip and lake_id inject.

Guards that a user abacus (CSV or Parquet, no lake_id column) is normalised into
the validated Parquet pivot with the lake_id injected and the numeric
stage/volume/area values preserved, and that a Parquet source is validated too.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.adapters import convert_abacus_to_parquet


def test_csv_without_lake_id_round_trips_with_injected_id(tmp_path) -> None:
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
    assert list(df.columns) == ["lake_id", "stage", "volume", "sarea"]
    assert df["lake_id"].unique().tolist() == ["lac0"]
    assert df["stage"].tolist() == pytest.approx([85.0, 87.0, 90.0])
    assert df["volume"].tolist() == pytest.approx([0.0, 200000.0, 1200000.0])
    assert df["sarea"].tolist() == pytest.approx([0.0, 100000.0, 400000.0])


def test_existing_lake_id_column_is_preserved(tmp_path) -> None:
    src = tmp_path / "abacus.csv"
    src.write_text(
        "lake_id,stage,volume,sarea\nretenue,85.0,0.0,0.0\nretenue,90.0,1.0e6,4.0e5\n",
        encoding="utf-8",
    )
    out = convert_abacus_to_parquet(src, tmp_path / "out.parquet", lake_id="ignored")
    df = pd.read_parquet(out)
    assert df["lake_id"].unique().tolist() == ["retenue"]


def test_invalid_csv_is_rejected_by_the_schema(tmp_path) -> None:
    src = tmp_path / "bad.csv"
    # Non-monotone stage must be caught before the file is written.
    src.write_text(
        "stage,volume,sarea\n90.0,1.0e6,4.0e5\n85.0,0.0,0.0\n",
        encoding="utf-8",
    )
    dest = tmp_path / "bad.parquet"
    with pytest.raises(DataContractViolation):
        convert_abacus_to_parquet(src, dest, lake_id="lac0")
    assert not dest.exists()


def test_parquet_source_is_normalised_and_validated(tmp_path) -> None:
    # A pre-built .parquet abacus must round-trip through the pivot (read with
    # pyarrow, not pd.read_csv) and be validated like a CSV source.
    src = tmp_path / "raw.parquet"
    pd.DataFrame({"stage": [85.0, 90.0], "volume": [0.0, 1.0e6], "sarea": [0.0, 4.0e5]}).to_parquet(
        src
    )
    dest = tmp_path / "pivot.parquet"
    out = convert_abacus_to_parquet(src, dest, lake_id="lac0")
    df = pd.read_parquet(out)
    assert list(df.columns) == ["lake_id", "stage", "volume", "sarea"]
    assert df["lake_id"].unique().tolist() == ["lac0"]


def test_invalid_parquet_source_is_rejected(tmp_path) -> None:
    # The contract is the single gate even for a .parquet source: a decreasing
    # volume must be rejected before the pivot is written.
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
