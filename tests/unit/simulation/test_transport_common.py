"""Unit tests for shared transport adapter helpers."""

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow_common.runtime_arrays import (
    build_concentration_runtime_overrides,
    flow_grid_shape,
)


def test_flow_grid_shape_supports_legacy_modflow_wrapper() -> None:
    flow_model = SimpleNamespace(mf=SimpleNamespace(nlay=2, nrow=3, ncol=4))
    assert flow_grid_shape(flow_model) == (2, 3, 4)


def test_build_concentration_runtime_overrides_expands_scalar_payloads() -> None:
    flow_model = SimpleNamespace(nlay=2, nrow=3, ncol=4, nper=5)
    overrides = build_concentration_runtime_overrides(
        {
            "sconc_init": 0.1,
            "sconc_input": 0.05,
            "rate_decay": 0.001,
        },
        flow_model,
    )

    sconc_init = overrides["sconc_init"]
    rate_decay = overrides["rate_decay"]
    sconc_input = overrides["sconc_input"]

    assert isinstance(sconc_init, np.ndarray)
    assert sconc_init.shape == (2, 3, 4)
    assert np.allclose(sconc_init, 0.1)

    assert isinstance(rate_decay, np.ndarray)
    assert rate_decay.shape == (2, 3, 4)
    assert np.allclose(rate_decay, 0.001)

    assert isinstance(sconc_input, dict)
    assert set(sconc_input) == {1, 2, 3, 4}
    assert all(arr.shape == (3, 4) for arr in sconc_input.values())
    assert all(np.allclose(arr, 0.05) for arr in sconc_input.values())


def test_build_concentration_runtime_overrides_normalizes_mapping_payloads() -> None:
    flow_model = SimpleNamespace(nlay=1, nrow=2, ncol=3, nper=4)
    overrides = build_concentration_runtime_overrides(
        {
            "sconc_input": {
                "1": 0.2,
                2: [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
            }
        },
        flow_model,
    )

    sconc_input = overrides["sconc_input"]
    assert set(sconc_input) == {1, 2}
    assert np.allclose(sconc_input[1], np.full((2, 3), 0.2))
    assert np.allclose(
        sconc_input[2],
        np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
    )
