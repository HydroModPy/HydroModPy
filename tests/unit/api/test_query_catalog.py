"""Tests for :func:`hydromodpy.query_catalog`."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

import hydromodpy as hmp


def _seed_project_catalog(tmp_path: Path) -> Path:
    project_dir = tmp_path / "ws" / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "simulations").mkdir()
    with hmp.open(project_dir):
        pass
    return project_dir


def test_query_catalog_returns_dataframe(tmp_path: Path) -> None:
    project_dir = _seed_project_catalog(tmp_path)
    df = hmp.query_catalog("SELECT 42 AS answer", workspace=project_dir)
    assert df.iloc[0]["answer"] == 42


def test_query_catalog_missing_catalog_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        hmp.query_catalog("SELECT 1", workspace=empty)


def test_query_catalog_invalid_sql_raises_duckdb_error(tmp_path: Path) -> None:
    project_dir = _seed_project_catalog(tmp_path)
    with pytest.raises(duckdb.Error):
        hmp.query_catalog("THIS IS NOT SQL", workspace=project_dir)


def test_query_catalog_limit_clause(tmp_path: Path) -> None:
    project_dir = _seed_project_catalog(tmp_path)
    df = hmp.query_catalog(
        "SELECT 1 AS x UNION SELECT 2 UNION SELECT 3", workspace=project_dir, limit=2
    )
    assert len(df) == 2
