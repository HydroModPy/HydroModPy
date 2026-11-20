"""Conductivity fields and K tensor handed to the MODFLOW 6 NPF and STO packages.

K, K22, Kv are in m/s, angles in degrees, depths in m. A trial or a runtime
override reaches the arrays, a tilted tensor turns XT3D on, and a zero or
missing conductivity or storage is refused.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import hydromodpy.solver.modflow6.support.property_mapping as pm
from hydromodpy.core.exceptions import ConfigError, DataContractViolation
from hydromodpy.core.units.physical_bounds import PhysicalBoundsError
from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.properties.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.model.properties.mesh_cells import cell_values
from hydromodpy.model.properties.property_table import (
    require_positive_conductivity,
    require_positive_storage,
    resolve_flow_property_runtime_overrides,
)
from hydromodpy.model.properties.unit_square_mesh import FieldMeshSquare
from hydromodpy.solver.modflow6 import build as mf6_build
from hydromodpy.solver.modflow6.build import (
    FLOW_PROPERTY_SIDECAR_SUFFIX,
    _save_flow_property_sidecar,
)
from hydromodpy.solver.modflow6.builders import period_forcing
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow6.builders.solver_options import resolve_xt3d_decision
from hydromodpy.solver.modflow6.support.property_mapping import (
    K_TENSOR_NPF_NAMES,
    MODFLOW6_PROPERTIES,
    k_tensor_npf_kwargs,
    resolve_k33_field,
)
from hydromodpy.solver.modflow_common.property_mapping import resolve_flow_property_arrays
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import regular_solver_mesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

TOP_M = 30.0
N_CELLS = 4
TRANSIENT = frozenset({"K", "Sy", "Ss"})


def two_layer_column() -> SolverMesh:
    # A 30 m column of 2 x 2 cells in two layers, 10 m and 20 m thick.
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), TOP_M),
        botm=np.stack([np.full((2, 2), 20.0), np.zeros((2, 2))]),
    )


def exponential_k(characteristic_depth: float) -> np.ndarray:
    solver_mesh = two_layer_column()
    assert solver_mesh.is_structured
    field_param = FieldParam(
        identifier="K",
        kind="homogeneous",
        value=1e-4,
        vertical_profile={"kind": "exponential", "characteristic_depth": characteristic_depth},
    )
    profiles = {"K": field_param}
    domain = SimpleNamespace(zones={})
    out = resolve_flow_property_arrays(
        profiles=profiles,
        domain=domain,
        solver_mesh=solver_mesh,
        required_properties=frozenset({"K"}),
        properties=MODFLOW6_PROPERTIES,
    )
    hk = out["hk"]
    assert hk.shape[0] == 2
    return hk


@pytest.mark.parametrize("characteristic_depth", [10.0, 50.0])
def test_depth_sets_layer_k_ratio(characteristic_depth: float) -> None:
    hk = exponential_k(characteristic_depth)
    k1, k2 = float(hk[0].flat[0]), float(hk[1].flat[0])

    # Layer centers sit 5 m and 20 m below the top, so k2 / k1 = exp(-15 m / depth).
    expected_ratio = np.exp(-15.0 / characteristic_depth)
    assert k2 / k1 == pytest.approx(expected_ratio, rel=1e-6)


def test_two_depths_two_k_arrays() -> None:
    hk_short = exponential_k(10.0)
    hk_long = exponential_k(80.0)

    ratio_short = hk_short[1].flat[0] / hk_short[0].flat[0]
    ratio_long = hk_long[1].flat[0] / hk_long[0].flat[0]

    assert ratio_short != pytest.approx(ratio_long)


def k_and_azimuth() -> dict[str, FieldParam]:
    # K and an azimuth of 30 degrees, K22 left equal to K: XT3D stays off.
    return {
        "K": FieldParam(identifier="K", kind="homogeneous", value=1e-4),
        "angle1": FieldParam(identifier="angle1", kind="homogeneous", value=30.0),
    }


def overridden_arrays(properties: dict[str, object]) -> dict[str, np.ndarray]:
    mesh = two_layer_column()
    mapped = resolve_flow_property_arrays(
        profiles=k_and_azimuth(),
        domain=SimpleNamespace(zones={}),
        solver_mesh=mesh,
        required_properties=frozenset({"K"}),
        runtime_property_overrides={"source": "project_run", "properties": properties},
        properties=MODFLOW6_PROPERTIES,
    )
    return dict(mapped)


def model_of_arrays(arrays: dict[str, np.ndarray]) -> SimpleNamespace:
    # The model attributes run_pre_processing sets before its XT3D decision.
    runtime = SimpleNamespace(mf6_enable_xt3d=None)
    model = SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))
    model.hk = arrays["hk"]
    for name in K_TENSOR_NPF_NAMES:
        setattr(model, name, arrays.get(name))
    return model


XT3D_ON = [
    pytest.param({"K22": 1e-5}, "K22 differs from K", id="k22 off the axis"),
    pytest.param({"angle2": 10.0}, "tilted", id="tilted tensor"),
]


@pytest.mark.parametrize(("properties", "match"), XT3D_ON)
def test_override_turns_xt3d_on(properties, match) -> None:
    model = model_of_arrays(overridden_arrays(properties))
    with pytest.warns(RuntimeWarning, match=match):
        decision = resolve_xt3d_decision(model, two_layer_column())
    assert (decision.enabled, decision.source) == (True, "auto_on")


@pytest.mark.parametrize(
    ("properties", "match"),
    [({"K": 1e3}, r"hydraulic conductivity \(id='K'\) in the runtime override, one value for every cell, value 1000.0 outside"),
     ({"K": 1e-5, "Sy": [0.1, 0.8, 0.1, 0.1]}, r"specific yield \(id='Sy'\) in the runtime override, every layer, by cell: 1 of 4 .* index 1: 0.8"),
     ({"K": 1e-5, "Ss": [1e-5] * 6 + [0.0, 1e-5]}, r"specific storage \(id='Ss'\) in the runtime override, layer 2 of 2, by cell: 1 of 4 .* index 2: 0.0"),
     ({"K": 1e-5, "angle2": 120.0}, r"\(id='angle2'\) in the runtime override")],
    ids=["k-everywhere", "sy-in-one-cell", "ss-in-one-cell-of-layer-2", "angle-past-the-vertical"],
)  # fmt: skip
def test_override_out_of_range(properties, match) -> None:
    with pytest.raises(PhysicalBoundsError, match=match):
        resolve_flow_property_runtime_overrides(
            {"properties": properties}, nlay=2, n_cells=N_CELLS, required_properties=TRANSIENT
        )


UNKNOWN_NAMES = [
    pytest.param({"K33": 1e-6}, {"K"}, "K33 name no flow property", id="k33"),
    pytest.param({"K": 1e-4, "K_22": 1e-5}, None, "K_22 name no flow property", id="k_22"),
]


@pytest.mark.parametrize(("properties", "required", "match"), UNKNOWN_NAMES)
def test_override_unknown_name(properties, required, match) -> None:
    kwargs = {} if required is None else {"required_properties": required}
    with pytest.raises(ValueError, match=match):
        resolve_flow_property_runtime_overrides(
            {"properties": properties}, nlay=2, n_cells=N_CELLS, **kwargs
        )


def tensor_model(*, xt3d: bool | None = None, **arrays: np.ndarray) -> SimpleNamespace:
    runtime = SimpleNamespace(mf6_enable_xt3d=xt3d)
    model = SimpleNamespace(modflow_config=SimpleNamespace(runtime=runtime))
    model.hk = np.full((2, N_CELLS), 1e-4)
    for name in ("k22", "angle1", "angle2", "angle3"):
        setattr(model, name, arrays.get(name))
    return model


def test_dip_writes_three_angles() -> None:
    dip = np.full((2, N_CELLS), 20.0)
    kwargs = k_tensor_npf_kwargs(tensor_model(angle2=dip))
    assert set(kwargs) == {"angle1", "angle2", "angle3"}
    assert np.all(kwargs["angle1"] == 0.0)
    assert np.all(kwargs["angle3"] == 0.0)
    assert kwargs["angle2"] is dip


def test_explicit_xt3d_off_is_kept() -> None:
    model = tensor_model(xt3d=False, angle2=np.full((2, N_CELLS), 20.0))
    with pytest.warns(RuntimeWarning, match="tilted"):
        decision = resolve_xt3d_decision(model, two_layer_column())
    assert decision.enabled is False
    assert decision.source == "explicit_off"


def test_tensor_stored_with_properties(tmp_path: Path) -> None:
    layered = np.full((2, N_CELLS), 1.0)
    model = tensor_model(k22=2e-5 * layered, angle2=20.0 * layered)
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


def _heterogeneous_k() -> FieldParam:
    return FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 1e-5, "schist": 1e-6},
        field_spatial_id="field_geology",
    )


def _k_with_an_uncovered_cell() -> tuple[FieldParam, np.ndarray]:
    # One cell that no zone of the support covers, as outside a clipped geology map.
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")
    n = int(mesh.n_cells)
    granite = np.zeros(n)
    schist = np.zeros(n)
    granite[: n // 2] = 1.0
    schist[n // 2 : n - 1] = 1.0
    discretization = WeightedAverageFieldDiscretization(
        mesh=mesh,
        field_id="field_geology",
        zone_keys=("granite", "schist"),
        fractions_by_zone={
            "granite": np.asarray(cell_values(mesh, granite)),
            "schist": np.asarray(cell_values(mesh, schist)),
        },
    )
    param = _heterogeneous_k()
    values = np.asarray(param.to_mesh_field(discretization).cell_values, dtype=float)
    return param, values.reshape(1, -1)


def test_uncovered_cell_refused():
    param, hk = _k_with_an_uncovered_cell()
    assert np.count_nonzero(hk == 0.0) == 1
    profiles = {"K": param}
    with pytest.raises(DataContractViolation, match=r"1 of 9 active.*'field_geology'"):
        require_positive_conductivity(
            hk, active_mask=np.ones_like(hk, dtype=bool), profiles=profiles
        )


def test_non_finite_k_refused():
    hk = np.array([[1e-5, np.nan, 1e-5]])
    with pytest.raises(DataContractViolation, match=r"1 not finite"):
        require_positive_conductivity(hk, active_mask=np.array([True, True, True]))


@pytest.mark.parametrize(
    ("sy", "ss", "iconvert", "steady", "match"),
    [([[0.1, 0.0, 0.0], [0.1, 0.1, 0.0]], None, 1, [True, False],
      r"Sy .* 3 of 6 active convertible .*\(layer 1: 2, layer 2: 1; 3 zero, 0 not finite\)"),
     ([0.1, np.nan, 0.1], None, 1, [False], r"Sy .* 1 of 3 .*1 not finite"),
     ([[0.1] * 3] * 2, [[1e-5] * 3, [1e-5, 0.0, 1e-5]], [1, 0], [False],
      r"Ss .* 1 of 3 active confined .*\(layer 2: 1; 1 zero"),
     ([[0.1] * 3] * 2, [[0.0] * 3] * 2, 1, [False], None),
     ([[0.0] * 3] * 2, [[0.0] * 3] * 2, 1, [True, True], None)],
    ids=["sy-zero-convertible", "sy-not-finite", "ss-zero-confined", "ss-zero-convertible",
         "every-period-steady"],
)  # fmt: skip
def test_storage_refusals(sy, ss, iconvert, steady, match):
    sy, ss = np.asarray(sy, dtype=float), None if ss is None else np.asarray(ss, dtype=float)
    with pytest.raises(DataContractViolation, match=match) if match else nullcontext():
        require_positive_storage(
            sy, ss, active_mask=np.ones(sy.shape, bool), iconvert=iconvert, steady=steady
        )


@pytest.mark.parametrize(("dry_cell", "match"), [(0, None), (1, r"Sy .* 1 of 11 active")])
def test_storage_under_lake_footprint(monkeypatch, dry_cell, match):
    # Sy = 0 under the lake footprint is never read. On an active cell it is refused.
    mesh = regular_solver_mesh(2, 3)
    mesh = replace(mesh, botm=np.vstack([mesh.botm, mesh.botm - 9.0]), idomain=np.ones((2, 6)))
    mesh = apply_lake_idomain_mask(mesh, lake_cell_ids_by_lake={"lake": [0]})
    sy = np.full((2, 6), 0.1)
    sy[0, dry_cell] = 0.0
    model = SimpleNamespace(
        steady=[False], nper=1, nlay=2, sy=sy, ss=sy / 1e4, inputs=make_model(), gwf=None
    )
    monkeypatch.setattr(mf6_build.flopy.mf6, "ModflowGwfsto", lambda gwf, **kwargs: kwargs)
    with pytest.raises(DataContractViolation, match=match) if match else nullcontext():
        period_forcing.build_storage_package(model, mesh)


K33_FIELDS = [
    pytest.param(
        np.array([1e-4, 1e-5, 1e-6]), None, 10.0, [1e-5, 1e-6, 1e-7], id="ratio divides kh"
    ),
    pytest.param(np.array([1e-4, 2e-5]), None, 1.0, [1e-4, 2e-5], id="ratio one is isotropic"),
    pytest.param(
        np.full(3, 1e-4), np.array([1e-5, 2e-5, 3e-5]), 1.0, [1e-5, 2e-5, 3e-5], id="direct kv"
    ),
]


@pytest.mark.parametrize(("hk", "kv", "vka", "expected"), K33_FIELDS)
def test_k33_field(hk, kv, vka, expected) -> None:
    np.testing.assert_allclose(resolve_k33_field(hk, kv, vka), expected)


K33_REFUSALS = [
    pytest.param(np.full(1, 1e-4), np.full(1, 1e-5), 5.0, "one or the other", id="kv and a ratio"),
    pytest.param(np.zeros(3), np.zeros(2), 1.0, "does not match", id="kv of another size"),
    pytest.param(np.full(2, 1e-4), None, 0.0, "must be > 0", id="ratio not positive"),
]


@pytest.mark.parametrize(("hk", "kv", "vka", "match"), K33_REFUSALS)
def test_k33_refusals(hk, kv, vka, match) -> None:
    with pytest.raises(ConfigError, match=match):
        resolve_k33_field(hk, kv, vka)


def test_kv_above_kh_warns(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(pm.logger, "warning", lambda *a, **k: calls.append(a))
    kv = np.array([1e-5, 2e-4])  # second cell has Kv > Kh
    resolve_k33_field(np.full(2, 1e-4), kv, 1.0)
    assert any("exceeds Kh" in str(c[0]) for c in calls)


def test_vka_below_one_warns_once(monkeypatch) -> None:
    pm._VKA_WARNED.clear()
    calls: list[tuple] = []
    monkeypatch.setattr(pm.logger, "warning", lambda *a, **k: calls.append(a))
    resolve_k33_field(np.full(1, 1e-4), None, 0.5)
    resolve_k33_field(np.full(1, 1e-4), None, 0.5)  # deduped
    assert sum("< 1" in str(c[0]) for c in calls) == 1
