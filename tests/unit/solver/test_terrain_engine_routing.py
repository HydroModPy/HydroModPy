"""Both solver families build their routing context with the engine the delineation used.

A solver reads the engine off the runtime geographic object. MODFLOW-NWT does not share
``ensure_solver_routing_context`` with MODFLOW 6, it carries its own copy of the call, so plumbing
only one of the two leaves half the runs routing with the build default.
"""

from types import SimpleNamespace

import pytest

from hydromodpy.spatial.terrain import registry

pytestmark = pytest.mark.fast


def _mf6():
    from hydromodpy.solver.modflow6 import build

    return build, build.ensure_solver_routing_context


def _nwt():
    from hydromodpy.solver.modflow_nwt.nwt import nwt_solver

    return nwt_solver, nwt_solver.ModflowNwt._ensure_solver_routing_context


@pytest.mark.parametrize("family", [_mf6, _nwt], ids=["modflow6", "modflow-nwt"])
def test_the_solver_routing_context_is_built_with_the_configured_engine(
    family, monkeypatch, tmp_path
) -> None:
    module, ensure = family()
    engine_id = registry.builtin_engine_ids()[0]
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
        geographic=SimpleNamespace(terrain_engine=engine_id),
    )
    ensure(solver)
    assert captured["engine_id"] == engine_id
