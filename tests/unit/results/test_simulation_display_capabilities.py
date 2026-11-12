"""Figure applicability is decided from the figure's declared requirements.

A run only renders the figures whose ``FigureSpec`` requirements it
satisfies. ``BaseFigure.unavailable_reason`` is the single contract; there
is no second list of figure names kept on the ``Run``.
"""

from __future__ import annotations

from hydromodpy.display.figure_registry import get as get_figure
from hydromodpy.results.run.view import Run
from tests._helpers.run_builders import runs

__all__ = ["runs"]


class TestFigureApplicability:
    def test_figure_needing_a_missing_table_is_unavailable(self, runs):
        sid = runs.open(n_cells=10, n_layers=1, flow_regime="steady").sim_id
        sim = Run(sid, runs.catalog())

        reason = get_figure("water_budget").unavailable_reason(sim)

        assert reason is not None
        assert "budgets" in reason
