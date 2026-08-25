"""TableRecord contract: in-memory vs. file-backed tables, lazy caching.

Guards that ``LoadResult`` can carry tabular data (lake
abacus) that is neither a time series nor a gridded field, and that a
Path-backed record reads its Parquet lazily and caches the frame.
"""

from __future__ import annotations

import pandas as pd

from hydromodpy.data.contracts import LoadResult, TableRecord


def _abacus_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "lake_id": ["lac0", "lac0", "lac0"],
            "stage": [85.0, 87.0, 90.0],
            "volume": [0.0, 2.0e5, 1.2e6],
            "sarea": [0.0, 1.0e5, 4.0e5],
        }
    )


def test_in_memory_table_record_is_not_a_file_reference() -> None:
    rec = TableRecord(
        variable="lake_abacus",
        source="custom",
        table_id="lac0",
        data=_abacus_frame(),
        unit="m|m3|m2",
    )
    assert rec.is_file_reference is False
    pd.testing.assert_frame_equal(rec.frame, _abacus_frame())


def test_file_backed_table_record_reads_and_caches(tmp_path) -> None:
    parquet = tmp_path / "lac0.parquet"
    _abacus_frame().to_parquet(parquet)

    rec = TableRecord(
        variable="lake_abacus",
        source="custom",
        table_id="lac0",
        data=parquet,
    )
    assert rec.is_file_reference is True

    first = rec.frame
    pd.testing.assert_frame_equal(first.reset_index(drop=True), _abacus_frame(), check_dtype=False)
    # After the first read the Path is replaced by the cached DataFrame.
    assert rec.is_file_reference is False
    assert rec.frame is first


def test_load_result_tables_participate_in_len_bool_and_records() -> None:
    rec = TableRecord(
        variable="lake_abacus",
        source="custom",
        table_id="lac0",
        data=_abacus_frame(),
    )
    empty = LoadResult()
    assert not empty
    assert empty.has_tables is False

    result = LoadResult(tables=[rec])
    assert bool(result) is True
    assert result.has_tables is True
    assert len(result) == 1
    assert result.all_records == [rec]
