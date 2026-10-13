"""A solver paired with a mesh engine it cannot read is refused while the file loads.

The check runs before any step, so a NWT run with ``engine = "voronoi"`` never
reaches the geographic step. The refusal names the solver and the engine.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.solver.base import registry as solver_registry
from hydromodpy.spatial.mesh import registry as mesh_registry
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.port import MeshEngineCapabilities


def _payload(solver: str, mesh: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "solver": {"backend": {"backend": solver}},
    }
    if mesh is not None:
        payload["mesh"] = mesh
    return payload


@pytest.mark.parametrize("engine", ["triangle", "voronoi"])
def test_nwt_refuses_an_unstructured_engine_and_names_both(engine: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(_payload("modflow_nwt", {"engine": engine}))
    message = str(excinfo.value)
    assert "'modflow_nwt'" in message
    assert f"mesh.engine is '{engine}'" in message
    assert "reads the meshes of the engines regular" in message
    assert "modflow6" in message


@pytest.mark.parametrize("mesh", [None, {"engine": "regular"}, {"engine": "voronoi"}])
def test_boussinesq_reads_the_triangle_engine_only(mesh: dict[str, Any] | None) -> None:
    with pytest.raises(ValueError) as excinfo:
        HydroModPyConfig.model_validate(_payload("boussinesq", mesh))
    message = str(excinfo.value)
    assert "'boussinesq'" in message
    assert "engines triangle" in message
    expected = "regular" if mesh is None else mesh["engine"]
    assert f"mesh.engine is '{expected}'" in message


def test_the_default_engine_is_named_as_the_default() -> None:
    with pytest.raises(ValueError, match=r"mesh\.engine is 'regular' \(the default\)"):
        HydroModPyConfig.model_validate(_payload("boussinesq", None))


@pytest.mark.parametrize(
    ("solver", "engine"),
    [
        ("modflow6", "regular"),
        ("modflow6", "triangle"),
        ("modflow6", "voronoi"),
        ("modflow_nwt", "regular"),
        ("boussinesq", "triangle"),
    ],
)
def test_a_pair_the_solver_reads_loads(solver: str, engine: str) -> None:
    cfg = HydroModPyConfig.model_validate(_payload(solver, {"engine": engine}))
    assert cfg.mesh is not None and cfg.mesh.engine == engine


def test_no_mesh_section_is_the_regular_engine() -> None:
    cfg = HydroModPyConfig.model_validate(_payload("modflow_nwt", None))
    assert cfg.mesh is None


class _PolygonEngine:
    engine_id: ClassVar[str] = "fake_polygon"
    engine_version: ClassVar[str] = "1.0.0"
    capabilities: ClassVar[MeshEngineCapabilities] = MeshEngineCapabilities(
        cell_types=(CellType.POLYGON,),
        structured=False,
        graded=True,
        exact_faces=False,
        cell_families="derived_from_faces",
        deterministic=True,
        needs_cache=False,
    )

    def build(self, request: object) -> object:
        raise NotImplementedError


@pytest.fixture
def polygon_engine():
    mesh_registry.register(_PolygonEngine)
    try:
        yield _PolygonEngine
    finally:
        mesh_registry.unregister(_PolygonEngine.engine_id)


def test_modflow6_reads_a_third_party_engine_of_polygon_cells(polygon_engine: type) -> None:
    cfg = HydroModPyConfig.model_validate(_payload("modflow6", {"engine": "fake_polygon"}))
    assert cfg.mesh is not None and cfg.mesh.engine == "fake_polygon"


@pytest.mark.parametrize("solver", ["modflow_nwt", "boussinesq"])
def test_a_solver_that_lists_engine_ids_refuses_a_third_party_engine(
    polygon_engine: type, solver: str
) -> None:
    with pytest.raises(ValueError, match="mesh.engine is 'fake_polygon'") as excinfo:
        HydroModPyConfig.model_validate(_payload(solver, {"engine": "fake_polygon"}))
    assert "modflow6" in str(excinfo.value)


def test_the_table_of_the_registry_gives_the_builtin_answers() -> None:
    assert solver_registry.accepted_meshes("flow", "modflow_nwt") == {"regular"}
    assert solver_registry.accepted_meshes("flow", "boussinesq") == {"triangle"}
    mf6 = solver_registry.accepted_meshes("flow", "modflow6")
    assert {"regular", "triangle", "voronoi", "*planar"} == set(mf6)


def test_a_flow_adapter_that_declares_nothing_reads_the_regular_engine() -> None:
    class _Silent:
        process_type = "flow"
        solver_name = "silent_for_meshes"
        requires = ()

        def validate(self, ctx): ...
        def execute(self, ctx): ...
        def cleanup(self, ctx): ...
        def extract_observables(self, ctx, store, requests, *, time_index=None): ...

    solver_registry.register("flow", "silent_for_meshes", _Silent)
    try:
        assert solver_registry.accepted_meshes("flow", "silent_for_meshes") == {"regular"}
    finally:
        solver_registry.unregister("flow", "silent_for_meshes")
