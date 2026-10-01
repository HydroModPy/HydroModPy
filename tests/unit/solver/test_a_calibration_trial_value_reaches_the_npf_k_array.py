"""A trial's characteristic_depth reaches the built MODFLOW 6 NPF k array.

``resolve_flow_property_arrays`` (``hydromodpy/solver/modflow6/support/
property_mapping.py``) is what ``build.py`` calls to produce ``model.hk``,
which is then passed verbatim as ``k=model.hk`` to ``flopy.mf6.ModflowGwfnpf``
(``solver_mesh.flatten_from_grid`` only reshapes it, it never changes a
value). Proving the ratio on this function's output is proving it on the NPF
package's own k array.

Evaluation depth: the layer-center depth below the model top, exactly what
``SolverMesh.layer_center_depths()`` defines: ``top - 0.5 * (layer_top +
layer_bottom)``. On a 30 m column built with ``genmtd_lay = "list"``,
``lay_proportions = [1/3, 2/3]`` (layer 1 = the top 10 m, layer 2 = the next
20 m), the layer centres sit 5 m and 20 m below the top, so the exponential
profile predicts ``k2 / k1 = exp(-(20 - 5) / characteristic_depth)``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from hydromodpy.solver.modflow6.support.property_mapping import resolve_flow_property_arrays
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import SGridConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_from_config import build_sgrid_from_config

_TOP_ELEVATION = 30.0
_DEPTH_LAYER_1 = 5.0
_DEPTH_LAYER_2 = 20.0


def _flat_top_raster(path: Path) -> None:
    data = np.full((2, 2), _TOP_ELEVATION, dtype=np.float32)
    transform = from_origin(0.0, 2.0, 1.0, 1.0)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype=data.dtype,
        crs="EPSG:2154",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)


def _column_solver_mesh(tmp_path: Path) -> SolverMesh:
    """A 30 m column, genmtd_lay='list', lay_proportions=[1/3, 2/3]."""
    top_path = tmp_path / "top.tif"
    _flat_top_raster(top_path)
    sgrid = build_sgrid_from_config(
        SGridConfig(
            top_path=str(top_path),
            bottom={"kind": "constant_altitude", "zbot": 0.0},
            layering={"kind": "list", "lay_proportions": [1 / 3, 2 / 3]},
        )
    )
    return SolverMesh.from_sgrid(
        sgrid,
        zbot=np.asarray(sgrid.botm, dtype=float),
        inactive_mask=np.zeros((2, 2), dtype=bool),
    )


def _hk(characteristic_depth: float, tmp_path: Path) -> np.ndarray:
    solver_mesh = _column_solver_mesh(tmp_path)
    assert solver_mesh.is_structured
    field_param = FieldParam(
        identifier="K",
        kind="homogeneous",
        value=1e-4,
        vertical_profile={"mode": "exponential", "characteristic_depth": characteristic_depth},
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
def test_characteristic_depth_sets_the_npf_k_layer_ratio(
    tmp_path: Path, characteristic_depth: float
) -> None:
    hk = _hk(characteristic_depth, tmp_path)
    k1, k2 = float(hk[0].flat[0]), float(hk[1].flat[0])

    expected_ratio = np.exp(-(_DEPTH_LAYER_2 - _DEPTH_LAYER_1) / characteristic_depth)
    assert k2 / k1 == pytest.approx(expected_ratio, rel=1e-6)


def test_two_trial_values_give_two_different_npf_k_arrays(tmp_path: Path) -> None:
    hk_short = _hk(10.0, tmp_path)
    hk_long = _hk(80.0, tmp_path)

    ratio_short = hk_short[1].flat[0] / hk_short[0].flat[0]
    ratio_long = hk_long[1].flat[0] / hk_long[0].flat[0]

    assert ratio_short != pytest.approx(ratio_long)
