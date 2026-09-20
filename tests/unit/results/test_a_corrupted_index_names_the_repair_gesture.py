"""A DuckDB index that exists but will not open must say what to run.

Before this test the corruption escaped ``connect_with_retry`` untyped: only
``duckdb.IOException`` with a lock-contention message was ever caught, so a
truncated write - a real open failure, not a race - propagated as DuckDB's
own C trace. Nothing told the caller that ``hmp catalog reindex`` already
works on a broken index, because it never opens the broken file at all: it
writes a fresh one next to it and publishes by atomic replace.

The corruption here is real: a valid DuckDB file is written, closed, then
truncated to half its size on disk.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.exceptions import CatalogUnreadableError
from hydromodpy.core.io.db_retry import connect_with_retry


@pytest.fixture
def truncated_index(tmp_path: Path) -> Path:
    """A DuckDB file that opened fine once, now missing its back half."""
    index = tmp_path / "index.duckdb"
    connection = duckdb.connect(str(index))
    connection.execute("CREATE TABLE simulations (sim_id VARCHAR)")
    connection.close()

    size = index.stat().st_size
    with open(index, "r+b") as handle:
        handle.truncate(size // 2)

    return index


def test_a_truncated_index_raises_the_typed_exception(truncated_index: Path) -> None:
    with pytest.raises(CatalogUnreadableError):
        connect_with_retry(str(truncated_index))


def test_the_message_names_the_broken_file(truncated_index: Path) -> None:
    with pytest.raises(CatalogUnreadableError) as excinfo:
        connect_with_retry(str(truncated_index))

    assert str(truncated_index) in str(excinfo.value)


def test_the_message_names_the_working_repair_gesture(truncated_index: Path) -> None:
    with pytest.raises(CatalogUnreadableError) as excinfo:
        connect_with_retry(str(truncated_index))

    assert "reindex" in str(excinfo.value)


def test_a_missing_index_still_raises_the_bare_duckdb_error(tmp_path: Path) -> None:
    """A path that does not exist yet is a different failure, not corruption.

    ``connect_with_retry`` must not claim a file "exists but could not be
    opened" when there is no file at all: that branch stays untyped.
    """
    missing = tmp_path / "never_written.duckdb"

    with pytest.raises(duckdb.Error) as excinfo:
        connect_with_retry(str(missing), read_only=True)

    assert not isinstance(excinfo.value, CatalogUnreadableError)
