"""The saturated thickness a network trial publishes beside its distances.

``d_sat_m`` is the paper's dsat: the saturated thickness averaged by area over
the catchment, at the state the network is read from. It never enters the pair
the criterion scores, and a backend that serves no such field loses it alone.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.metrics.solver_extract import (
    _saturated_thickness_or_none,
    catchment_saturation,
)
from hydromodpy.core.exceptions import ObservableNotAvailableError


def _run_ctx(*, top, botm, inactive_mask=None):
    mesh = SimpleNamespace(top=np.asarray(top, dtype=float), botm=np.asarray(botm, dtype=float))
    if inactive_mask is not None:
        mesh.inactive_mask = np.asarray(inactive_mask, dtype=bool)
    return SimpleNamespace(model=SimpleNamespace(solver_mesh=mesh))


def _geometry(catchment, areas):
    return SimpleNamespace(
        catchment=np.asarray(catchment, dtype=bool),
        cell_area_m2=np.asarray(areas, dtype=float),
    )


def test_area_weighted_over_the_catchment_at_the_last_state() -> None:
    run_ctx = _run_ctx(top=[100.0, 100.0, 100.0, 100.0], botm=[[90.0] * 4, [70.0] * 4])
    geometry = _geometry([True, True, False, True], [1.0, 3.0, 50.0, 1.0])
    # Two timesteps: only the last one is read, as the network reads it. The
    # third cell lies outside the catchment and weighs fifty times the others.
    thickness = SimpleNamespace(values=np.array([[0.0] * 4, [10.0, 20.0, 99.0, np.nan]]))

    out = catchment_saturation(run_ctx, geometry, thickness)

    assert out["d_sat_m"] == pytest.approx((10.0 * 1.0 + 20.0 * 3.0) / 4.0)
    assert out["d_sat_unset_fraction"] == pytest.approx(1.0 / 5.0)
    assert out["d_aquifer_m"] == pytest.approx(30.0)
    assert out["d_sat_over_d"] == pytest.approx(17.5 / 30.0)


def test_the_unset_share_splits_into_dry_and_inactive_when_the_mesh_says_which() -> None:
    # MODFLOW writes HDRY on a dry cell and HNOFLO on one it never computed,
    # and both come back NaN. The inactive mask of the top layer is what tells
    # them apart; a lake footprint is one such cell, and it is not a dry state.
    run_ctx = _run_ctx(
        top=[100.0] * 4,
        botm=[[90.0] * 4, [70.0] * 4],
        inactive_mask=[[False, False, True, False], [False, False, True, False]],
    )
    geometry = _geometry([True, True, True, True], [1.0, 2.0, 3.0, 4.0])
    thickness = SimpleNamespace(values=np.array([10.0, np.nan, np.nan, 20.0]))

    out = catchment_saturation(run_ctx, geometry, thickness)

    assert out["d_sat_dry_fraction"] == pytest.approx(2.0 / 10.0)
    assert out["d_sat_inactive_fraction"] == pytest.approx(3.0 / 10.0)
    assert "d_sat_unset_fraction" not in out
    assert out["d_sat_m"] == pytest.approx((10.0 * 1.0 + 20.0 * 4.0) / 5.0)


def test_a_mask_on_another_mesh_keeps_the_single_unset_share() -> None:
    run_ctx = _run_ctx(top=[100.0] * 2, botm=[[70.0] * 2], inactive_mask=[[False] * 3])
    thickness = SimpleNamespace(values=np.array([10.0, np.nan]))

    out = catchment_saturation(run_ctx, _geometry([True, True], [1.0, 1.0]), thickness)

    assert out["d_sat_unset_fraction"] == pytest.approx(0.5)
    assert "d_sat_dry_fraction" not in out


def test_nothing_without_a_saturated_thickness() -> None:
    run_ctx = _run_ctx(top=[100.0], botm=[[70.0]])

    assert catchment_saturation(run_ctx, _geometry([True], [1.0]), None) == {}


def test_a_field_on_another_mesh_warns_and_leaves_the_trial_scored(caplog) -> None:
    run_ctx = _run_ctx(top=[100.0, 100.0], botm=[[70.0, 70.0]])
    thickness = SimpleNamespace(values=np.array([10.0, 20.0, 30.0]))

    with caplog.at_level(logging.WARNING):
        out = catchment_saturation(run_ctx, _geometry([True, True], [1.0, 1.0]), thickness)

    assert out == {}
    assert "holds 3 cells" in caplog.text


def test_a_backend_without_the_field_keeps_the_criterion() -> None:
    class _Adapter:
        def extract_observables(self, _run_ctx, _store, _requests, *, time_index=None):
            raise ObservableNotAvailableError("no saturated thickness here")

    output = SimpleNamespace(time="all")

    assert _saturated_thickness_or_none(_Adapter(), None, "network", output, None) is None


def test_the_request_reads_the_same_times_as_the_network() -> None:
    seen = []

    class _Adapter:
        def extract_observables(self, _run_ctx, _store, requests, *, time_index=None):
            seen.extend(requests)
            return {requests[0].id: "field"}

    output = SimpleNamespace(time="last")

    assert _saturated_thickness_or_none(_Adapter(), None, "network", output, None) == "field"
    assert seen[0].name == "saturated_thickness"
    assert seen[0].support == "cells"
    assert seen[0].times == "last"
