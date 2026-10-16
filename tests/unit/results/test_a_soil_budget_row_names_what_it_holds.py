"""A ``soil_budget`` row names exactly what it holds: no silent extra column."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.storage.parquet_schemas import primary_key_for
from tests._helpers.run_stores import open_run_store


def test_soil_budget_declares_its_primary_key() -> None:
    assert primary_key_for("soil_budget") == ("sim_id", "column_id", "year")


def test_an_undeclared_column_is_refused_by_name(tmp_path: Path) -> None:
    with open_run_store(tmp_path / "project", "run", n_cells=1, n_layers=1) as store:
        with pytest.raises(KeyError, match="not_a_column"):
            store.write_view(
                store.sim_id,
                "soil_budget",
                [{"column_id": "0.0", "year": 2020, "not_a_column": 1.0}],
            )
