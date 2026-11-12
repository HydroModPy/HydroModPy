"""Flow properties on a NWT grid from the profiles of the model, with or without a spatial support.

Hydraulic conductivity K is in m/s and specific yield Sy is dimensionless. A heterogeneous
profile reads its zone fractions from a support of the domain. Values are flat per cell, row 0
first, and a runtime override replaces the profile of its property.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.properties.field_spatial import WeightedAverageFieldDiscretization
from hydromodpy.solver.modflow_common.property_mapping import resolve_flow_property_arrays
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def mesh_of(nlay: int = 1, nrow: int = 2, ncol: int = 4):
    top = np.full((nrow, ncol), 10.0)
    botm = np.empty((nlay, nrow, ncol))
    for ilay in range(nlay):
        botm[ilay] = 9.0 - float(ilay)
    return solver_mesh_from_structured_arrays(nrow=nrow, ncol=ncol, top=top, botm=botm)


class _HalfDomainSupport:
    """Two zones: the cells left of the middle of the domain, and the others."""

    identifier = "support_halves"
    default_cell_samples_per_axis = 4

    def on_mesh(self, cell_mesh, *, cell_samples_per_axis: int = 10):
        x_centers = np.asarray(cell_mesh.centers[:, 0], dtype=float)
        midpoint = 0.5 * (x_centers.min() + x_centers.max())
        left = (x_centers <= midpoint).astype(float)
        return WeightedAverageFieldDiscretization(
            mesh=cell_mesh,
            field_id=self.identifier,
            zone_keys=("left", "right"),
            fractions_by_zone={"left": left, "right": 1.0 - left},
        )


HOMOGENEOUS_K = FieldParam(identifier="K", kind="homogeneous", value=1.25)
HALVES_K = FieldParam(
    identifier="K",
    kind="heterogeneous",
    values_by_key={"left": 10.0, "right": 2.0},
    field_spatial_id="support_halves",
)


def resolve(profiles, zones, mesh, required, **kwargs):
    return resolve_flow_property_arrays(
        profiles=profiles,
        domain=SimpleNamespace(zones=zones),
        solver_mesh=mesh,
        required_properties=required,
        **kwargs,
    )


def test_homogeneous_profile_needs_no_support() -> None:
    actual = resolve({"K": HOMOGENEOUS_K}, {}, mesh_of(nlay=2), {"K"})

    np.testing.assert_allclose(actual["hk"], 1.25)
    np.testing.assert_allclose(actual["hk_value"], 1.25)


def test_heterogeneous_profile_uses_its_support() -> None:
    actual = resolve({"K": HALVES_K}, {"halves": _HalfDomainSupport()}, mesh_of(), {"K"})

    # The NWT adapter reshapes this flat surface to its DIS grid.
    expected_surface = np.array([10.0, 10.0, 2.0, 2.0, 10.0, 10.0, 2.0, 2.0])
    np.testing.assert_array_equal(actual["hk_value"], expected_surface)
    np.testing.assert_array_equal(actual["hk"][0], expected_surface)


def test_runtime_override_replaces_the_profile() -> None:
    profiles = {
        "K": HOMOGENEOUS_K,
        "Sy": FieldParam(identifier="Sy", kind="homogeneous", value=0.05),
    }

    actual = resolve(
        profiles,
        {},
        mesh_of(nlay=2),
        {"K", "Sy"},
        runtime_property_overrides={"K": np.full((2, 2, 4), 3.0)},
    )

    np.testing.assert_allclose(actual["hk"], 3.0)
    np.testing.assert_allclose(actual["hk_value"], 3.0)
    np.testing.assert_allclose(actual["sy"], 0.05)
    np.testing.assert_allclose(actual["sy_value"], 0.05)


def test_refusals() -> None:
    with pytest.raises(ValueError, match="Missing spatial support 'support_halves'"):
        resolve({"K": HALVES_K}, {}, mesh_of(), {"K"})
