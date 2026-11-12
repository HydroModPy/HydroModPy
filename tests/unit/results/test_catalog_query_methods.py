from __future__ import annotations

import pytest

from hydromodpy.results.catalog.discovery import SimulationNotFoundError
from tests._helpers.run_builders import runs

__all__ = ["runs"]


class TestCatalogQueryMethods:
    def test_simulations_property(self, runs):
        runs.open(project="a")
        runs.open(project="b")
        assert len(runs.catalog().simulations) == 2

    def test_getitem_not_found(self, runs):
        runs.open()
        with pytest.raises(SimulationNotFoundError):
            _ = runs.catalog()["nonexistent"]

    def test_find_by_tags(self, runs):
        runs.open(tags=["transient", "test"])
        runs.open(tags=["steady"])
        assert runs.catalog().find(tags="transient").count == 1

    def test_find_unknown_filter(self, runs):
        runs.open()
        with pytest.raises(ValueError, match="Unknown filter"):
            runs.catalog().find(nonexistent_field="x")

    def test_latest(self, runs):
        runs.open(project="p1")
        runs.catalog()
        second = runs.open(project="p1").sim_id
        assert runs.catalog().latest("p1").sim_id == second

    def test_latest_not_found(self, runs):
        runs.open(project="p1")
        with pytest.raises(KeyError):
            runs.catalog().latest("nonexistent")

    def test_best_not_found(self, runs):
        runs.open(project="p1")
        with pytest.raises(KeyError):
            runs.catalog().best("nonexistent", metric="nse")
