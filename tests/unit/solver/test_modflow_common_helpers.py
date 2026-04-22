"""Unit tests for the shared MODFLOW helpers introduced in P06."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.boundary_packages import (
    BoundaryCell,
    DisvBoundaryCell,
    PackageKind,
    package_attr_names,
    validate_attrs,
)
from hydromodpy.solver.modflow_common.flow_translator import (
    MF6_PACKAGES,
    NWT_PACKAGES,
    BoundaryKind,
    resolve_package,
    resolve_packages,
)
from hydromodpy.solver.modflow_common.forcing_discretization import (
    broadcast_to_stress_periods,
    stress_period_axes,
)


class TestFlowTranslator:
    def test_resolve_package_nwt_for_stream(self) -> None:
        assert resolve_package(BoundaryKind.STREAM, solver="modflownwt") == "Riv"

    def test_resolve_package_mf6_for_recharge(self) -> None:
        assert resolve_package("recharge", solver="mf6") == "Rcha"

    def test_resolve_package_unknown_solver_raises(self) -> None:
        with pytest.raises(ValueError):
            resolve_package(BoundaryKind.DRAIN, solver="unknown")

    def test_resolve_packages_is_deduplicated(self) -> None:
        out = resolve_packages(
            [BoundaryKind.STREAM, BoundaryKind.RIV, BoundaryKind.DRAIN],
            solver="mf6",
        )
        assert out == ["Riv", "Drn"]

    def test_every_kind_has_nwt_and_mf6_mapping(self) -> None:
        for kind in BoundaryKind:
            assert kind in NWT_PACKAGES
            assert kind in MF6_PACKAGES


class TestBoundaryPackages:
    def test_drn_attrs(self) -> None:
        assert package_attr_names(PackageKind.DRN) == ("elev", "cond")

    def test_riv_attrs(self) -> None:
        assert package_attr_names("riv") == ("stage", "cond", "rbot")

    def test_validate_attrs_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_attrs(PackageKind.DRN, (1.0,))

    def test_validate_attrs_match_is_silent(self) -> None:
        validate_attrs(PackageKind.GHB, (10.0, 0.5))

    def test_boundary_cell_as_tuple(self) -> None:
        cell = BoundaryCell(layer=0, row=5, col=3, attrs=(10.0, 0.5))
        assert cell.as_tuple() == (0, 5, 3, 10.0, 0.5)

    def test_disv_boundary_cell_as_tuple(self) -> None:
        cell = DisvBoundaryCell(layer=1, cell_id=42, attrs=(7.5,))
        assert cell.as_tuple() == ((1, 42), 7.5)


class TestForcingDiscretization:
    def test_broadcast_scalar_to_stress_periods(self) -> None:
        out = broadcast_to_stress_periods(3.0, nper=2, shape=(2, 2))
        assert set(out) == {0, 1}
        assert out[0].shape == (2, 2)
        assert np.allclose(out[0], 3.0)
        assert out[0] is not out[1]  # detached copies

    def test_broadcast_array_keeps_shape(self) -> None:
        arr = np.array([[1.0, 2.0], [3.0, 4.0]])
        out = broadcast_to_stress_periods(arr, nper=3)
        assert np.array_equal(out[2], arr)

    def test_stress_period_axes(self) -> None:
        assert stress_period_axes(4) == [0, 1, 2, 3]
