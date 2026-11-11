"""The verb ``open`` of a project: its store reads the index, built when the project is read."""

from __future__ import annotations

from hydromodpy.project import api
from hydromodpy.project.facade import Project
from hydromodpy.results.catalog import Catalog
from tests._helpers.run_builders import runs
from tests._helpers.sealed_runs import make_project

__all__ = ["runs"]


class TestHmpOpen:
    def test_open_returns_the_project_whose_store_reads_the_index(self, runs):
        sid = runs.open().sim_id
        runs.catalog()
        runs.close_catalog()

        with api.open(runs.project_root) as proj:
            assert isinstance(proj, Project)
            assert isinstance(proj.store, Catalog)
            assert list(proj.store.simulations["sim_id"].astype(str)) == [sid]

    def test_opening_creates_no_index_until_the_project_is_read(self, tmp_path):
        project = make_project(tmp_path / "project")
        with api.open(project) as proj:
            assert not (project / ".hmp" / "index.duckdb").exists()
            assert proj.cases.empty
        assert (project / ".hmp" / "index.duckdb").exists()
