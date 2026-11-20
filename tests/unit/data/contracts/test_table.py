"""Table record: a lake abacus (stage m, volume m3, area m2) held in memory or in a Parquet file.

A file-backed record reads its Parquet on first use and then keeps the frame.
"""

from __future__ import annotations

import pandas as pd

from hydromodpy.data.contracts.table import TableRecord


def _abacus_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "lake_id": ["lac0", "lac0", "lac0"],
            "stage": [85.0, 87.0, 90.0],
            "volume": [0.0, 2.0e5, 1.2e6],
            "sarea": [0.0, 1.0e5, 4.0e5],
        }
    )


def test_in_memory_table() -> None:
    rec = TableRecord(
        variable="lake_abacus",
        source="file",
        table_id="lac0",
        data=_abacus_frame(),
        unit="m|m3|m2",
    )
    assert rec.is_file_reference is False
    pd.testing.assert_frame_equal(rec.frame, _abacus_frame())


def test_file_backed_table_is_cached(tmp_path) -> None:
    parquet = tmp_path / "lac0.parquet"
    _abacus_frame().to_parquet(parquet)

    rec = TableRecord(
        variable="lake_abacus",
        source="file",
        table_id="lac0",
        data=parquet,
    )
    assert rec.is_file_reference is True

    first = rec.frame
    pd.testing.assert_frame_equal(first.reset_index(drop=True), _abacus_frame(), check_dtype=False)
    # After the first read the Path is replaced by the cached DataFrame.
    assert rec.is_file_reference is False
    assert rec.frame is first
