"""Figure applicability is decided from the figure's declared requirements.

A run only renders the figures whose ``FigureSpec`` requirements it
satisfies. ``BaseFigure.unavailable_reason`` is the single contract; there
is no second list of figure names kept on the ``Run``.
"""

from __future__ import annotations

from hydromodpy.display import get as get_figure
from hydromodpy.results.run import Run

from ._test_simulation_api_builders import _populate, _register, catalog

__all__ = ["catalog"]


class TestFigureApplicability:
    def test_figure_needing_a_missing_field_is_unavailable(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="steady")
        sim = Run(sid, catalog)

        reason = get_figure("piezometric_map").unavailable_reason(sim)

        assert reason is not None
        assert "watertable_elevation" in reason

    def test_figure_needing_a_missing_table_is_unavailable(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="steady")
        sim = Run(sid, catalog)

        reason = get_figure("water_budget").unavailable_reason(sim)

        assert reason is not None
        assert "budgets" in reason

    def test_figure_becomes_available_once_its_table_exists(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="steady")
        _populate(catalog, sid)
        sim = Run(sid, catalog)

        assert get_figure("water_budget").unavailable_reason(sim) is None
        assert get_figure("hydrograph").unavailable_reason(sim) is None

    def test_has_table_reports_catalog_content(self, catalog):
        sid = _register(catalog, n_cells=10, n_layers=1, flow_regime="steady")
        sim = Run(sid, catalog)
        assert sim.has_table("budgets") is False

        _populate(catalog, sid)
        assert Run(sid, catalog).has_table("budgets") is True
