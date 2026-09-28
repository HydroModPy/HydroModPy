"""The MODFLOW 6 replication of the reference script must not drift to the recipe.

``ref_example04.toml`` exists to be read beside ``example_04_calibration.py``: it
measures what changes when the published estimator is replaced by the script's
own mean offset. Someone tidying it toward the protocol's published defaults
would delete the only thing it is for, and the file would still validate. So the
values it departs on are gated, not commented.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.protocols import protocol_options_away_from_the_recipe
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    HYDROGRAPH_BLOCK,
    HYDROGRAPH_OUTPUT,
    NETWORK_BLOCK,
    STEADY_STAGE,
    TRANSIENT_STAGE,
)
from hydromodpy.calibration.runners.phase_regime import phase_overrides
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.toml_io.loader import load_toml_with_base_config

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
    assert calibration.protocol.version == "1.2"
    assert [phase.name for phase in calibration.phases] == [STEADY_STAGE, TRANSIENT_STAGE]
    assert [block.name for block in calibration.objective_blocks] == [
        NETWORK_BLOCK,
        HYDROGRAPH_BLOCK,
    ]


def test_stage_one_keeps_the_scripts_mean_offset_and_nelder_mead(calibration) -> None:
    assert calibration.objective_blocks[0].metric == "distance_mean"
    steady = calibration.phases[0]
    assert steady.method == "scipy_nelder_mead"
    assert steady.max_iter == 60
    assert steady.method_options == {
        "maxiter": 30,
        "maxfev": 60,
        "xatol": 0.30,
        "fatol": 0.05,
    }


# The steady trace of a Nancon session run with these options on 2026-09-08:
# log10 K against the mean offset, in metres. Nine solves, one of them a repeat.
_NANCON_STEADY_TRACE = {
    -5.0: 287.3839080695424,
    -4.4: 186.641131046373,
    -3.8: 300.1191516816517,
    -4.55: 214.26321839924782,
    -4.25: 185.7234104098768,
    -3.95: 232.09030552780553,
    -4.1: 208.383141357349,
    -4.2875: 192.34474990832632,
}


def _replay(sugg: ParamSuggestion) -> EvaluationResult:
    point = round(math.log10(float(sugg.values["K"])), 6)
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=_NANCON_STEADY_TRACE[point],
        status="completed",
    )


def test_stage_one_meets_its_own_tolerance_well_inside_scipys_cap(calibration) -> None:
    # SciPy's maxiter = 30 sits below the phase's max_iter = 60, and a simplex
    # that SciPy stops on that cap reports not converged. On the recorded
    # Nancon trace the simplex meets xatol and fatol after 9 solves, so the
    # steady stage converges and freezes K for the transient one.
    steady = calibration.phases[0]
    lower, upper = calibration.parameters["K"].bounds
    space = ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, transform="log")])
    optimizer = ScipyNelderMead(space, **steady.method_options)
    engine = CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=_replay, max_iter=steady.max_iter
    )

    session = engine.run()

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == 9


def test_stage_one_collapses_the_record_into_one_steady_period(calibration) -> None:
    # 1995-01-01 to 2020-12-31 inclusive, the window the REA recharge stops at.
    # The protocol writes the regime; the paths are what the trials run with.
    assert calibration.phases[0].regime == "steady"
    assert phase_overrides(calibration.phases[0], load_toml_with_base_config(REFERENCE)) == {
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
    assert storage.objective_blocks == [HYDROGRAPH_BLOCK]
    assert storage.max_iter == 120
    assert storage.method_options["xatol"] == pytest.approx(3.7e-5)
    # The reference scores the whole calibration window, with no spin-up year cut.
    # The protocol leaves the first year out by default, so the file says so.
    assert storage.scoring_window is not None
    assert (storage.scoring_window.start, storage.scoring_window.end) == ("1995-01-01", None)

    hydrograph = next(
        block for block in calibration.objective_blocks if block.name == HYDROGRAPH_BLOCK
    )
    assert hydrograph.metric == "nse_log"
    assert hydrograph.uses_outputs == [HYDROGRAPH_OUTPUT]
    output = calibration.outputs[HYDROGRAPH_OUTPUT]
    assert output.observes == "NANCON"
    assert output.variable == "discharge"


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
