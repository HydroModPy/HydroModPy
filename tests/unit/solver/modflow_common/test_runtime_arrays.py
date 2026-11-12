"""Run-time arrays the MODFLOW adapters build from scalar or gridded user payloads.

A scalar is expanded to the (nlay, nrow, ncol) grid and a surface of cells is repeated on every
layer. Concentrations are in the unit of the transport model, K in m/s.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.model.properties.property_table import resolve_flow_property_runtime_overrides
from hydromodpy.solver.modflow_common.runtime_arrays import (
    build_concentration_runtime_overrides,
    flow_grid_shape,
)


def test_grid_shape_of_a_legacy_wrapper() -> None:
    flow_model = SimpleNamespace(mf=SimpleNamespace(nlay=2, nrow=3, ncol=4))
    assert flow_grid_shape(flow_model) == (2, 3, 4)


def test_scalar_concentrations_fill_the_grid() -> None:
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


def test_concentration_input_by_period() -> None:
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


def test_surface_property_repeats_on_layers() -> None:
    overrides = resolve_flow_property_runtime_overrides(
        {"properties": {"K": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], "Sy": 0.2}},
        nlay=2,
        n_cells=6,
        required_properties={"K", "Sy"},
    )

    # A grid-shaped surface reads as its cells, row 0 first; the result is flat.
    assert overrides["hk"].shape == (2, 6)
    assert overrides["hk_value"].shape == (6,)
    assert np.array_equal(overrides["hk_value"], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert np.array_equal(overrides["hk"][0], overrides["hk_value"])
    assert np.array_equal(overrides["hk"][1], overrides["hk_value"])
    assert np.allclose(overrides["sy"], 0.2)


def test_full_property_arrays() -> None:
    overrides = resolve_flow_property_runtime_overrides(
        {"K": [[1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]]},
        nlay=2,
        n_cells=4,
        required_properties={"K"},
    )

    assert overrides["hk"].shape == (2, 4)
    assert overrides["hk_value"].shape == (4,)
    assert np.allclose(overrides["hk"][1], [10.0, 20.0, 30.0, 40.0])
    assert np.allclose(overrides["hk_value"], [1.0, 2.0, 3.0, 4.0])


def test_property_of_a_wrong_size_is_refused() -> None:
    with pytest.raises(ValueError, match="incompatible size"):
        resolve_flow_property_runtime_overrides(
            {"K": [1.0, 2.0, 3.0]}, nlay=2, n_cells=4, required_properties={"K"}
        )
