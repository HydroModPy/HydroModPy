"""The MODFLOW 6 replication of the reference script must not drift to the recipe.

``ref_example04.toml`` exists to be read beside ``example_04_calibration.py``: it
measures what changes when the published estimator is replaced by the script's
own mean offset. Someone tidying it toward the protocol's published defaults
would delete the only thing it is for, and the file would still validate. So the
values it departs on are gated, not commented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.protocols import protocol_options_away_from_the_recipe
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    NETWORK_BLOCK,
    STEADY_STAGE,
    TRANSIENT_STAGE,
)
from hydromodpy.config import HydroModPyConfig

REFERENCE = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "projects"
    / "21_nancon_network_calibration"
    / "ref_example04.toml"
)


@pytest.fixture(scope="module")
def calibration():
    return HydroModPyConfig.from_toml(REFERENCE).calibration


def test_the_two_stages_come_from_the_named_protocol(calibration) -> None:
    assert calibration.protocol is not None
    assert calibration.protocol.name == "matching_hydrographic_network"
    # Pinned, so the comparison cannot silently move with the recipe.
    assert calibration.protocol.version == "1.0"
    assert [phase.name for phase in calibration.phases] == [STEADY_STAGE, TRANSIENT_STAGE]
    assert [block.name for block in calibration.objective_blocks] == [NETWORK_BLOCK]


def test_stage_one_keeps_the_scripts_mean_offset_and_nelder_mead(calibration) -> None:
    assert calibration.objective_blocks[0].metric == "distance_mean"
    steady = calibration.phases[0]
    assert steady.method == "scipy_nelder_mead"
    assert steady.max_iter == 60
    assert steady.optimizer_kwargs == {
        "maxiter": 30,
        "maxfev": 60,
        "xatol": 0.30,
        "fatol": 0.05,
    }


def test_stage_one_collapses_the_record_into_one_steady_period(calibration) -> None:
    # 1995-01-01 to 2020-12-31 inclusive, the window the REA recharge stops at.
    assert calibration.phases[0].overrides == {
        "flow.flow_regime": "steady",
        "simulation.time.start_datetime": "1995-01-01",
        "simulation.time.end_datetime": "2020-12-31",
        "simulation.time.step_unit": "day",
        "simulation.time.step_value": 9497,
    }


def test_stage_two_reads_storage_from_the_hydrograph_with_conductivity_frozen(calibration) -> None:
    assert calibration.phases[0].freeze_on_success is True
    storage = calibration.phases[1]
    assert storage.depends_on == STEADY_STAGE
    assert storage.parameters == ["Sy"]
    assert storage.objective == "nse_log"
    assert storage.max_iter == 120
    assert storage.optimizer_kwargs["xatol"] == pytest.approx(3.7e-5)
    # The reference scores the whole calibration window, with no spin-up year cut.
    assert storage.scoring_window is None


def test_the_file_departs_from_the_recipe_on_the_estimator_and_the_engine(calibration) -> None:
    moved = {
        item["key"]: item["here"]
        for item in protocol_options_away_from_the_recipe(
            "matching_hydrographic_network", calibration.protocol
        )
    }
    assert moved["steady_metric"] == "distance_mean"
    assert moved["steady_method"] == "scipy_nelder_mead"


def test_the_uncertainty_interval_costs_no_extra_run(calibration) -> None:
    assert calibration.uncertainty is not None
    assert calibration.uncertainty.method == "cost_profile"


def test_the_two_stage_card_is_asked_for_by_its_current_name() -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    assert "matching_hydrographic_network_card" in text
    assert "abherve_two_stage_card" not in text
