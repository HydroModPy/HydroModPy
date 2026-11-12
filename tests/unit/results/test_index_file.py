"""The index file: its lock, its staging copy in blocks of 16 KiB, its publication and its readers."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

import duckdb
import pytest

from hydromodpy.core.exceptions import CatalogUnreadableError, WriteConflictError
from hydromodpy.core.io.lock_file import LockFile
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.catalog.index_file import (
    INDEX_LEASE_S,
    discard_staging,
    index_lock,
    index_lock_path,
    new_staging,
    open_index,
    open_staging,
    publish_staging,
)
from tests._helpers.sealed_runs import make_project


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_project(tmp_path / "demo")


def _publish_value(root: Path, value: int) -> None:
    """Publish an index holding one table ``t`` with one row ``value``."""
    index_path = catalog_path_for(root)
    with index_lock(root) as lock:
        staging = new_staging(index_path, copy_of=None)
        connection = open_staging(staging)
        connection.execute("CREATE TABLE t (x INTEGER)")
        connection.execute("INSERT INTO t VALUES (?)", [value])
        connection.execute("CHECKPOINT")
        connection.close()
        publish_staging(staging, index_path, lock)


def _value(connection: duckdb.DuckDBPyConnection) -> int:
    return int(connection.execute("SELECT x FROM t").fetchone()[0])


def _foreign_lock(root: Path) -> dict:
    """Write a fresh lock in the name of a live process of this host that is not this one."""
    holder = {"pid": os.getppid(), "host": socket.gethostname(), "created": time.time()}
    path = index_lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(holder), encoding="utf-8")
    return holder


# -- the lock ---------------------------------------------------------------


# -- the staging file ---------------------------------------------------------


# -- publication --------------------------------------------------------------


@pytest.mark.parametrize(
    "lose",
    ["released", "taken_back", "never_taken"],
)
def test_a_staging_file_is_not_published_without_the_lock(root, lose):
    _publish_value(root, 1)
    index_path = catalog_path_for(root)
    before = index_path.read_bytes()
    lock = LockFile(index_lock_path(root), stale_after_s=INDEX_LEASE_S, wait_s=0.0)
    if lose != "never_taken":
        assert lock.acquire()
    if lose == "released":
        lock.release()
    if lose == "taken_back":
        _foreign_lock(root)
    staging = new_staging(index_path, copy_of=index_path)
    try:
        with pytest.raises(WriteConflictError) as refused:
            publish_staging(staging, index_path, lock)
    finally:
        discard_staging(staging)

    assert "another process took .hmp/index.duckdb.lock while this one wrote" in str(refused.value)
    assert "the index it wrote is dropped" in str(refused.value)
    assert index_path.read_bytes() == before


# -- readers ------------------------------------------------------------------


def test_open_index_without_an_index_is_file_not_found(root):
    with pytest.raises(FileNotFoundError, match="the project has no index yet"):
        open_index(root)


def test_open_index_on_a_broken_file_is_unreadable(root):
    index_path = catalog_path_for(root)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"not a database")

    with pytest.raises(CatalogUnreadableError, match="hmp catalog reindex"):
        open_index(root)
