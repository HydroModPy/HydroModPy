from __future__ import annotations

import pytest

import hydromodpy as hmp
from hydromodpy.results.catalog import Catalog
from tests._helpers.sealed_runs import make_project

from ._test_simulation_api_builders import runs

__all__ = ["runs"]


class TestHmpOpen:
    def test_open_returns_the_reader_of_an_indexed_project(self, runs):
        sid = runs.open().sim_id
        runs.catalog()
        runs.close_catalog()

        with hmp.open(runs.project_root) as cat:
            assert isinstance(cat, Catalog)
            assert list(cat.simulations["sim_id"].astype(str)) == [sid]

    def test_open_never_creates_an_index(self, tmp_path):
        project = make_project(tmp_path / "project")
        with pytest.raises(FileNotFoundError):
            hmp.open(project)
        assert not (project / ".hmp" / "index.duckdb").exists()
