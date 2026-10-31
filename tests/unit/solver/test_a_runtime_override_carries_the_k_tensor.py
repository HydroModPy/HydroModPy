"""A runtime property override carries K22, Kv and the angles, as it carries K.

``Project.run(properties=...)`` hands the build arrays that win over the flow
parameters (``resolve_flow_property_runtime_overrides``). They knew K, Sy and
Ss only, so an override of K22, Kv or an angle was dropped in silence and the
run used the flow parameter instead. The override now covers every property of
the shared mapping, reaches the MODFLOW 6 arrays the XT3D rule reads, and a
name it does not know, or a property the solver does not read, is refused.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.units.physical_bounds import PhysicalBoundsError
from hydromodpy.solver.modflow6.builders.solver_options import resolve_xt3d_decision
from hydromodpy.solver.modflow6.support.property_mapping import (
    K_TENSOR_NPF_NAMES,
)
from hydromodpy.solver.modflow6.support.property_mapping import (
    resolve_flow_property_arrays as resolve_modflow6_arrays,
)
from hydromodpy.solver.modflow_common.property_mapping import (
    resolve_flow_property_arrays as resolve_modflow_arrays,
)
from hydromodpy.solver.modflow_common.runtime_arrays import (
    resolve_flow_property_runtime_overrides,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.field.field_param import FieldParam
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N_CELLS = 4
TRANSIENT = frozenset({"K", "Sy", "Ss"})


def _mesh() -> SolverMesh:
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), 30.0),
        botm=np.stack([np.full((2, 2), 20.0), np.zeros((2, 2))]),
    )


def _flow() -> SimpleNamespace:
    """K and an azimuth of 30 degrees, K22 left equal to K: XT3D stays off."""
    return SimpleNamespace(
        parameters={
            "K": FieldParam(identifier="K", kind="homogeneous", value=1e-4),
            "angle1": FieldParam(identifier="angle1", kind="homogeneous", value=30.0),
        }
    )


def _modflow6(properties: dict[str, object]) -> dict[str, np.ndarray]:
    mesh = _mesh()
    mapped = resolve_modflow6_arrays(
        flow=_flow(),
        domain=SimpleNamespace(zones={}),
        solver_mesh=mesh,
        required_properties=frozenset({"K"}),
        runtime_property_overrides={"source": "project_run", "properties": properties},
    )
    return {name: mesh.flatten_from_grid(values) for name, values in mapped.items()}


def _model(arrays: dict[str, np.ndarray]) -> SimpleNamespace:
    """The model attributes ``run_pre_processing`` sets before its XT3D decision."""
    runtime = SimpleNamespace(mf6_enable_xt3d=None)
    model = SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))
    model.hk = arrays["hk"]
    for name in K_TENSOR_NPF_NAMES:
        setattr(model, name, arrays.get(name))
    return model


@pytest.mark.parametrize(
    ("key", "name", "value"),
    [
        ("K22", "k22", 2e-5),
        ("Kv", "kv", 1e-6),
        ("K33", "kv", 1e-6),
        ("angle1", "angle1", 60.0),
        ("angle2", "angle2", -15.0),
        ("angle3", "angle3", 5.0),
    ],
)
def test_each_tensor_property_is_carried_to_every_cell(key: str, name: str, value: float) -> None:
    overrides = resolve_flow_property_runtime_overrides(
        {"properties": {key: value}}, nlay=2, n_cells=N_CELLS, required_properties={"K"}
    )
    assert overrides[name].shape == (2, N_CELLS)
    assert np.all(overrides[name] == value)
    assert np.all(overrides[f"{name}_value"] == value)


def test_an_override_wins_over_the_flow_angle() -> None:
    arrays = _modflow6({"angle1": 0.0, "K22": 2e-5})
    assert np.all(arrays["angle1"] == 0.0)
    assert np.all(arrays["k22"] == 2e-5)


def test_the_flow_alone_keeps_xt3d_off() -> None:
    assert resolve_xt3d_decision(_model(_modflow6({})), _mesh()).enabled is False


def test_an_override_that_turns_k22_off_axis_turns_xt3d_on() -> None:
    model = _model(_modflow6({"K22": 1e-5}))
    with pytest.warns(RuntimeWarning, match="K22 differs from K"):
        decision = resolve_xt3d_decision(model, _mesh())
    assert (decision.enabled, decision.source) == (True, "auto_on")


def test_an_override_that_tilts_the_tensor_turns_xt3d_on() -> None:
    model = _model(_modflow6({"angle2": 10.0}))
    with pytest.warns(RuntimeWarning, match="tilted"):
        assert resolve_xt3d_decision(model, _mesh()).enabled


def test_an_unknown_property_name_is_refused() -> None:
    with pytest.raises(ValueError, match="K_22 name no flow property"):
        resolve_flow_property_runtime_overrides(
            {"properties": {"K": 1e-4, "K_22": 1e-5}}, nlay=2, n_cells=N_CELLS
        )


def test_a_solver_without_the_tensor_refuses_a_k22_override() -> None:
    with pytest.raises(ValueError, match="sets K22, which this solver does not read"):
        resolve_modflow_arrays(
            flow=_flow(),
            domain=SimpleNamespace(zones={}),
            solver_mesh=_mesh(),
            required_properties=frozenset({"K"}),
            runtime_property_overrides={"properties": {"K22": 1e-5}},
        )


def test_the_trial_sandbox_keys_are_not_properties() -> None:
    overrides = resolve_flow_property_runtime_overrides(
        {"model_name_override": "trial000001", "trial_owns_its_recharge": True},
        nlay=2,
        n_cells=N_CELLS,
        required_properties={"K", "Sy", "Ss"},
    )
    assert overrides == {}


@pytest.mark.parametrize(
    ("properties", "match"),
    [({"K": 1e3}, r"hydraulic conductivity \(id='K'\) in the runtime override, one value for every cell, value 1000.0 outside"),
     ({"K": 1e-5, "Sy": [0.1, 0.8, 0.1, 0.1]}, r"specific yield \(id='Sy'\) in the runtime override, every layer, by cell: 1 of 4 .* index 1: 0.8"),
     ({"K": 1e-5, "Ss": [1e-5] * 6 + [0.0, 1e-5]}, r"specific storage \(id='Ss'\) in the runtime override, layer 2 of 2, by cell: 1 of 4 .* index 2: 0.0"),
     ({"K": 1e-5, "angle2": 120.0}, r"\(id='angle2'\) in the runtime override")],
    ids=["k-everywhere", "sy-in-one-cell", "ss-in-one-cell-of-layer-2", "angle-past-the-vertical"],
)  # fmt: skip
def test_an_override_outside_the_physical_range_is_refused(properties, match) -> None:
    with pytest.raises(PhysicalBoundsError, match=match):
        resolve_flow_property_runtime_overrides(
            {"properties": properties}, nlay=2, n_cells=N_CELLS, required_properties=TRANSIENT
        )


@pytest.mark.parametrize("properties", [{"Sy": 0.0}, {"Ss": [np.nan] * N_CELLS}], ids=["sy", "ss"])
def test_a_steady_run_does_not_bound_the_storage_it_does_not_read(properties) -> None:
    overrides = resolve_flow_property_runtime_overrides(
        {"properties": properties}, nlay=2, n_cells=N_CELLS, required_properties={"K"}
    )
    assert overrides.keys() == {
        f"{name.lower()}{end}" for name in properties for end in ("", "_value")
    }
