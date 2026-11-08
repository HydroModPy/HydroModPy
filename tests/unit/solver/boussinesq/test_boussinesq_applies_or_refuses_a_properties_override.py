"""Boussinesq applies a ``Project.run(properties=...)`` override of K and Sy, or refuses it.

The run hands its override to the solver in ``Model.properties.overrides``, set
by ``Model.with_properties``. MODFLOW 6 and MODFLOW-NWT read it, Boussinesq did
not, so a run with ``properties={"K": ...}`` solved on the flow K without a word.
The backend reads the K and Sy overrides (Sy only on a transient run), refuses
the properties it does not read by name, and refuses any override next to a
mesh bundle, which carries its own values.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.model.model import Geometry, Model, ModelTime, Properties
from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.properties.property_table import resolve_required_flow_properties
from hydromodpy.solver.boussinesq import flow_to_boussinesq_adapter as adapter
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.property_mapping import resolve_flow_property_arrays
from tests._helpers.model_factory import make_model
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


def _profiles() -> dict[str, FieldParam]:
    return {
        "K": FieldParam(identifier="K", kind="homogeneous", value=FLOW_K),
        "Sy": FieldParam(identifier="Sy", kind="homogeneous", value=FLOW_SY),
    }


def _model(regime: str = "transient", *, profiles: dict | None = None, **overrides) -> Model:
    """A model on a 2 x 2 cell mesh whose per-cell overrides are ``overrides``."""
    return make_model(
        geometry=Geometry(cells=_cell_mesh(), domain=SimpleNamespace(zones={})),
        properties=Properties(
            profiles=_profiles() if profiles is None else profiles, overrides=overrides
        ),
        time=ModelTime(grid=None, regime=regime, first_period_steady=True),
    )


def _arrays(regime: str, overrides: object) -> dict[str, np.ndarray]:
    return resolve_flow_property_arrays(
        profiles=_profiles(),
        domain=SimpleNamespace(zones={}),
        cell_mesh=_cell_mesh(),
        required_properties=resolve_required_flow_properties(flow_regime=regime, storage=("Sy",)),
        runtime_property_overrides=overrides,
    )


def test_without_an_override_the_flow_values_are_read() -> None:
    arrays = _arrays("transient", None)
    assert np.all(arrays[K_NAME] == FLOW_K)
    assert np.all(arrays[SY_NAME] == FLOW_SY)


def test_a_scalar_override_of_k_and_sy_wins_over_the_flow() -> None:
    arrays = _arrays("transient", {"K": 3e-5, "Sy": 0.2})
    assert np.all(arrays[K_NAME] == 3e-5)
    assert np.all(arrays[SY_NAME] == 0.2)


def test_an_override_of_k_alone_leaves_sy_on_the_flow() -> None:
    arrays = _arrays("transient", {"K": 3e-5})
    assert np.all(arrays[K_NAME] == 3e-5)
    assert np.all(arrays[SY_NAME] == FLOW_SY)


def test_a_per_cell_override_reaches_each_cell() -> None:
    per_cell = np.array([1e-5, 2e-5, 3e-5, 4e-5])
    arrays = _arrays("transient", {"K": per_cell})
    np.testing.assert_allclose(arrays[K_NAME], per_cell)


@pytest.mark.parametrize("key", ["Kv", "Ss", "K22", "angle1", "angle2", "angle3"])
def test_a_property_the_backend_does_not_read_is_refused_by_name(key: str) -> None:
    canonical = {"Kv": "Kv", "Ss": "Ss"}.get(key, key)
    with pytest.raises(ValueError, match=f"sets {canonical}, which this solver does not read"):
        _arrays("transient", {"K": 3e-5, key: 1e-5})


def test_sy_is_refused_on_a_steady_run_that_does_not_read_it() -> None:
    with pytest.raises(ValueError, match="sets Sy, which this solver does not read: it reads K"):
        _arrays("steady", {"Sy": 0.2})


def test_a_steady_run_reads_a_k_override() -> None:
    arrays = _arrays("steady", {"K": 3e-5})
    assert np.all(arrays[K_NAME] == 3e-5)
    assert SY_NAME not in arrays


def test_a_name_that_is_no_property_is_refused_by_the_model() -> None:
    with pytest.raises(ValueError, match="K_22 name no flow property"):
        make_model().with_properties(K=3e-5, K_22=1e-5)


def test_the_sandbox_keys_of_a_calibration_trial_are_not_properties() -> None:
    arrays = _arrays("transient", {"model_name_override": "trial000001"})
    assert np.all(arrays[K_NAME] == FLOW_K)


def _solver_mesh_inputs(monkeypatch: pytest.MonkeyPatch, model: Model) -> dict:
    """The properties the runtime solver mesh is built with, whatever the geometry."""
    seen: dict[str, np.ndarray] = {}

    def capture(cell_mesh, **kwargs):
        seen["conductivity"] = np.asarray(kwargs["hydraulic_conductivity_m_s"])
        seen["storage"] = np.asarray(kwargs["storage_coefficient"])

    monkeypatch.setattr(BoussinesqMesh, "from_cell_mesh", staticmethod(capture))
    adapter.resolve_runtime_solver_mesh(model)
    return seen


def test_a_project_run_override_reaches_the_solver_mesh(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _solver_mesh_inputs(monkeypatch, _model().with_properties(K=5e-6))
    assert np.all(seen["conductivity"] == 5e-6)
    assert np.all(seen["storage"] == FLOW_SY)


def test_a_run_without_override_keeps_the_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _solver_mesh_inputs(monkeypatch, _model())
    assert np.all(seen["conductivity"] == FLOW_K)


@pytest.mark.parametrize(
    ("name", "regime", "match"),
    [("Sy", "transient", r"Sy .* 4 of 4 active convertible"),
     ("Sy", "steady", None),
     ("K", "steady", r"K is zero, negative or not finite on 4 of 4 active")],
)  # fmt: skip
def test_a_zero_value_is_refused_where_the_run_reads_it(monkeypatch, name, regime, match) -> None:
    """A value of zero, as on a cell no zone of its support covers."""
    uncovered = SimpleNamespace(
        to_mesh_field=lambda mesh, label, depth: SimpleNamespace(cell_values=np.zeros(4))
    )
    model = _model(regime, profiles={**_profiles(), name: uncovered})
    if match is None:
        assert np.all(_solver_mesh_inputs(monkeypatch, model)["storage"] == 0.0)
        return
    with pytest.raises(DataContractViolation, match=match):
        _solver_mesh_inputs(monkeypatch, model)


def test_a_project_run_override_of_k22_is_refused_before_the_solve() -> None:
    with pytest.raises(ValueError, match="sets K22, which this solver does not read"):
        adapter.resolve_runtime_solver_mesh(_model().with_properties(K22=1e-5))


def _bundle() -> SimpleNamespace:
    return SimpleNamespace(bundle_dir="bundle", cells=(object(), object(), object()))


def test_an_override_next_to_a_mesh_bundle_is_refused() -> None:
    model = make_model(properties=Properties(profiles={}, overrides={"K": 5e-6}))
    with pytest.raises(ValueError, match="sets K on the mesh bundle bundle"):
        adapter.resolve_bundle_solver_mesh(model, bundle=_bundle())
