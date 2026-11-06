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
raw sources, so two solvers cannot be wrong together.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import hydromodpy
from tests._helpers.tolerances import tol
from tests.integration import _one_cell_mesh_inputs as inputs

pytestmark = [pytest.mark.integration, pytest.mark.fast]

_RECHARGE_REL = tol("one_cell_mesh_acceptance__recharge_against_the_hand_reference_relative")
_ZONE_REL = tol("one_cell_mesh_acceptance__zone_means_against_the_exact_areas_relative")
_CASES = ("raster-nearest", "stations-nearest", "stations-idw")


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
# Area weighting: the same on every solver, equal to the exact overlay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pair_name", ["regular", "triangle"])
def test_the_area_weighted_recharge_is_the_same_for_both_solvers_and_equals_the_overlay(
    request: pytest.FixtureRequest, pair_name: str, tmp_path: Path
) -> None:
    pair = request.getfixturevalue(pair_name)
    case = inputs.raster_case(pair, method="area")
    flow = inputs.make_flow(case, profile=False)
    mf6 = inputs.prepare_mf6(pair, flow, tmp_path / "mf6")
    if pair_name == "regular":
        other = inputs.prepare_nwt(pair, flow, tmp_path / "nwt")
    else:
        other = inputs.prepare_boussinesq(pair, flow)
    _equal_periods(mf6.recharge, other.recharge)

    expected, reached = inputs.reference_area_recharge(pair, case)
    assert reached.mean() > 0.9, "the raster must reach most cells"
    for kper in range(inputs.NPER):
        np.testing.assert_allclose(
            mf6.recharge[kper][reached], expected[kper][reached], rtol=_RECHARGE_REL, atol=0.0
        )
