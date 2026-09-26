"""Each phase reports the share of the cost each block actually took.

``objective_block_shares`` reads it off the ``<block>.total`` components
:class:`CompositeObjective` already writes, weighted by the same normalised
weights the objective used: ``w_i * c_i / sum_j(w_j * c_j)``.
``mean_objective_block_shares`` averages it over several trials, the way
:func:`hydromodpy.calibration.runners.cli_runner._phase_objective_block_shares`
averages it over a phase's finished trials.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.objective import (
    CompositeObjective,
    ConfigBlockObjective,
    mean_objective_block_shares,
    objective_block_shares,
)
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.cli_runner import _phase_objective_block_shares
from hydromodpy.calibration.runners.staged_runner import _reused_phase_objective_block_shares
from tests._helpers.fixtures_catalog import simulation_catalog

BLOCKS = [("network", 1.0), ("hydrograph", 3.0)]  # normalised: 0.25 / 0.75


def test_the_share_is_the_normalised_weighted_contribution() -> None:
    components = {"network.total": 10.0, "hydrograph.total": 2.0}

    shares = objective_block_shares(components, BLOCKS)

    # contributions: 0.25 * 10 = 2.5, 0.75 * 2 = 1.5, sum = 4.0
    assert shares == pytest.approx({"network": 0.625, "hydrograph": 0.375})
    assert sum(shares.values()) == pytest.approx(1.0)


def test_the_mean_share_averages_exactly_over_the_trials() -> None:
    trials = [
        {"network.total": 10.0, "hydrograph.total": 2.0},  # network 0.625, hydrograph 0.375
        {"network.total": 2.0, "hydrograph.total": 2.0},  # network 0.25, hydrograph 0.75
    ]

    mean, n_trials = mean_objective_block_shares(BLOCKS, trials)

    assert mean == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    assert n_trials == 2


def test_a_trial_missing_a_block_total_is_skipped_from_the_mean() -> None:
    trials = [
        {"network.total": 2.0, "hydrograph.total": 2.0},  # network 0.25, hydrograph 0.75
        {"network.total": 5.0},  # no hydrograph.total: cannot be told apart, skipped
    ]

    mean, n_trials = mean_objective_block_shares(BLOCKS, trials)

    assert mean == pytest.approx({"network": 0.25, "hydrograph": 0.75})
    assert n_trials == 1


def test_no_computable_trial_returns_none() -> None:
    trials = [{"network.total": 5.0}, None]

    assert mean_objective_block_shares(BLOCKS, trials) is None


def test_a_single_declared_block_always_takes_the_whole_cost() -> None:
    # No ".total" key needed: a lone block is never wrapped in a CompositeObjective.
    assert objective_block_shares({"hydrograph.raw_cost": 3.0}, [("hydrograph", 1.0)]) == {
        "hydrograph": 1.0
    }


def test_no_declared_block_gives_no_share() -> None:
    assert objective_block_shares({}, []) is None
    assert mean_objective_block_shares([], [{}]) is None


def test_weighted_costs_summing_to_zero_give_no_share() -> None:
    blocks = [("a", 1.0), ("b", 1.0)]
    components = {"a.total": 5.0, "b.total": -5.0}

    assert objective_block_shares(components, blocks) is None


def test_a_signed_criterion_reads_a_non_negative_total_and_a_share_in_0_1() -> None:
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
    shares = objective_block_shares(value.components, [("network", 1.0), ("hydrograph", 3.0)])

    assert value.components["network.total"] == pytest.approx(3.0)
    weighted_network = 0.25 * value.components["network.total"]
    weighted_hydrograph = 0.75 * value.components["hydrograph.total"]
    denom = weighted_network + weighted_hydrograph
    assert denom == pytest.approx(value.total)
    assert shares == pytest.approx(
        {"network": weighted_network / denom, "hydrograph": weighted_hydrograph / denom}
    )
    assert all(0.0 <= share <= 1.0 for share in shares.values())


def _result(
    trial_id: int, objective_value: float, components: dict | None, **kwargs
) -> EvaluationResult:
    return EvaluationResult(
        trial_id=trial_id,
        sim_id=None,
        objective_value=objective_value,
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

    shares = _phase_objective_block_shares(cfg, history, best)

    assert shares["mean_n_trials"] == 2
    assert shares["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
    assert shares["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_a_failed_trial_does_not_enter_the_mean() -> None:
    cfg = _cfg(BLOCKS)
    history = [
        _result(1, 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
        _result(
            2, float("inf"), {"network.total": 999.0, "hydrograph.total": 999.0}, status="failed"
        ),
    ]
    best = history[0]

    shares = _phase_objective_block_shares(cfg, history, best)

    assert shares["mean_n_trials"] == 1
    assert shares["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})


def test_no_declared_blocks_gives_no_report_entry() -> None:
    cfg = _cfg([])
    history = [_result(1, 0.5, {"whatever.total": 1.0})]

    assert _phase_objective_block_shares(cfg, history, history[0]) is None


def _seed_trials(catalog, trials: list[tuple[str, float, dict | None]]) -> str:
    """Persist one session with the given (status, objective_value, metrics) trials."""
    persistence = CalibrationPersistence(catalog)
    session_id = uuid.uuid4().hex
    persistence.start_session(
        session_id=session_id,
        project="unit_test",
        method="grid",
        objective_name="composite",
        search_space={},
        config={},
    )
    for index, (status, objective_value, components) in enumerate(trials):
        result = EvaluationResult(
            trial_id=index,
            sim_id=None,
            objective_value=objective_value,
            status=status,
            components=components,
        )
        persistence.append_iteration(session_id, ParamSuggestion(trial_id=index, values={}), result)
    persistence.finalize_session(session_id, best=None, n_iterations=len(trials), duration_s=0.0)
    return session_id


class TestReusedPhase:
    """``_reused_phase_objective_block_shares`` reads a reused phase's own persisted trials."""

    def test_recomputes_the_shares_from_the_persisted_metrics(self, tmp_path) -> None:
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        with simulation_catalog(tmp_path) as catalog:
            session_id = _seed_trials(
                catalog,
                [
                    ("completed", 4.0, {"network.total": 10.0, "hydrograph.total": 2.0}),
                    ("completed", 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
                ],
            )
            shares, note = _reused_phase_objective_block_shares(_cfg(BLOCKS), catalog, session_id)

        assert note is None
        assert shares["mean_n_trials"] == 2
        assert shares["mean"] == pytest.approx({"network": 0.4375, "hydrograph": 0.5625})
        # trial 2 (objective_value 2.0) is the best: network 0.25, hydrograph 0.75
        assert shares["best"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})

    def test_a_crashed_persisted_trial_does_not_enter_the_mean(self, tmp_path) -> None:
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        with simulation_catalog(tmp_path) as catalog:
            session_id = _seed_trials(
                catalog,
                [
                    ("completed", 2.0, {"network.total": 2.0, "hydrograph.total": 2.0}),
                    # calibration_iterations' CHECK constraint accepts only finite
                    # lifecycle states; a live run never persists "failed" either
                    # (cli_runner.py remaps it to "crashed" first).
                    ("crashed", float("inf"), {"network.total": 999.0, "hydrograph.total": 999.0}),
                ],
            )
            shares, note = _reused_phase_objective_block_shares(_cfg(BLOCKS), catalog, session_id)

        assert note is None
        assert shares["mean_n_trials"] == 1
        assert shares["mean"] == pytest.approx({"network": 0.25, "hydrograph": 0.75})

    def test_no_persisted_components_gives_an_absent_note_not_a_share(self, tmp_path) -> None:
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        with simulation_catalog(tmp_path) as catalog:
            session_id = _seed_trials(catalog, [("completed", 1.0, None)])
            shares, note = _reused_phase_objective_block_shares(_cfg(BLOCKS), catalog, session_id)

        assert shares is None
        assert note is not None
        assert "not recomputed" in note

    def test_fewer_than_two_blocks_reports_nothing_without_touching_the_catalog(self) -> None:
        shares, note = _reused_phase_objective_block_shares(
            _cfg([("hydrograph", 1.0)]), catalog=None, session_id="unused"
        )

        assert shares is None
        assert note is None
