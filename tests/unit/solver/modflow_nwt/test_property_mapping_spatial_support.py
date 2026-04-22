from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.spatial.field.core.field_param import FieldParam
from hydromodpy.spatial.field.core.field_spatial_weighted_discretization import (
    WeightedAverageFieldDiscretization,
)
from hydromodpy.solver.modflow_common.solver_mesh import SolverMesh
from hydromodpy.solver.modflow_nwt.modflow.property_mapping import (
    resolve_flow_property_arrays,
)


def _build_solver_mesh(*, nlay: int = 1, nrow: int = 2, ncol: int = 4):
    top = np.full((nrow, ncol), 10.0, dtype=float)
    botm = np.empty((nlay, nrow, ncol), dtype=float)
    for ilay in range(nlay):
        botm[ilay, :, :] = 9.0 - float(ilay)
    return SolverMesh.from_structured_arrays(
        nrow=nrow,
        ncol=ncol,
        top=top,
        botm=botm,
    )


class _HalfDomainSupport:
    def __init__(self, identifier: str = "support_halves") -> None:
        self.identifier = identifier
        self.default_cell_samples_per_axis = 4

    def on_mesh(self, mesh, *, cell_samples_per_axis: int = 10):
        _ = cell_samples_per_axis
        x_centers, _ = mesh.cell_centroids()
        x_centers = np.asarray(x_centers, dtype=float)
        midpoint = 0.5 * (float(np.min(x_centers)) + float(np.max(x_centers)))
        left = (x_centers <= midpoint).astype(float)
        right = 1.0 - left
        return WeightedAverageFieldDiscretization(
            mesh=mesh,
            field_id=self.identifier,
            zone_keys=("left", "right"),
            fractions_by_zone={
                "left": left,
                "right": right,
            },
        )


def test_resolve_flow_property_arrays_homogeneous_without_spatial_support() -> None:
    flow = SimpleNamespace(
        parameters={
            "K": FieldParam(
                identifier="K",
                kind="homogeneous",
                value=1.25,
            )
        }
    )
    domain = SimpleNamespace(zones={})
    mesh = _build_solver_mesh(nlay=2)

    actual = resolve_flow_property_arrays(
        flow=flow,
        domain=domain,
        solver_mesh=mesh,
        required_properties={"K"},
    )

    np.testing.assert_allclose(actual["hk"], 1.25)
    np.testing.assert_allclose(actual["hk_value"], 1.25)


def test_resolve_flow_property_arrays_heterogeneous_uses_non_geology_support() -> None:
    flow = SimpleNamespace(
        parameters={
            "K": FieldParam(
                identifier="K",
                kind="heterogeneous",
                values_by_key={"left": 10.0, "right": 2.0},
                field_spatial_id="support_halves",
            )
        }
    )
    domain = SimpleNamespace(zones={"halves": _HalfDomainSupport()})
    mesh = _build_solver_mesh()

    actual = resolve_flow_property_arrays(
        flow=flow,
        domain=domain,
        solver_mesh=mesh,
        required_properties={"K"},
    )

    expected_surface = np.array(
        [
            [10.0, 10.0, 2.0, 2.0],
            [10.0, 10.0, 2.0, 2.0],
        ],
        dtype=float,
    )
    np.testing.assert_allclose(actual["hk_value"], expected_surface)
    np.testing.assert_allclose(actual["hk"][0], expected_surface)


def test_resolve_flow_property_arrays_reports_missing_requested_support() -> None:
    flow = SimpleNamespace(
        parameters={
            "K": FieldParam(
                identifier="K",
                kind="heterogeneous",
                values_by_key={"left": 10.0, "right": 2.0},
                field_spatial_id="support_halves",
            )
        }
    )
    domain = SimpleNamespace(zones={})
    mesh = _build_solver_mesh()

    with pytest.raises(ValueError, match="Missing spatial support 'support_halves'"):
        resolve_flow_property_arrays(
            flow=flow,
            domain=domain,
            solver_mesh=mesh,
            required_properties={"K"},
        )


def test_resolve_flow_property_arrays_prefers_runtime_overrides() -> None:
    flow = SimpleNamespace(
        parameters={
            "K": FieldParam(
                identifier="K",
                kind="homogeneous",
                value=1.25,
            ),
            "Sy": FieldParam(
                identifier="Sy",
                kind="homogeneous",
                value=0.05,
            ),
        }
    )
    domain = SimpleNamespace(zones={})
    mesh = _build_solver_mesh(nlay=2)

    actual = resolve_flow_property_arrays(
        flow=flow,
        domain=domain,
        solver_mesh=mesh,
        required_properties={"K", "Sy"},
        runtime_property_overrides={
            "properties": {
                "K": np.full((2, 2, 4), 3.0, dtype=float),
            }
        },
    )

    np.testing.assert_allclose(actual["hk"], 3.0)
    np.testing.assert_allclose(actual["hk_value"], 3.0)
    np.testing.assert_allclose(actual["sy"], 0.05)
    np.testing.assert_allclose(actual["sy_value"], 0.05)
