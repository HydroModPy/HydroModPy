"""Boussinesq applies a ``Project.run(properties=...)`` override of K and Sy, or refuses it.

The run handed its override to the build through ``setup.flow_runtime_overrides``.
MODFLOW 6 and MODFLOW-NWT read it, Boussinesq did not, so a run with
``properties={"K": ...}`` solved on the flow K without a word. The backend now
reads the K and Sy overrides (Sy only on a transient run), refuses the
properties it does not read by name, and refuses any override next to a mesh
bundle, which carries its own values.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.boussinesq import flow_to_boussinesq_adapter as adapter
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.property_mapping import (
    resolve_flow_property_arrays,
    resolve_required_flow_properties,
)
from hydromodpy.spatial.field.core.field_param import FieldParam
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

FLOW_K = 1e-4
FLOW_SY = 0.1
K_NAME = "hydraulic_conductivity_m_s"
SY_NAME = "storage_coefficient"


def _cell_mesh():
    mesh = solver_mesh_from_structured_arrays(
        nrow=2, ncol=2, top=np.full((2, 2), 30.0), botm=np.zeros((1, 2, 2))
    )
    return mesh.cell_mesh


def _flow(regime: str = "transient") -> SimpleNamespace:
    return SimpleNamespace(
        flow_regime=regime,
        parameters={
            "K": FieldParam(identifier="K", kind="homogeneous", value=FLOW_K),
            "Sy": FieldParam(identifier="Sy", kind="homogeneous", value=FLOW_SY),
        },
    )


def _arrays(regime: str, overrides: object) -> dict[str, np.ndarray]:
    return resolve_flow_property_arrays(
        flow=_flow(regime),
        domain=SimpleNamespace(zones={}),
        cell_mesh=_cell_mesh(),
        required_properties=resolve_required_flow_properties(flow_regime=regime),
        runtime_property_overrides=overrides,
    )


def test_without_an_override_the_flow_values_are_read() -> None:
    arrays = _arrays("transient", None)
    assert np.all(arrays[K_NAME] == FLOW_K)
    assert np.all(arrays[SY_NAME] == FLOW_SY)


def test_a_scalar_override_of_k_and_sy_wins_over_the_flow() -> None:
    arrays = _arrays("transient", {"source": "project_run", "properties": {"K": 3e-5, "Sy": 0.2}})
    assert np.all(arrays[K_NAME] == 3e-5)
    assert np.all(arrays[SY_NAME] == 0.2)


def test_an_override_of_k_alone_leaves_sy_on_the_flow() -> None:
    arrays = _arrays("transient", {"properties": {"K": 3e-5}})
    assert np.all(arrays[K_NAME] == 3e-5)
    assert np.all(arrays[SY_NAME] == FLOW_SY)


def test_a_per_cell_override_reaches_each_cell() -> None:
    per_cell = np.array([1e-5, 2e-5, 3e-5, 4e-5])
    arrays = _arrays("transient", {"properties": {"K": per_cell}})
    np.testing.assert_allclose(arrays[K_NAME], per_cell)


@pytest.mark.parametrize("key", ["Kv", "Ss", "K22", "angle1", "angle2", "angle3"])
def test_a_property_the_backend_does_not_read_is_refused_by_name(key: str) -> None:
    canonical = {"Kv": "Kv", "Ss": "Ss"}.get(key, key)
    with pytest.raises(ValueError, match=f"sets {canonical}, which this solver does not read"):
        _arrays("transient", {"properties": {"K": 3e-5, key: 1.0}})


def test_sy_is_refused_on_a_steady_run_that_does_not_read_it() -> None:
    with pytest.raises(ValueError, match="sets Sy, which this solver does not read: it reads K"):
        _arrays("steady", {"properties": {"Sy": 0.2}})


def test_a_steady_run_reads_a_k_override() -> None:
    arrays = _arrays("steady", {"properties": {"K": 3e-5}})
    assert np.all(arrays[K_NAME] == 3e-5)
    assert SY_NAME not in arrays


def test_a_name_that_is_no_property_is_refused() -> None:
    with pytest.raises(ValueError, match="K_22 name no flow property"):
        _arrays("transient", {"properties": {"K": 3e-5, "K_22": 1e-5}})


def test_the_sandbox_keys_of_a_calibration_trial_are_not_properties() -> None:
    arrays = _arrays("transient", {"model_name_override": "trial000001"})
    assert np.all(arrays[K_NAME] == FLOW_K)


def _setup(overrides: object) -> SimpleNamespace:
    return SimpleNamespace(
        cell_mesh=_cell_mesh(),
        flow=_flow(),
        domain=SimpleNamespace(zones={}),
        mesh_summary=None,
        flow_runtime_overrides=overrides,
    )


def _solver_mesh_inputs(monkeypatch: pytest.MonkeyPatch, setup: SimpleNamespace) -> dict:
    """The properties the runtime solver mesh is built with, whatever the geometry."""
    seen: dict[str, np.ndarray] = {}

    def capture(cell_mesh, **kwargs):
        seen["conductivity"] = np.asarray(kwargs["hydraulic_conductivity_m_s"])
        seen["storage"] = np.asarray(kwargs["storage_coefficient"])

    monkeypatch.setattr(BoussinesqMesh, "from_cell_mesh", staticmethod(capture))
    adapter.resolve_runtime_solver_mesh(setup)
    return seen


def test_a_project_run_override_reaches_the_solver_mesh(monkeypatch: pytest.MonkeyPatch) -> None:
    overrides = {"source": "project_run", "properties": {"K": 5e-6}}
    seen = _solver_mesh_inputs(monkeypatch, _setup(overrides))
    assert np.all(seen["conductivity"] == 5e-6)
    assert np.all(seen["storage"] == FLOW_SY)


def test_a_run_without_override_keeps_the_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _solver_mesh_inputs(monkeypatch, _setup(None))
    assert np.all(seen["conductivity"] == FLOW_K)


def test_a_project_run_override_of_k22_is_refused_before_the_solve() -> None:
    with pytest.raises(ValueError, match="sets K22, which this solver does not read"):
        adapter.resolve_runtime_solver_mesh(
            _setup({"source": "project_run", "properties": {"K22": 1e-5}})
        )


def _bundle() -> SimpleNamespace:
    return SimpleNamespace(bundle_dir="bundle", cells=(object(), object(), object()))


def test_an_override_next_to_a_mesh_bundle_is_refused() -> None:
    setup = SimpleNamespace(
        flow=None, flow_runtime_overrides={"source": "project_run", "properties": {"K": 5e-6}}
    )
    with pytest.raises(ValueError, match="sets K on the mesh bundle bundle"):
        adapter.resolve_bundle_solver_mesh(setup, bundle=_bundle())
