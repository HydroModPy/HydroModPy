"""The solver routes its grid with the DEM correction method the delineation used.

``condition_dem`` refuses ``provided``, so a DEM declared that way is filled on the
solver grid, which is its own template. Every other method is passed on unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.solver.modflow_common import routing_context

pytestmark = pytest.mark.fast

METHODS = [
    pytest.param("provided", "fill", id="provided becomes fill"),
    pytest.param("fill", "fill", id="fill"),
    pytest.param("breach", "breach", id="breach"),
    pytest.param("capped_breach", "capped_breach", id="capped breach"),
]


@pytest.mark.parametrize(("declared", "routed"), METHODS)
def test_correction_method_of_the_solver_grid(declared, routed, monkeypatch, tmp_path) -> None:
    captured: dict = {}

    def build_regional(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(correc="c", direc="d", acc="a")

    monkeypatch.setattr(routing_context, "build_regional_flow_products", build_regional)
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"x")

    routing_context.build_solver_routing_context(
        dem_path=dem, output_dir=tmp_path / "out", dem_correc_type=declared
    )

    assert captured["dem_correc_type"] == routed
