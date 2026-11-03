"""Each phase reports the fraction of the cost each block actually took.

``cost_block_fractions`` reads it off the ``<block>.total`` components
:class:`CompositeObjective` already writes, weighted by the same normalised
weights the objective used: ``w_i * c_i / sum_j(w_j * c_j)``.
``mean_cost_block_fractions`` averages it over several trials, the way
:func:`hydromodpy.calibration.runners.cli_runner._phase_cost_block_fractions`
averages it over a phase's finished trials.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    cost_block_fractions,
    mean_cost_block_fractions,
)
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.cli_runner import _phase_cost_block_fractions
from hydromodpy.calibration.runners.staged_runner import _reused_phase_cost_block_fractions

BLOCKS = [("network", 1.0), ("hydrograph", 3.0)]  # normalised: 0.25 / 0.75


def test_the_fraction_is_the_normalised_weighted_contribution() -> None:
    components = {"network.total": 10.0, "hydrograph.total": 2.0}

    fractions = cost_block_fractions(components, BLOCKS)

    # contributions: 0.25 * 10 = 2.5, 0.75 * 2 = 1.5, sum = 4.0
    assert fractions == pytest.approx({"network": 0.625, "hydrograph": 0.375})
    assert sum(fractions.values()) == pytest.approx(1.0)


def test_the_mean_fraction_averages_exactly_over_the_trials() -> None:
    trials = [
        {"network.total": 10.0, "hydrograph.total": 2.0},  # network 0.625, hydrograph 0.375
        {"network.total": 2.0, "hydrograph.total": 2.0},  # network 0.25, hydrograph 0.75
    ]

    mean, n_trials = mean_cost_block_fractions(BLOCKS, trials)

    assert mean == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    assert n_trials == 2


def test_a_trial_missing_a_block_total_is_skipped_from_the_mean() -> None:
    trials = [
        {"network.total": 2.0, "hydrograph.total": 2.0},  # network 0.25, hydrograph 0.75
        {"network.total": 5.0},  # no hydrograph.total: cannot be told apart, skipped
    ]

    mean, n_trials = mean_cost_block_fractions(BLOCKS, trials)

    assert mean == pytest.approx({"network": 0.25, "hydrograph": 0.75})
    assert n_trials == 1


def test_no_computable_trial_returns_none() -> None:
    trials = [{"network.total": 5.0}, None]

    assert mean_cost_block_fractions(BLOCKS, trials) is None


def test_a_single_declared_block_always_takes_the_whole_cost() -> None:
    # No ".total" key needed: a lone block is never wrapped in a CompositeObjective.
    assert cost_block_fractions({"hydrograph.raw_cost": 3.0}, [("hydrograph", 1.0)]) == {
        "hydrograph": 1.0
    }


def test_no_declared_block_gives_no_fraction() -> None:
    assert cost_block_fractions({}, []) is None
    assert mean_cost_block_fractions([], [{}]) is None


def test_weighted_costs_summing_to_zero_give_no_fraction() -> None:
    blocks = [("a", 1.0), ("b", 1.0)]
    components = {"a.total": 5.0, "b.total": -5.0}

    assert cost_block_fractions(components, blocks) is None


def test_a_signed_criterion_reads_a_non_negative_total_and_a_fraction_in_0_1() -> None:
    """``distance_gap`` publishes a signed residual, but ``.total`` already holds
    ``abs(D_so - D_os)``: the cost the composite actually weighted and summed.
    """
    network = ConfigBlockObjective(
        name="network", metric="distance_gap", uses_outputs=["net"], observed_by_output={}
    )
    hydrograph = ConfigBlockObjective(
        name="hydrograph",
        metric="rmse",
        uses_outputs=["q"],
        observed_by_output={"q": [1.0, 2.0, 3.0]},
    )
    composite = CompositeObjective([(network, 1.0), (hydrograph, 3.0)], name="composite")
    # D_so=5, D_os=8: the signed residual is -3, but the cost is abs(-3) = 3.
    sim = {"net": [5.0, 8.0], "q": [1.5, 2.5, 3.5]}

    value = composite.evaluate(sim)
    fractions = cost_block_fractions(value.components, [("network", 1.0), ("hydrograph", 3.0)])

    assert value.components["network.total"] == pytest.approx(3.0)
    weighted_network = 0.25 * value.components["network.total"]
    weighted_hydrograph = 0.75 * value.components["hydrograph.total"]
    denom = weighted_network + weighted_hydrograph
    assert denom == pytest.approx(value.total)
    assert fractions == pytest.approx(
        {"network": weighted_network / denom, "hydrograph": weighted_hydrograph / denom}
    )
    assert all(0.0 <= fraction <= 1.0 for fraction in fractions.values())


def _result(trial_id: int, cost: float, components: dict | None, **kwargs) -> EvaluationResult:
    return EvaluationResult(
        trial_id=trial_id,
        sim_id=None,
        cost=cost,
        components=components,
        status=kwargs.get("status", "completed"),
    )


def _cfg(blocks: list[tuple[str, float]]) -> SimpleNamespace:
    return SimpleNamespace(
        objective_blocks=[SimpleNamespace(name=name, weight=weight) for name, weight in blocks]
    )


def test_the_phase_report_helper_reads_mean_and_best_off_the_history() -> None:
    cfg = _cfg(BLOCKS)
    history = [
        _result(1, 4.0, {"network.total": 10.0, "hydrograph.total": 2.0}),
        _result(2, 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
    ]
    best = history[1]

    fractions = _phase_cost_block_fractions(cfg, history, best)

    assert fractions["mean_n_trials"] == 2
    assert fractions["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    assert fractions["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_a_failed_trial_does_not_enter_the_mean() -> None:
    cfg = _cfg(BLOCKS)
    history = [
        _result(1, 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
        _result(
            2, float("inf"), {"network.total": 999.0, "hydrograph.total": 999.0}, status="failed"
        ),
    ]
    best = history[0]

    fractions = _phase_cost_block_fractions(cfg, history, best)

    assert fractions["mean_n_trials"] == 1
    assert fractions["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_no_declared_blocks_gives_no_report_entry() -> None:
    cfg = _cfg([])
    history = [_result(1, 0.5, {"whatever.total": 1.0})]

    assert _phase_cost_block_fractions(cfg, history, history[0]) is None


def _seed_trials(tmp_path, trials: list[tuple[str, float, dict | None]]) -> CalibrationPersistence:
    """Journal one session with the given (status, cost, metrics) trials."""
    session_dir = tmp_path / "sessions" / "calage"
    session_dir.mkdir(parents=True, exist_ok=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id=uuid.uuid4().hex,
        case_id="calage",
        site=None,
        project="unit_test",
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        cost_name="composite",
        bounds={},
        windows={},
    )
    for index, (status, cost, components) in enumerate(trials):
        result = EvaluationResult(
            trial_id=index,
            sim_id=None,
            cost=cost,
            status=status,
            components=components,
        )
        persistence.append_iteration(ParamSuggestion(trial_id=index, values={}), result)
    persistence.finalize_session(status="completed", best=None)
    return persistence


class TestReusedPhase:
    """``_reused_phase_cost_block_fractions`` reads a reused phase's own persisted trials."""

    def test_recomputes_the_fractions_from_the_persisted_metrics(self, tmp_path) -> None:
        persistence = _seed_trials(
            tmp_path,
            [
                ("completed", 4.0, {"network.total": 10.0, "hydrograph.total": 2.0}),
                ("completed", 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
            ],
        )
        fractions, note = _reused_phase_cost_block_fractions(_cfg(BLOCKS), persistence, "main")

        assert note is None
        assert fractions["mean_n_trials"] == 2
        assert fractions["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
        # trial 2 (cost 2.0) is the best: network 0.25, hydrograph 0.75
        assert fractions["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})

    def test_a_crashed_persisted_trial_does_not_enter_the_mean(self, tmp_path) -> None:
        persistence = _seed_trials(
            tmp_path,
            [
                ("completed", 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
                # The journal accepts only finite lifecycle states; a live run never
                # journals "failed" either (cli_runner.py remaps it to "crashed" first).
                ("crashed", float("inf"), {"network.total": 999.0, "hydrograph.total": 999.0}),
            ],
        )
        fractions, note = _reused_phase_cost_block_fractions(_cfg(BLOCKS), persistence, "main")

        assert note is None
        assert fractions["mean_n_trials"] == 1
        assert fractions["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})

    def test_no_persisted_components_gives_an_absent_note_not_a_fraction(self, tmp_path) -> None:
        persistence = _seed_trials(tmp_path, [("completed", 1.0, None)])
        fractions, note = _reused_phase_cost_block_fractions(_cfg(BLOCKS), persistence, "main")

        assert fractions is None
        assert note is not None
        assert "not recomputed" in note

    def test_fewer_than_two_blocks_reports_nothing_without_touching_the_journal(self) -> None:
        fractions, note = _reused_phase_cost_block_fractions(
            _cfg([("hydrograph", 1.0)]), None, "unused"
        )

        assert fractions is None
        assert note is None
