"""MODFLOW 6 receives K22 and the three angles of the K tensor, and XT3D when it is tilted.

The flow parameters ``K22``, ``angle1``, ``angle2`` and ``angle3`` are mapped on
the solver mesh like K. Only those the flow sets reach NPF, so a run without them
writes the same package as before. A non-zero ``angle2`` or ``angle3`` turns XT3D
on with a RuntimeWarning, because MODFLOW 6 reads them only there, unless
``mf6_enable_xt3d`` is written. MODFLOW 6 reads ANGLE2 only with ANGLE3, so a
tilt writes all three angles. K33 and the tensor arrays are left beside the
model with K, Sy and Ss.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.build import (
    FLOW_PROPERTY_SIDECAR_SUFFIX,
    _save_flow_property_sidecar,
)
from hydromodpy.solver.modflow6.builders.solver_options import (
    k_tensor_is_tilted,
    resolve_xt3d_decision,
)
from hydromodpy.solver.modflow6.support.property_mapping import (
    k_tensor_npf_kwargs,
    resolve_flow_property_arrays,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.field.field_param import FieldParam
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

N_CELLS = 4


def _mesh() -> SolverMesh:
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), 30.0),
        botm=np.stack([np.full((2, 2), 20.0), np.zeros((2, 2))]),
    )


def _flow(**values: float) -> SimpleNamespace:
    parameters = {"K": FieldParam(identifier="K", kind="homogeneous", value=1e-4)}
    for param_id, value in values.items():
        parameters[param_id] = FieldParam(identifier=param_id, kind="homogeneous", value=value)
    return SimpleNamespace(parameters=parameters)


def _mapped(**values: float) -> dict[str, np.ndarray]:
    return resolve_flow_property_arrays(
        flow=_flow(**values),
        domain=SimpleNamespace(zones={}),
        solver_mesh=_mesh(),
        required_properties=frozenset({"K"}),
    )


def _model(*, xt3d: bool | None = None, **arrays: np.ndarray) -> SimpleNamespace:
    runtime = SimpleNamespace(mf6_enable_xt3d=xt3d)
    model = SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))
    model.hk = np.full((2, N_CELLS), 1e-4)
    for name in ("k22", "angle1", "angle2", "angle3"):
        setattr(model, name, arrays.get(name))
    return model


def test_k22_and_the_angles_are_mapped_on_every_cell_of_every_layer() -> None:
    mapped = _mapped(K22=2e-5, angle1=30.0, angle2=-15.0, angle3=5.0)
    for name, value in (("k22", 2e-5), ("angle1", 30.0), ("angle2", -15.0), ("angle3", 5.0)):
        assert np.asarray(mapped[name]).shape == (2, 2, 2)
        assert np.all(np.asarray(mapped[name]) == value)


def test_a_flow_without_the_tensor_maps_no_tensor_array() -> None:
    mapped = _mapped()
    assert not {"k22", "angle1", "angle2", "angle3"} & set(mapped)


def test_npf_receives_only_the_tensor_arrays_the_flow_sets() -> None:
    k22 = np.full((2, N_CELLS), 2e-5)
    angle1 = np.full((2, N_CELLS), 30.0)
    kwargs = k_tensor_npf_kwargs(_model(k22=k22, angle1=angle1))
    assert set(kwargs) == {"k22", "angle1"}
    assert kwargs["k22"] is k22
    assert k_tensor_npf_kwargs(_model()) == {}


def test_a_dip_alone_writes_the_three_angles_the_missing_ones_as_zero() -> None:
    dip = np.full((2, N_CELLS), 20.0)
    kwargs = k_tensor_npf_kwargs(_model(angle2=dip))
    assert set(kwargs) == {"angle1", "angle2", "angle3"}
    assert np.all(kwargs["angle1"] == 0.0)
    assert np.all(kwargs["angle3"] == 0.0)
    assert kwargs["angle2"] is dip


@pytest.mark.parametrize("name", ["angle2", "angle3"])
def test_a_tilted_tensor_turns_xt3d_on_even_on_a_regular_grid(name: str) -> None:
    angles = np.zeros((2, N_CELLS))
    angles[1, 2] = 10.0
    model = _model(**{name: angles})
    assert k_tensor_is_tilted(model)
    with pytest.warns(RuntimeWarning, match="tilted"):
        decision = resolve_xt3d_decision(model, _mesh())
    assert decision.enabled
    assert decision.source == "auto_on"


def test_an_azimuth_without_k22_leaves_xt3d_off_on_a_regular_grid() -> None:
    model = _model(angle1=np.full((2, N_CELLS), 30.0))
    assert not k_tensor_is_tilted(model)
    assert resolve_xt3d_decision(model, _mesh()).enabled is False


def test_zero_dip_angles_do_not_tilt_the_tensor() -> None:
    model = _model(angle2=np.zeros((2, N_CELLS)), angle3=np.zeros((2, N_CELLS)))
    assert not k_tensor_is_tilted(model)


def test_a_written_xt3d_off_is_kept_with_a_warning_on_a_tilted_tensor() -> None:
    model = _model(xt3d=False, angle2=np.full((2, N_CELLS), 20.0))
    with pytest.warns(RuntimeWarning, match="tilted"):
        decision = resolve_xt3d_decision(model, _mesh())
    assert decision.enabled is False
    assert decision.source == "explicit_off"


def test_k33_and_the_tensor_are_stored_with_the_other_properties(tmp_path: Path) -> None:
    layered = np.full((2, N_CELLS), 1.0)
    model = _model(k22=2e-5 * layered, angle2=20.0 * layered)
    model.full_path = str(tmp_path)
    model.model_output_name = "m"
    model.hk = 1e-4 * layered
    model.k33 = 1e-5 * layered
    model.sy = 0.1 * layered
    model.ss = 1e-5 * layered
    _save_flow_property_sidecar(model)
    with np.load(tmp_path / f"m{FLOW_PROPERTY_SIDECAR_SUFFIX}") as stored:
        assert set(stored.files) == {
            "hydraulic_conductivity",
            "hydraulic_conductivity_k33",
            "hydraulic_conductivity_k22",
            "conductivity_tensor_angle1",
            "conductivity_tensor_angle2",
            "conductivity_tensor_angle3",
            "specific_yield",
            "specific_storage",
        }
        assert np.array_equal(stored["hydraulic_conductivity_k33"], model.k33)
        assert np.array_equal(stored["conductivity_tensor_angle2"], model.angle2)
