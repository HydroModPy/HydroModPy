from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders import resolve_rewet_npf_options
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

from ._test_modflow6_boundary_conditions_builders import (
    _build_model,
    _build_unstructured_model,
)


def _structured_solver_mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]], dtype=float)
    botm_2d = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]], dtype=float)
    return SolverMesh.from_structured_arrays(
        nrow=2,
        ncol=3,
        top=top,
        botm=np.stack([botm_2d]),
    )


@pytest.mark.parametrize(
    ("enable_rewet", "expected_record", "expected_wetdry"),
    [
        pytest.param(
            False,
            None,
            None,
            id="test_modflow6_keeps_rewet_disabled_by_default",
        ),
        pytest.param(
            True,
            ["WETFCT", pytest.approx(0.1), "IWETIT", 1, "IHDWET", 0],
            np.full((1, 6), 0.1, dtype=float),
            id="test_modflow6_enables_rewet_when_requested",
        ),
    ],
)
def test_modflow6_rewet_flag_matrix(
    enable_rewet: bool,
    expected_record: list | None,
    expected_wetdry: np.ndarray | None,
) -> None:
    model = _build_model()
    model.flow_regime = "transient"
    if enable_rewet:
        model.modflow_config = model.modflow_config.model_copy(
            update={
                "runtime": model.modflow_config.runtime.model_copy(
                    update={"mf6_enable_rewet": True}
                )
            }
        )
    solver_mesh = _structured_solver_mesh()

    rewet_record, wetdry = resolve_rewet_npf_options(model, solver_mesh)

    if expected_record is None:
        assert rewet_record is None
    else:
        assert rewet_record == expected_record
    if expected_wetdry is None:
        assert wetdry is None
    else:
        np.testing.assert_allclose(wetdry, expected_wetdry)


def test_modflow6_disables_xt3d_by_default() -> None:
    model = _build_model()

    assert model._xt3d_requested_value() is None
    assert model._xt3d_is_enabled() is False
    assert model._resolve_xt3d_npf_options() is None


def test_modflow6_enables_xt3d_when_requested() -> None:
    model = _build_model()
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(update={"mf6_enable_xt3d": True})
        }
    )

    assert model._xt3d_is_enabled() is True
    assert model._resolve_xt3d_npf_options() == ["XT3D"]


@pytest.mark.parametrize(
    ("enable_xt3d", "expected_requested", "expected_mode", "expected_enabled", "expected_npf"),
    [
        pytest.param(
            None,
            None,
            "auto_unstructured",
            True,
            ["XT3D"],
            id="test_modflow6_auto_enables_xt3d_on_unstructured_mesh",
        ),
        pytest.param(
            False,
            False,
            "explicit_false",
            False,
            None,
            id="test_modflow6_explicit_false_disables_xt3d_on_unstructured_mesh",
        ),
    ],
)
def test_modflow6_xt3d_unstructured_flag_matrix(
    enable_xt3d: bool | None,
    expected_requested: bool | None,
    expected_mode: str,
    expected_enabled: bool,
    expected_npf: list | None,
) -> None:
    model = _build_unstructured_model()
    if enable_xt3d is not None:
        model.modflow_config = model.modflow_config.model_copy(
            update={
                "runtime": model.modflow_config.runtime.model_copy(
                    update={"mf6_enable_xt3d": enable_xt3d}
                )
            }
        )

    assert model._xt3d_requested_value() is expected_requested
    assert model._xt3d_activation_mode(model.solver_mesh) == expected_mode
    assert model._xt3d_is_enabled(model.solver_mesh) is expected_enabled
    if expected_npf is None:
        assert model._resolve_xt3d_npf_options(model.solver_mesh) is None
    else:
        assert model._resolve_xt3d_npf_options(model.solver_mesh) == expected_npf


def test_modflow6_forces_complex_ims_when_xt3d_is_active() -> None:
    model = _build_unstructured_model()
    model.modflow_config = model.modflow_config.model_copy(
        update={
            "runtime": model.modflow_config.runtime.model_copy(
                update={"mf6_ims_complexity": "SIMPLE"}
            )
        }
    )

    assert model._xt3d_is_enabled(model.solver_mesh) is True
    assert model._resolve_ims_complexity(model.solver_mesh) == "COMPLEX"
