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


def test_per_cell_override() -> None:
    per_cell = np.array([1e-5, 2e-5, 3e-5, 4e-5])
    arrays = _arrays("transient", {"K": per_cell})
    np.testing.assert_allclose(arrays[K_NAME], per_cell)


@pytest.mark.parametrize("key", ["Kv", "Ss", "K22", "angle1", "angle2", "angle3"])
def test_unread_property_is_refused(key: str) -> None:
    canonical = {"Kv": "Kv", "Ss": "Ss"}.get(key, key)
    with pytest.raises(ValueError, match=f"sets {canonical}, which this solver does not read"):
        _arrays("transient", {"K": 3e-5, key: 1e-5})


def test_sy_refused_on_steady_run() -> None:
    with pytest.raises(ValueError, match="sets Sy, which this solver does not read: it reads K"):
        _arrays("steady", {"Sy": 0.2})


def test_unknown_name_is_refused() -> None:
    with pytest.raises(ValueError, match="K_22 name no flow property"):
        make_model().with_properties(K=3e-5, K_22=1e-5)


def _solver_mesh_inputs(monkeypatch: pytest.MonkeyPatch, model: Model) -> dict:
    """The properties the runtime solver mesh is built with, whatever the geometry."""
    seen: dict[str, np.ndarray] = {}

    def capture(cell_mesh, **kwargs):
        seen["conductivity"] = np.asarray(kwargs["hydraulic_conductivity_m_s"])
        seen["storage"] = np.asarray(kwargs["storage_coefficient"])

    monkeypatch.setattr(BoussinesqMesh, "from_cell_mesh", staticmethod(capture))
    adapter.resolve_runtime_solver_mesh(model)
    return seen


@pytest.mark.parametrize(
    ("name", "regime", "match"),
    [("Sy", "transient", r"Sy .* 4 of 4 active convertible"),
     ("Sy", "steady", None),
     ("K", "steady", r"K is zero, negative or not finite on 4 of 4 active")],
)  # fmt: skip
def test_zero_value_is_refused(monkeypatch, name, regime, match) -> None:
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


def test_k22_override_is_refused() -> None:
    with pytest.raises(ValueError, match="sets K22, which this solver does not read"):
        adapter.resolve_runtime_solver_mesh(_model().with_properties(K22=1e-5))


def _bundle() -> SimpleNamespace:
    return SimpleNamespace(bundle_dir="bundle", cells=(object(), object(), object()))


def test_override_on_a_bundle_is_refused() -> None:
    model = make_model(properties=Properties(profiles={}, overrides={"K": 5e-6}))
    with pytest.raises(ValueError, match="sets K on the mesh bundle bundle"):
        adapter.resolve_bundle_solver_mesh(model, bundle=_bundle())


def test_missing_profile_leaves_the_mesh_to_the_bundle() -> None:
    # A transient run reads K and Sy: a model with no profile builds no direct mesh.
    assert adapter.resolve_runtime_solver_mesh(_model(profiles={})) is None


def _bundle_with(
    *, cell_k: float | None, cell_sy: float | None, default_k: float | None = None
) -> SimpleNamespace:
    """A bundle of one cell whose hydraulic view carries the given K and Sy defaults."""
    cell = SimpleNamespace(
        cell_id=7, hydraulic_conductivity_m_s=cell_k, storage_coefficient=cell_sy
    )
    view = SimpleNamespace(
        conductivity=SimpleNamespace(default_value=default_k),
        storage_coefficient=SimpleNamespace(default_value=None),
    )
    return SimpleNamespace(
        bundle_dir="bundle",
        cells=(cell,),
        metadata_view=SimpleNamespace(hydraulic_properties=view),
    )


BUNDLE_REFUSALS = [
    pytest.param(
        _bundle_with(cell_k=None, cell_sy=0.1),
        "transient",
        "hydraulic_conductivity_m_s for every cell.*cell_id=7",
        id="no K on the cell and no default",
    ),
    pytest.param(
        _bundle_with(cell_k=1e-4, cell_sy=None),
        "transient",
        "storage_coefficient for every cell.*cell_id=7",
        id="no Sy on a transient run",
    ),
]


@pytest.mark.parametrize(("bundle", "regime", "message"), BUNDLE_REFUSALS)
def test_bundle_missing_value_is_refused(bundle, regime: str, message: str) -> None:
    model = make_model(
        properties=Properties(profiles={}, overrides={}),
        time=ModelTime(grid=None, regime=regime, first_period_steady=True),
    )

    with pytest.raises(ValueError, match=message):
        adapter.resolve_bundle_solver_mesh(model, bundle=bundle)
