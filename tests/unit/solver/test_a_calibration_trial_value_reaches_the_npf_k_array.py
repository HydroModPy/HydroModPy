"""A trial's characteristic_depth reaches the built MODFLOW 6 NPF k array.

``resolve_flow_property_arrays`` (``hydromodpy/solver/modflow6/support/
property_mapping.py``) is what ``build.py`` calls to produce ``model.hk``,
which is then passed verbatim as ``k=model.hk`` to ``flopy.mf6.ModflowGwfnpf``
(``solver_mesh.flatten_from_grid`` only reshapes it, it never changes a
value). Proving the ratio on this function's output is proving it on the NPF
package's own k array.

Evaluation depth: the layer-center depth below the model top, exactly what
``SolverMesh.layer_center_depths()`` defines: ``top - 0.5 * (layer_top +
layer_bottom)``. On a 30 m column in two layers (layer 1 = the top 10 m,
layer 2 = the next 20 m), the layer centers sit 5 m and 20 m below the top,
so the exponential profile predicts ``k2 / k1 = exp(-(20 - 5) / characteristic_depth)``.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.support.property_mapping import resolve_flow_property_arrays
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.field.field_param import FieldParam
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

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
    flow = SimpleNamespace(parameters={"K": field_param})
    domain = SimpleNamespace(zones={})
    out = resolve_flow_property_arrays(
        flow=flow,
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
