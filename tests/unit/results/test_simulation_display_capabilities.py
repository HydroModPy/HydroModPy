"""Figure applicability is decided from the figure's declared requirements.

A run only renders the figures whose ``FigureSpec`` requirements it
satisfies. ``BaseFigure.unavailable_reason`` is the single contract; there
is no second list of figure names kept on the ``Run``.
"""

from __future__ import annotations

from hydromodpy.display import get as get_figure
from hydromodpy.results.run import Run
from tests._helpers.run_builders import populate, runs

__all__ = ["runs"]


class TestFigureApplicability:
    def test_figure_needing_a_missing_field_is_unavailable(self, runs):
        sid = runs.open(n_cells=10, n_layers=1, flow_regime="steady").sim_id
        sim = Run(sid, runs.catalog())

        reason = get_figure("piezometric_map").unavailable_reason(sim)

        assert reason is not None
        assert "watertable_elevation" in reason

    def test_figure_needing_a_missing_table_is_unavailable(self, runs):
        sid = runs.open(n_cells=10, n_layers=1, flow_regime="steady").sim_id
        sim = Run(sid, runs.catalog())

        reason = get_figure("water_budget").unavailable_reason(sim)

        assert reason is not None
        assert "budgets" in reason

    def test_figure_becomes_available_once_its_table_exists(self, runs):
        store = runs.open(n_cells=10, n_layers=1, flow_regime="steady")
        populate(store)
        sim = Run(store.sim_id, runs.catalog())

        assert get_figure("water_budget").unavailable_reason(sim) is None
        assert get_figure("hydrograph").unavailable_reason(sim) is None

    def test_has_table_reports_catalog_content(self, runs):
        bare = runs.open(n_cells=10, n_layers=1, flow_regime="steady").sim_id
        filled = runs.open(n_cells=10, n_layers=1, flow_regime="steady")
        populate(filled)
        catalog = runs.catalog()

        assert Run(bare, catalog).has_table("budgets") is False
        assert Run(filled.sim_id, catalog).has_table("budgets") is True
