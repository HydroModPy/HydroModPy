"""The solver builds its routing context with the engine the delineation used.

A solver reads the engine off the raster geometry of its model.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.fast


def _nwt():
    from hydromodpy.solver.modflow_nwt.nwt import nwt_solver

    return nwt_solver, nwt_solver.ModflowNwt._ensure_solver_routing_context


def test_a_provided_dem_is_filled_on_the_solver_grid(monkeypatch, tmp_path) -> None:
    """A DEM declared ``conditioned`` routes the solver grid with ``fill``.

    ``condition_dem`` refuses ``provided``, so the solver grid, its own
    template, is filled instead of routed as provided.
    """
    from hydromodpy.solver.modflow_common import routing_context

    captured: dict = {}

    def build_regional(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(correc="c", direc="d", acc="a")

    monkeypatch.setattr(routing_context, "build_regional_flow_products", build_regional)
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"x")
    routing_context.build_solver_routing_context(
        dem_path=dem,
        output_dir=tmp_path / "out",
        dem_correc_type="provided",
    )
    assert captured["dem_correc_type"] == "fill"


@pytest.mark.parametrize("method", ["fill", "breach", "capped_breach"])
def test_every_other_method_passes_through_unchanged(method, monkeypatch, tmp_path) -> None:
    from hydromodpy.solver.modflow_common import routing_context

    captured: dict = {}

    def build_regional(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(correc="c", direc="d", acc="a")

    monkeypatch.setattr(routing_context, "build_regional_flow_products", build_regional)
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"x")
    routing_context.build_solver_routing_context(
        dem_path=dem,
        output_dir=tmp_path / "out",
        dem_correc_type=method,
    )
    assert captured["dem_correc_type"] == method
