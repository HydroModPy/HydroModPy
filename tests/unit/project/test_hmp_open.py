"""The verb ``open`` of a project: its store reads the index, built when the project is read."""

from __future__ import annotations

from hydromodpy.project import api
from hydromodpy.project.facade import Project
from hydromodpy.results.catalog.facade import Catalog
from tests._helpers.run_builders import runs

__all__ = ["runs"]


def test_open_gives_a_project_whose_store_reads_the_index(runs):
    sim_id = runs.open().sim_id
    runs.catalog()
    runs.close_catalog()

    with api.open(runs.project_root) as proj:
        assert isinstance(proj, Project)
        assert isinstance(proj.store, Catalog)
        assert list(proj.store.simulations["sim_id"].astype(str)) == [sim_id]
