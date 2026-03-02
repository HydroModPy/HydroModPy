from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow_nwt.flow_to_modflow_adapter import FlowToModflowAdapter


def _build_adapter(
    *,
    initial_type: str = "top",
    initial_value: float = 0.0,
    boundary_conditions: dict[str, object] | None = None,
    active_bc: list[str] | None = None,
) -> FlowToModflowAdapter:
    dem = np.array(
        [
            [12.0, 14.0, 16.0],
            [11.0, 13.0, 15.0],
        ],
        dtype=float,
    )
    bottom = dem - 10.0

    bc = {} if boundary_conditions is None else boundary_conditions
    # Default active_bc: activate all BCs present in boundary_conditions so
    # that existing tests continue to pass without requiring explicit lists.
    if active_bc is None:
        active_bc = list(bc.keys())

    flow = SimpleNamespace(
        initial_conditions=SimpleNamespace(
            h=SimpleNamespace(type=initial_type, value=initial_value)
        ),
        boundary_conditions=bc,
        active_bc=active_bc,
        sinks_sources={},
        active_sinks_sources=[],
        parameters={},
    )
    domain = SimpleNamespace(zones={})
    sgrid = SimpleNamespace()

    return FlowToModflowAdapter(
        flow=flow,
        domain=domain,
        sgrid=sgrid,
        dem=dem,
        bottom_layer=bottom,
        nlay=2,
        nrow=dem.shape[0],
        ncol=dem.shape[1],
        nper=1,
        resolution=5.0,
        sink_fill=False,
    )


def test_initial_heads_and_side_boundaries_follow_bas_contract():
    adapter = _build_adapter(
        initial_type="top",
        boundary_conditions={"west_side": SimpleNamespace(value=9.5)},
    )

    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()

    assert ibound.shape == (2, 2, 3)
    assert strt.shape == (2, 2, 3)
    assert drain_array.shape == (2, 3)

    # West side is set as constant-head.
    assert np.all(ibound[:, :, 0] < 0)
    assert np.all(strt[:, :, 0] == 9.5)

    # Interior follows top initialization policy.
    np.testing.assert_allclose(strt[0, :, 1:], adapter.dem[:, 1:])
    np.testing.assert_allclose(strt[1, :, 1:], adapter.dem[:, 1:])

    adapter._validate_ibound_strt_contract(
        ibound=ibound,
        strt=strt,
        drain_array=drain_array,
    )


def test_validate_ibound_strt_contract_rejects_shape_mismatch():
    adapter = _build_adapter(initial_type="custom", initial_value=7.0)
    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()

    with pytest.raises(ValueError, match="ibound shape mismatch"):
        adapter._validate_ibound_strt_contract(
            ibound=ibound[0],  # wrong shape on purpose
            strt=strt,
            drain_array=drain_array,
        )


def test_validate_ibound_strt_contract_rejects_non_finite_starting_heads():
    adapter = _build_adapter(initial_type="bottom")
    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()
    strt_bad = strt.copy()
    strt_bad[0, 0, 0] = np.nan

    with pytest.raises(ValueError, match="strt contains non-finite values"):
        adapter._validate_ibound_strt_contract(
            ibound=ibound,
            strt=strt_bad,
            drain_array=drain_array,
        )


def test_validate_ibound_strt_contract_rejects_non_binary_drain_mask():
    adapter = _build_adapter(initial_type="top")
    ibound, strt, drain_array = adapter._build_initial_heads_and_sides()
    drain_bad = drain_array.copy()
    drain_bad[0, 0] = 0.5

    with pytest.raises(ValueError, match="drain_array must only contain binary"):
        adapter._validate_ibound_strt_contract(
            ibound=ibound,
            strt=strt,
            drain_array=drain_bad,
        )
