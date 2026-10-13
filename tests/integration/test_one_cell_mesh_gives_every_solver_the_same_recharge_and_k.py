"""One cell mesh gives every solver the same recharge and the same K.

Nothing is solved. Each solver is prepared by its own adapter code up to the
arrays it hands to its solver (``tests/integration/_one_cell_mesh_inputs.py``),
on the same mesh, the same recharge sources and the same vector geology:

- pair R, a regular mesh read by MODFLOW 6 and MODFLOW-NWT: recharge of every
  period, K and Sy of every layer, with an exponential K profile;
- pair T, the frozen island triangulation read by MODFLOW 6 and Boussinesq:
  recharge of every period, K and Sy.

Between two solvers the arrays are equal to the byte (``np.array_equal``): one
path produces them. The hand references (nearest pixel or station, inverse
distance, exact zone areas, the profile) are computed from the raw polygons and
raw sources, so two solvers cannot be wrong together. The path itself is proved
by spies on the shared discretizers and an AST guard on ``hydromodpy/solver/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

import hydromodpy
import hydromodpy.solver.boussinesq.forcing.recharge_resolution as boussinesq_recharge
import hydromodpy.solver.field_property_mapping as property_mapping
import hydromodpy.solver.modflow6.builders.recharge as mf6_recharge
import hydromodpy.solver.modflow_nwt.nwt.payloads.recharge_etp as nwt_recharge
from tests._helpers.tolerances import tol
from tests.integration import _one_cell_mesh_inputs as inputs

pytestmark = [pytest.mark.integration, pytest.mark.fast]

_RECHARGE_REL = tol("one_cell_mesh_acceptance__recharge_against_the_hand_reference_relative")
_ZONE_REL = tol("one_cell_mesh_acceptance__zone_means_against_the_exact_areas_relative")
_CASES = ("raster-nearest", "stations-nearest", "stations-idw")
_SOLVER_ROOT = inputs.REPO_ROOT / "hydromodpy" / "solver"


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_runtime() -> None:
    """The flow parameters need the runtime providers; the call is idempotent."""
    hydromodpy.bootstrap()


@pytest.fixture(scope="module")
def regular(tmp_path_factory: pytest.TempPathFactory) -> inputs.MeshPair:
    return inputs.regular_pair(tmp_path_factory.mktemp("regular"))


@pytest.fixture(scope="module")
def triangle(tmp_path_factory: pytest.TempPathFactory) -> inputs.MeshPair:
    return inputs.triangle_pair(tmp_path_factory.mktemp("triangle"))


@pytest.fixture(scope="module")
def regular_cases(regular: inputs.MeshPair) -> dict[str, inputs.RechargeCase]:
    return inputs.recharge_cases(regular)


@pytest.fixture(scope="module")
def triangle_cases(triangle: inputs.MeshPair) -> dict[str, inputs.RechargeCase]:
    return inputs.recharge_cases(triangle)


def _equal_periods(left: dict[int, np.ndarray], right: dict[int, np.ndarray]) -> None:
    assert left.keys() == right.keys() == set(range(inputs.NPER))
    for kper in range(inputs.NPER):
        assert np.array_equal(left[kper], right[kper]), f"period {kper} differs"


# ---------------------------------------------------------------------------
# The meshes are what the test claims
# ---------------------------------------------------------------------------


def test_the_meshes_hold_cells_cut_by_the_contacts(
    regular: inputs.MeshPair, triangle: inputs.MeshPair
) -> None:
    for pair in (regular, triangle):
        fractions = np.column_stack(list(inputs.reference_zone_fractions(pair).values()))
        np.testing.assert_allclose(fractions.sum(axis=1), 1.0, rtol=0.0, atol=1e-9)
        held = (fractions > 1e-3).sum(axis=1)
        assert (held == 2).sum() >= 20, f"{pair.name}: too few cells cut by one contact"
        assert (held == 3).sum() >= 1, f"{pair.name}: no cell holds the three zones"


def test_the_regular_mesh_has_an_unaligned_origin_and_three_layers(
    regular: inputs.MeshPair,
) -> None:
    x_min, y_min, _, _ = regular.bounds
    assert x_min != round(x_min) and y_min != round(y_min)
    assert regular.cell_mesh.structured_shape == (30, 40)
    assert regular.solver_mesh.nlay == 3


# ---------------------------------------------------------------------------
# Pair R: MODFLOW 6 and MODFLOW-NWT, every layer and every period
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def regular_k(regular: inputs.MeshPair, tmp_path_factory: pytest.TempPathFactory):
    """MODFLOW 6 and NWT inputs of the regular pair with a K profile, no recharge source."""
    case = inputs.recharge_cases(regular)["raster-nearest"]
    flow = inputs.make_flow(case, profile=True)
    return (
        inputs.prepare_mf6(regular, flow, tmp_path_factory.mktemp("mf6_k")),
        inputs.prepare_nwt(regular, flow, tmp_path_factory.mktemp("nwt_k")),
    )


def test_modflow6_and_nwt_read_the_same_k_and_sy_on_every_layer(regular_k) -> None:
    mf6, nwt = regular_k
    assert mf6.k.shape == nwt.k.shape == (3, 1200)
    assert np.array_equal(mf6.k, nwt.k)
    assert np.array_equal(mf6.sy, nwt.sy)
    assert not np.array_equal(mf6.k[0], mf6.k[2]), "the K profile must vary with depth"


def test_k_and_sy_equal_the_exact_zone_means_and_the_profile(
    regular: inputs.MeshPair, regular_k
) -> None:
    mf6, _ = regular_k
    np.testing.assert_allclose(
        mf6.k, inputs.reference_k(regular, profile=True), rtol=_ZONE_REL, atol=0.0
    )
    sy = inputs.reference_zone_values(regular, inputs.SY_BY_ZONE)
    np.testing.assert_allclose(mf6.sy, np.tile(sy, (3, 1)), rtol=_ZONE_REL, atol=0.0)


@pytest.mark.parametrize("name", _CASES)
def test_modflow6_and_nwt_read_the_same_recharge_in_every_period(
    regular: inputs.MeshPair,
    regular_cases: dict[str, inputs.RechargeCase],
    name: str,
    tmp_path: Path,
) -> None:
    case = regular_cases[name]
    flow = inputs.make_flow(case, profile=True)
    mf6 = inputs.prepare_mf6(regular, flow, tmp_path / "mf6")
    nwt = inputs.prepare_nwt(regular, flow, tmp_path / "nwt")
    _equal_periods(mf6.recharge, nwt.recharge)
    assert not np.array_equal(mf6.recharge[0], mf6.recharge[1]), "periods must differ"


@pytest.mark.parametrize("name", _CASES)
def test_the_regular_recharge_equals_the_hand_reference(
    regular: inputs.MeshPair,
    regular_cases: dict[str, inputs.RechargeCase],
    name: str,
    tmp_path: Path,
) -> None:
    case = regular_cases[name]
    mf6 = inputs.prepare_mf6(regular, inputs.make_flow(case, profile=False), tmp_path)
    expected = inputs.reference_recharge(regular, case)
    for kper in range(inputs.NPER):
        np.testing.assert_allclose(mf6.recharge[kper], expected[kper], rtol=_RECHARGE_REL, atol=0.0)


# ---------------------------------------------------------------------------
# Pair T: MODFLOW 6 and Boussinesq
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def triangle_k(triangle: inputs.MeshPair, tmp_path_factory: pytest.TempPathFactory):
    case = inputs.recharge_cases(triangle)["raster-nearest"]
    flow = inputs.make_flow(case, profile=False)
    return (
        inputs.prepare_mf6(triangle, flow, tmp_path_factory.mktemp("mf6_t")),
        inputs.prepare_boussinesq(triangle, flow),
    )


def test_modflow6_and_boussinesq_read_the_same_k_and_sy(triangle_k) -> None:
    mf6, boussinesq = triangle_k
    assert mf6.k.shape == (2, 1200) and boussinesq.k.shape == (1, 1200)
    assert np.array_equal(mf6.k[0], boussinesq.k[0])
    assert np.array_equal(mf6.sy[0], boussinesq.sy[0])
    assert np.array_equal(mf6.k[0], mf6.k[1]), "a profile-free K is the same in every layer"


def test_the_triangle_k_and_sy_equal_the_exact_zone_means(
    triangle: inputs.MeshPair, triangle_k
) -> None:
    mf6, _ = triangle_k
    np.testing.assert_allclose(
        mf6.k, inputs.reference_k(triangle, profile=False), rtol=_ZONE_REL, atol=0.0
    )
    sy = inputs.reference_zone_values(triangle, inputs.SY_BY_ZONE)
    np.testing.assert_allclose(mf6.sy[0], sy, rtol=_ZONE_REL, atol=0.0)


@pytest.mark.parametrize("name", _CASES)
def test_modflow6_and_boussinesq_read_the_same_recharge_in_every_period(
    triangle: inputs.MeshPair,
    triangle_cases: dict[str, inputs.RechargeCase],
    name: str,
    tmp_path: Path,
) -> None:
    case = triangle_cases[name]
    flow = inputs.make_flow(case, profile=False)
    mf6 = inputs.prepare_mf6(triangle, flow, tmp_path)
    boussinesq = inputs.prepare_boussinesq(triangle, flow)
    _equal_periods(mf6.recharge, boussinesq.recharge)
    assert not np.array_equal(mf6.recharge[0], mf6.recharge[1]), "periods must differ"


@pytest.mark.parametrize("name", _CASES)
def test_the_triangle_recharge_equals_the_hand_reference(
    triangle: inputs.MeshPair,
    triangle_cases: dict[str, inputs.RechargeCase],
    name: str,
    tmp_path: Path,
) -> None:
    case = triangle_cases[name]
    mf6 = inputs.prepare_mf6(triangle, inputs.make_flow(case, profile=False), tmp_path)
    expected = inputs.reference_recharge(triangle, case)
    for kper in range(inputs.NPER):
        np.testing.assert_allclose(mf6.recharge[kper], expected[kper], rtol=_RECHARGE_REL, atol=0.0)


# ---------------------------------------------------------------------------
# One path: spies on the shared discretizers
# ---------------------------------------------------------------------------


def _spy(monkeypatch: pytest.MonkeyPatch, module: object, name: str) -> list[dict[str, object]]:
    """Wrap ``module.name`` to record its arguments and result, and still call it."""
    original = getattr(module, name)
    calls: list[dict[str, object]] = []

    def wrapper(*args: object, **kwargs: object):
        record = {"args": args, **kwargs}
        calls.append(record)
        record["result"] = original(*args, **kwargs)
        return record["result"]

    monkeypatch.setattr(module, name, wrapper)
    return calls


@pytest.mark.parametrize(
    ("name", "function"),
    [
        ("raster-nearest", "discretize_fields_on_cells"),
        ("stations-idw", "discretize_points_on_cells"),
    ],
)
def test_every_solver_discretizes_on_the_centres_of_the_cell_mesh(
    monkeypatch: pytest.MonkeyPatch,
    regular: inputs.MeshPair,
    triangle: inputs.MeshPair,
    regular_cases: dict[str, inputs.RechargeCase],
    triangle_cases: dict[str, inputs.RechargeCase],
    name: str,
    function: str,
    tmp_path: Path,
) -> None:
    spied = {
        "mf6": _spy(monkeypatch, mf6_recharge, function),
        "nwt": _spy(monkeypatch, nwt_recharge, function),
        "boussinesq": _spy(monkeypatch, boussinesq_recharge, function),
    }
    flow_r = inputs.make_flow(regular_cases[name], profile=True)
    flow_t = inputs.make_flow(triangle_cases[name], profile=False)
    inputs.prepare_mf6(regular, flow_r, tmp_path / "mf6_r")
    inputs.prepare_nwt(regular, flow_r, tmp_path / "nwt_r")
    inputs.prepare_mf6(triangle, flow_t, tmp_path / "mf6_t")
    inputs.prepare_boussinesq(triangle, flow_t)

    expected = {
        "mf6": [regular.cell_mesh, triangle.cell_mesh],
        "nwt": [regular.cell_mesh],
        "boussinesq": [triangle.cell_mesh],
    }
    for solver, cell_meshes in expected.items():
        assert len(spied[solver]) == len(cell_meshes), f"{solver} did not call {function}"
        for call, cell_mesh in zip(spied[solver], cell_meshes, strict=True):
            assert np.array_equal(call["centers"], cell_mesh.centers), solver


def test_every_solver_maps_its_properties_through_the_one_zone_fraction_function(
    monkeypatch: pytest.MonkeyPatch,
    regular: inputs.MeshPair,
    triangle: inputs.MeshPair,
    regular_cases: dict[str, inputs.RechargeCase],
    triangle_cases: dict[str, inputs.RechargeCase],
    tmp_path: Path,
) -> None:
    calls = _spy(monkeypatch, property_mapping, "zone_fractions")
    flow_r = inputs.make_flow(regular_cases["raster-nearest"], profile=True)
    flow_t = inputs.make_flow(triangle_cases["raster-nearest"], profile=False)
    geology_r = regular.domain.zones["geology"]
    geology_t = triangle.domain.zones["geology"]
    steps = (
        (
            "mf6",
            regular.cell_mesh,
            geology_r,
            lambda: inputs.prepare_mf6(regular, flow_r, tmp_path / "a"),
        ),
        (
            "nwt",
            regular.cell_mesh,
            geology_r,
            lambda: inputs.prepare_nwt(regular, flow_r, tmp_path / "b"),
        ),
        (
            "mf6",
            triangle.cell_mesh,
            geology_t,
            lambda: inputs.prepare_mf6(triangle, flow_t, tmp_path / "c"),
        ),
        (
            "boussinesq",
            triangle.cell_mesh,
            geology_t,
            lambda: inputs.prepare_boussinesq(triangle, flow_t),
        ),
    )
    for solver, cell_mesh, geology, prepare in steps:
        before = len(calls)
        prepare()
        new = calls[before:]
        assert new, f"{solver} did not call zone_fractions"
        for call in new:
            assert call["args"][0] is cell_mesh, solver
            assert call["args"][1] is geology, solver
            assert call["result"].source == "vector", solver
            assert call["result"].n_mixed_cells >= 20, solver


# ---------------------------------------------------------------------------
# One path: nothing under hydromodpy/solver/ reaches a retired reader or attribute
# ---------------------------------------------------------------------------

_RETIRED_MODULES = frozenset(
    {
        "sgrid_field_discretization",
        "planar_forcing_discretization",
        "sgrid_fieldparam_discretization",
    }
)
_RETIRED_NAMES = frozenset({"build_planar_cell_adjacency", "GridIntersect"})
_RETIRED_ATTRIBUTE = "solver_mesh_support"


def _retired_uses(source: str) -> list[str]:
    """Imports of a retired reader and any use of ``solver_mesh_support`` in ``source``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if set(alias.name.split(".")) & _RETIRED_MODULES:
                    found.append(f"import {alias.name}")
                if alias.name.split(".")[-1] in _RETIRED_NAMES:
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if set(module.split(".")) & _RETIRED_MODULES:
                found.append(f"from {module} import ...")
            for alias in node.names:
                if alias.name in _RETIRED_NAMES | _RETIRED_MODULES:
                    found.append(f"from {module} import {alias.name}")
        elif isinstance(node, ast.Name) and node.id in _RETIRED_NAMES:
            found.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr in _RETIRED_NAMES:
                found.append(f"attribute {node.attr}")
            if node.attr == _RETIRED_ATTRIBUTE:
                found.append(f"use of {_RETIRED_ATTRIBUTE}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "hasattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == _RETIRED_ATTRIBUTE
        ):
            found.append(f"{node.func.id} of {_RETIRED_ATTRIBUTE}")
    return found


def test_no_solver_module_reaches_a_retired_reader() -> None:
    offences = {}
    for path in sorted(_SOLVER_ROOT.rglob("*.py")):
        uses = _retired_uses(path.read_text(encoding="utf-8"))
        if uses:
            offences[str(path.relative_to(inputs.REPO_ROOT))] = uses
    assert offences == {}


@pytest.mark.parametrize(
    "probe",
    [
        "from hydromodpy.spatial.mesh.cartesian_grid.sgrid_field_discretization import f",
        "import hydromodpy.spatial.mesh.gmsh_grid.planar_forcing_discretization",
        "from hydromodpy.spatial.mesh.cartesian_grid import sgrid_fieldparam_discretization",
        "from flopy.utils.gridintersect import GridIntersect",
        "from hydromodpy.spatial.mesh.model.cell_adjacency import build_planar_cell_adjacency",
        "x = GridIntersect(grid)",
        "x = model.solver_mesh_support",
        "model.solver_mesh_support = None",
        "x = getattr(model, 'solver_mesh_support', None)",
    ],
)
def test_the_guard_fails_on_a_probe_file(probe: str, tmp_path: Path) -> None:
    """A file that does what the guard forbids is reported (the negative control)."""
    path = tmp_path / "probe.py"
    path.write_text(probe + "\n", encoding="utf-8")
    assert _retired_uses(path.read_text(encoding="utf-8")) != []
