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
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow6.builders.solver_options import (
    k_tensor_is_tilted,
    resolve_xt3d_decision,
)
from hydromodpy.solver.modflow6.support.property_mapping import (
    K_TENSOR_NPF_NAMES,
    k_tensor_npf_kwargs,
    resolve_flow_property_arrays,
    resolve_k33_field,
)
from hydromodpy.solver.modflow6.support.property_mapping import (
    resolve_flow_property_arrays as resolve_modflow6_arrays,
)
from hydromodpy.solver.modflow_common.property_mapping import (
    resolve_flow_property_arrays as resolve_modflow_arrays,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.mf6_toy_models import regular_solver_mesh
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

# A trial's characteristic_depth reaches the built MODFLOW 6 NPF k array.
#
# ``resolve_flow_property_arrays`` (``hydromodpy/solver/modflow6/support/
# property_mapping.py``) is what ``build.py`` calls to produce ``model.hk``,
# which is then passed verbatim as ``k=model.hk`` to ``flopy.mf6.ModflowGwfnpf``
# (``solver_mesh.flatten_from_grid`` only reshapes it, it never changes a
# value). Proving the ratio on this function's output is proving it on the NPF
# package's own k array.
#
# Evaluation depth: the layer-center depth below the model top, exactly what
# ``SolverMesh.layer_center_depths()`` defines: ``top - 0.5 * (layer_top +
# layer_bottom)``. On a 30 m column in two layers (layer 1 = the top 10 m,
# layer 2 = the next 20 m), the layer centers sit 5 m and 20 m below the top,
# so the exponential profile predicts ``k2 / k1 = exp(-(20 - 5) / characteristic_depth)``.

_TOP_ELEVATION = 30.0


_DEPTH_LAYER_1 = 5.0


_DEPTH_LAYER_2 = 20.0


def _column_solver_mesh() -> SolverMesh:
    """A 30 m column of 2 x 2 cells in two layers, 10 m and 20 m thick."""
    botm = np.stack(
        [
            np.full((2, 2), _TOP_ELEVATION - _TOP_ELEVATION / 3.0),
            np.zeros((2, 2)),
        ]
    )
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), _TOP_ELEVATION),
        botm=botm,
    )


def _hk(characteristic_depth: float) -> np.ndarray:
    solver_mesh = _column_solver_mesh()
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
    )
    hk = out["hk"]
    assert hk.shape[0] == 2
    return hk


@pytest.mark.parametrize("characteristic_depth", [10.0, 50.0])
def test_characteristic_depth_sets_the_npf_k_layer_ratio(characteristic_depth: float) -> None:
    hk = _hk(characteristic_depth)
    k1, k2 = float(hk[0].flat[0]), float(hk[1].flat[0])

    expected_ratio = np.exp(-(_DEPTH_LAYER_2 - _DEPTH_LAYER_1) / characteristic_depth)
    assert k2 / k1 == pytest.approx(expected_ratio, rel=1e-6)


def test_two_trial_values_give_two_different_npf_k_arrays() -> None:
    hk_short = _hk(10.0)
    hk_long = _hk(80.0)

    ratio_short = hk_short[1].flat[0] / hk_short[0].flat[0]
    ratio_long = hk_long[1].flat[0] / hk_long[0].flat[0]

    assert ratio_short != pytest.approx(ratio_long)


# A runtime property override carries K22, Kv and the angles, as it carries K.
#
# ``Project.run(properties=...)`` hands the build arrays that win over the flow
# parameters (``resolve_flow_property_runtime_overrides``). They knew K, Sy and
# Ss only, so an override of K22, Kv or an angle was dropped in silence and the
# run used the flow parameter instead. The override now covers every property of
# the shared mapping, reaches the MODFLOW 6 arrays the XT3D rule reads, and a
# name it does not know, or a property the solver does not read, is refused.

N_CELLS = 4


TRANSIENT = frozenset({"K", "Sy", "Ss"})


def _mesh() -> SolverMesh:
    return solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=2,
        top=np.full((2, 2), 30.0),
        botm=np.stack([np.full((2, 2), 20.0), np.zeros((2, 2))]),
    )


def _profiles() -> dict[str, FieldParam]:
    """K and an azimuth of 30 degrees, K22 left equal to K: XT3D stays off."""
    return {
        "K": FieldParam(identifier="K", kind="homogeneous", value=1e-4),
        "angle1": FieldParam(identifier="angle1", kind="homogeneous", value=30.0),
    }


def _modflow6(properties: dict[str, object]) -> dict[str, np.ndarray]:
    mesh = _mesh()
    mapped = resolve_modflow6_arrays(
        profiles=_profiles(),
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


def test_an_override_names_a_property_by_its_one_id() -> None:
    with pytest.raises(ValueError, match="K33 name no flow property"):
        resolve_flow_property_runtime_overrides(
            {"properties": {"K33": 1e-6}}, nlay=2, n_cells=N_CELLS, required_properties={"K"}
        )


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
            profiles=_profiles(),
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


# MODFLOW 6 receives K22 and the three angles of the K tensor, and XT3D when it is tilted.
#
# The flow parameters ``K22``, ``angle1``, ``angle2`` and ``angle3`` are mapped on
# the solver mesh like K. Only those the flow sets reach NPF, so a run without them
# writes the same package as before. A non-zero ``angle2`` or ``angle3`` turns XT3D
# on with a RuntimeWarning, because MODFLOW 6 reads them only there, unless
# ``mf6_enable_xt3d`` is written. MODFLOW 6 reads ANGLE2 only with ANGLE3, so a
# tilt writes all three angles. K33 and the tensor arrays are left beside the
# model with K, Sy and Ss.


def _profiles_2(**values: float) -> dict[str, FieldParam]:
    parameters = {"K": FieldParam(identifier="K", kind="homogeneous", value=1e-4)}
    for param_id, value in values.items():
        parameters[param_id] = FieldParam(identifier=param_id, kind="homogeneous", value=value)
    return parameters


def _mapped(**values: float) -> dict[str, np.ndarray]:
    return resolve_flow_property_arrays(
        profiles=_profiles_2(**values),
        domain=SimpleNamespace(zones={}),
        solver_mesh=_mesh(),
        required_properties=frozenset({"K"}),
    )


def _model_2(*, xt3d: bool | None = None, **arrays: np.ndarray) -> SimpleNamespace:
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
    kwargs = k_tensor_npf_kwargs(_model_2(k22=k22, angle1=angle1))
    assert set(kwargs) == {"k22", "angle1"}
    assert kwargs["k22"] is k22
    assert k_tensor_npf_kwargs(_model_2()) == {}


def test_a_dip_alone_writes_the_three_angles_the_missing_ones_as_zero() -> None:
    dip = np.full((2, N_CELLS), 20.0)
    kwargs = k_tensor_npf_kwargs(_model_2(angle2=dip))
    assert set(kwargs) == {"angle1", "angle2", "angle3"}
    assert np.all(kwargs["angle1"] == 0.0)
    assert np.all(kwargs["angle3"] == 0.0)
    assert kwargs["angle2"] is dip


@pytest.mark.parametrize("name", ["angle2", "angle3"])
def test_a_tilted_tensor_turns_xt3d_on_even_on_a_regular_grid(name: str) -> None:
    angles = np.zeros((2, N_CELLS))
    angles[1, 2] = 10.0
    model = _model_2(**{name: angles})
    assert k_tensor_is_tilted(model)
    with pytest.warns(RuntimeWarning, match="tilted"):
        decision = resolve_xt3d_decision(model, _mesh())
    assert decision.enabled
    assert decision.source == "auto_on"


def test_an_azimuth_without_k22_leaves_xt3d_off_on_a_regular_grid() -> None:
    model = _model_2(angle1=np.full((2, N_CELLS), 30.0))
    assert not k_tensor_is_tilted(model)
    assert resolve_xt3d_decision(model, _mesh()).enabled is False


def test_zero_dip_angles_do_not_tilt_the_tensor() -> None:
    model = _model_2(angle2=np.zeros((2, N_CELLS)), angle3=np.zeros((2, N_CELLS)))
    assert not k_tensor_is_tilted(model)


def test_a_written_xt3d_off_is_kept_with_a_warning_on_a_tilted_tensor() -> None:
    model = _model_2(xt3d=False, angle2=np.full((2, N_CELLS), 20.0))
    with pytest.warns(RuntimeWarning, match="tilted"):
        decision = resolve_xt3d_decision(model, _mesh())
    assert decision.enabled is False
    assert decision.source == "explicit_off"


def test_k33_and_the_tensor_are_stored_with_the_other_properties(tmp_path: Path) -> None:
    layered = np.full((2, N_CELLS), 1.0)
    model = _model_2(k22=2e-5 * layered, angle2=20.0 * layered)
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


# A zero or missing conductivity is refused, and so is a storage a transient period reads.
#
# Sy counts on a convertible cell, Ss on a confined one, both on active cells only.


def _heterogeneous_k() -> FieldParam:
    return FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 1e-5, "schist": 1e-6},
        field_spatial_id="field_geology",
    )


def _k_with_an_uncovered_cell() -> tuple[FieldParam, np.ndarray]:
    """One cell that no zone of the support covers, as outside a clipped geology map."""
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


def test_an_uncovered_active_cell_is_refused_and_names_the_support():
    param, hk = _k_with_an_uncovered_cell()
    assert np.count_nonzero(hk == 0.0) == 1
    profiles = {"K": param}
    with pytest.raises(DataContractViolation, match=r"1 of 9 active.*'field_geology'"):
        require_positive_conductivity(
            hk, active_mask=np.ones_like(hk, dtype=bool), profiles=profiles
        )


def test_an_uncovered_inactive_cell_is_accepted():
    param, hk = _k_with_an_uncovered_cell()
    active = hk > 0.0
    require_positive_conductivity(hk, active_mask=active, profiles={})


def test_a_non_finite_conductivity_is_refused():
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
def test_a_storage_is_refused_only_where_a_transient_period_reads_it(
    sy, ss, iconvert, steady, match
):
    sy, ss = np.asarray(sy, dtype=float), None if ss is None else np.asarray(ss, dtype=float)
    with pytest.raises(DataContractViolation, match=match) if match else nullcontext():
        require_positive_storage(
            sy, ss, active_mask=np.ones(sy.shape, bool), iconvert=iconvert, steady=steady
        )


@pytest.mark.parametrize(("dry_cell", "match"), [(0, None), (1, r"Sy .* 1 of 11 active")])
def test_modflow6_reads_the_storage_on_the_grid_the_lake_leaves(monkeypatch, dry_cell, match):
    """Sy = 0 under the lake footprint is never read; on an active cell it is refused."""
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
        mf6_build._build_storage_package(model, mesh)


# Vertical anisotropy resolution for the MF6 k33 field.
#
# A direct per-cell Kv field or the uniform kh/vka ratio, mutually exclusive, with
# guardrails against the ratio-versus-value footgun and Kv > Kh.


def test_uniform_ratio_divides_kh() -> None:
    hk = np.array([1e-4, 1e-5, 1e-6])
    np.testing.assert_allclose(resolve_k33_field(hk, None, 10.0), hk / 10.0)


def test_ratio_one_is_vertically_isotropic() -> None:
    hk = np.array([1e-4, 2e-5])
    np.testing.assert_allclose(resolve_k33_field(hk, None, 1.0), hk)


def test_direct_kv_field_takes_precedence() -> None:
    hk = np.full(3, 1e-4)
    kv = np.array([1e-5, 2e-5, 3e-5])
    np.testing.assert_allclose(resolve_k33_field(hk, kv, 1.0), kv)


def test_kv_field_and_nonunit_vka_is_a_conflict() -> None:
    with pytest.raises(ConfigError, match="one or the other"):
        resolve_k33_field(np.full(1, 1e-4), np.full(1, 1e-5), 5.0)


def test_kv_shape_mismatch_raises() -> None:
    with pytest.raises(ConfigError, match="does not match"):
        resolve_k33_field(np.zeros(3), np.zeros(2), 1.0)


def test_nonpositive_vka_raises() -> None:
    with pytest.raises(ConfigError, match="must be > 0"):
        resolve_k33_field(np.full(2, 1e-4), None, 0.0)


def test_kv_above_kh_warns(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(pm.logger, "warning", lambda *a, **k: calls.append(a))
    hk = np.full(2, 1e-4)
    kv = np.array([1e-5, 2e-4])  # second cell has Kv > Kh
    resolve_k33_field(hk, kv, 1.0)
    assert any("exceeds Kh" in str(c[0]) for c in calls)


def test_vka_below_one_warns_once(monkeypatch) -> None:
    pm._VKA_WARNED.clear()
    calls: list[tuple] = []
    monkeypatch.setattr(pm.logger, "warning", lambda *a, **k: calls.append(a))
    resolve_k33_field(np.full(1, 1e-4), None, 0.5)
    resolve_k33_field(np.full(1, 1e-4), None, 0.5)  # deduped
    assert sum("< 1" in str(c[0]) for c in calls) == 1
