from __future__ import annotations

import duckdb
import pytest

import hydromodpy.core.io.db_retry as db_retry


def test_connect_with_retry_retries_lock_contention_until_success(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []
    sentinel = object()

    def fake_connect(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 4:
            raise duckdb.IOException("IO Error: conflicting lock is held by another process")
        return sentinel

    monkeypatch.setattr(db_retry.duckdb, "connect", fake_connect)
    monkeypatch.setattr(db_retry.time, "sleep", sleeps.append)
    monkeypatch.setattr(db_retry.random, "uniform", lambda a, b: 0.0)

    conn = db_retry.connect_with_retry(
        "workspace.duckdb",
        retries=4,
        backoff=0.1,
        max_backoff=1.0,
    )

    assert conn is sentinel
    assert calls["count"] == 4
    assert sleeps == [0.1, 0.2, 0.4]


def test_connect_with_retry_does_not_retry_non_lock_io_errors(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_connect(*args, **kwargs):
        calls["count"] += 1
        raise duckdb.IOException("IO Error: Cannot open file 'missing.duckdb': No such file")

    monkeypatch.setattr(db_retry.duckdb, "connect", fake_connect)
    monkeypatch.setattr(db_retry.time, "sleep", sleeps.append)

    with pytest.raises(duckdb.IOException, match="No such file"):
        db_retry.connect_with_retry(
            "missing.duckdb",
            retries=4,
            backoff=0.1,
            max_backoff=1.0,
        )

    assert calls["count"] == 1
    assert sleeps == []


def test_with_lock_retry_retries_lock_contention_until_success(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []

    monkeypatch.setattr(db_retry.time, "sleep", sleeps.append)
    monkeypatch.setattr(db_retry.random, "uniform", lambda a, b: 0.0)

    @db_retry.with_lock_retry(retries=3, backoff=0.1, max_backoff=1.0)
    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise duckdb.IOException("IO Error: file is used by another process")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 3
    assert sleeps == [0.1, 0.2]
