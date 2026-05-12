from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.solver.modflow6.modflow6_config import (
    Modflow6Config,
    Modflow6RuntimeConfig,
)
from hydromodpy.solver.modflow6.steady_initial_conditions import (
    _modflow_config_for_steady_initialization,
)


def test_modflow6_steady_initialization_relaxes_auxiliary_solver_only() -> None:
    config = Modflow6Config(
        runtime=Modflow6RuntimeConfig(
            mf6_executable_name="mf6",
            mf6_outer_dvclose=1e-4,
            mf6_inner_dvclose=1e-4,
            mf6_outer_maximum=500,
            mf6_inner_maximum=500,
        )
    )
    model = SimpleNamespace(modflow_config=config, exe="/opt/mf6")

    steady_config = _modflow_config_for_steady_initialization(model)

    assert steady_config.runtime.mf6_executable_name == "/opt/mf6"
    assert steady_config.runtime.mf6_outer_dvclose == 1e-3
    assert steady_config.runtime.mf6_inner_dvclose == 1e-3
    assert steady_config.runtime.mf6_outer_maximum == 1000
    assert steady_config.runtime.mf6_inner_maximum == 1000
    assert config.runtime.mf6_outer_dvclose == 1e-4
    assert config.runtime.mf6_inner_dvclose == 1e-4


def test_modflow6_steady_initialization_preserves_looser_user_settings() -> None:
    config = Modflow6Config(
        runtime=Modflow6RuntimeConfig(
            mf6_outer_dvclose=2e-3,
            mf6_inner_dvclose=3e-3,
            mf6_outer_maximum=1200,
            mf6_inner_maximum=1300,
        )
    )
    model = SimpleNamespace(modflow_config=config, exe="mf6")

    steady_config = _modflow_config_for_steady_initialization(model)

    assert steady_config.runtime.mf6_outer_dvclose == 2e-3
    assert steady_config.runtime.mf6_inner_dvclose == 3e-3
    assert steady_config.runtime.mf6_outer_maximum == 1200
    assert steady_config.runtime.mf6_inner_maximum == 1300
