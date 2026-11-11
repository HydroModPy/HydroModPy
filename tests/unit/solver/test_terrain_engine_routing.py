"""The solver builds its routing context with the engine the delineation used.

A solver reads the engine off the raster geometry of its model.
"""

from types import SimpleNamespace

import pytest

from hydromodpy.catchment.terrain import registry
from hydromodpy.model.domain.geometry import RasterGeometry
from hydromodpy.model.model import Geometry
from tests._helpers.model_factory import make_model

pytestmark = pytest.mark.fast


def _nwt():
    from hydromodpy.solver.modflow_nwt.nwt import nwt_solver

    return nwt_solver, nwt_solver.ModflowNwt._ensure_solver_routing_context


def test_the_solver_routing_context_is_built_with_the_configured_engine(
    monkeypatch, tmp_path
) -> None:
    module, ensure = _nwt()
    engine_id = registry.terrain_engines.names(shipped_only=True)[0]
    captured: dict = {}

    def build(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(module, "build_solver_routing_context", build)
    solver = SimpleNamespace(
        routing_ctx=None,
        grid_ctx=SimpleNamespace(),
        dem_watershed_path=str(tmp_path / "dem.tif"),
        full_path=str(tmp_path),
        inputs=make_model(
            geometry=Geometry(
                cells=None,
                domain=None,
                raster=RasterGeometry.from_geographic(SimpleNamespace(terrain_engine=engine_id)),
            )
        ),
    )
    ensure(solver)
    assert captured["engine_id"] == engine_id


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
