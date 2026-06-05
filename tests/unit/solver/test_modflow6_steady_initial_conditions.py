from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.solver.modflow6.modflow6_config import (
    Modflow6Config,
    Modflow6RuntimeConfig,
)
from hydromodpy.solver.modflow6.steady_initial_conditions import (
    _modflow_config_for_steady_initialization,
    _read_final_percent_discrepancy,
    _steady_initialization_balance_is_acceptable,
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
    assert steady_config.runtime.mf6_newton is True
    assert steady_config.runtime.mf6_newton_under_relaxation is True
    assert config.runtime.mf6_outer_dvclose == 1e-4
    assert config.runtime.mf6_inner_dvclose == 1e-4


def test_modflow6_steady_initialization_disables_rewet_when_forcing_newton() -> None:
    # A user-valid newton=False + rewet=True + CG transient config must not trip
    # the NEWTON+REWET or NEWTON+CG guard during the steady spin-up (forces Newton).
    config = Modflow6Config(
        runtime=Modflow6RuntimeConfig(
            mf6_newton=False, mf6_enable_rewet=True, mf6_linear_acceleration="CG"
        )
    )
    model = SimpleNamespace(modflow_config=config, exe="mf6")

    steady_config = _modflow_config_for_steady_initialization(model)

    assert steady_config.runtime.mf6_newton is True
    assert steady_config.runtime.mf6_enable_rewet is False
    assert steady_config.runtime.mf6_linear_acceleration == "BICGSTAB"
    # The user's transient config is untouched.
    assert config.runtime.mf6_newton is False
    assert config.runtime.mf6_enable_rewet is True
    assert config.runtime.mf6_linear_acceleration == "CG"


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


def test_modflow6_steady_initialization_accepts_closed_nonconverged_budget(
    tmp_path,
) -> None:
    list_path = tmp_path / "ssic.lst"
    list_path.write_text(
        """
 PERCENT DISCREPANCY =        -200.00     PERCENT DISCREPANCY =        -200.00
 PERCENT DISCREPANCY =          -0.00     PERCENT DISCREPANCY =          -0.00
""",
        encoding="utf-8",
    )

    assert _read_final_percent_discrepancy(list_path) == -0.0
    assert _steady_initialization_balance_is_acceptable(list_path) is True


def test_modflow6_steady_initialization_rejects_open_budget(tmp_path) -> None:
    list_path = tmp_path / "ssic.lst"
    list_path.write_text(
        "PERCENT DISCREPANCY = -12.5     PERCENT DISCREPANCY = -12.5\n",
        encoding="utf-8",
    )

    assert _read_final_percent_discrepancy(list_path) == -12.5
    assert _steady_initialization_balance_is_acceptable(list_path) is False
