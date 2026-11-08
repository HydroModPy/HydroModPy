"""The five start states are frozen records, and each refuses what it cannot hold."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from hydromodpy.model.initial.state import (
    HEAD_RULE_KINDS,
    INITIAL_STATE_TYPES,
    CyclicSpinupStrategy,
    CyclicStart,
    HeadRule,
    PriorState,
    SolvedState,
    SteadyStart,
    SteadyStateStrategy,
)

ACCEPTED_RULES = (
    ("top", None),
    ("top_offset", 0.5),
    ("bottom", None),
    ("custom", 12.0),
)


@pytest.mark.parametrize(("kind", "value_m"), ACCEPTED_RULES, ids=[k for k, _ in ACCEPTED_RULES])
def test_a_head_rule_holds_its_kind_and_value(kind: str, value_m: float | None) -> None:
    rule = HeadRule(kind, value_m)

    assert (rule.kind, rule.value_m) == (kind, value_m)


def test_the_accepted_rules_are_every_head_rule_kind() -> None:
    assert tuple(kind for kind, _ in ACCEPTED_RULES) == HEAD_RULE_KINDS


REFUSED_RULES = (
    ("steady_state", None, "head rule kind"),
    ("nowhere", None, "head rule kind"),
    ("top_offset", None, "value is required"),
    ("custom", None, "value is required"),
    ("top", 1.0, "value is only supported"),
    ("bottom", 1.0, "value is only supported"),
)


@pytest.mark.parametrize(
    ("kind", "value_m", "message"),
    REFUSED_RULES,
    ids=[f"{k}-{v}" for k, v, _ in REFUSED_RULES],
)
def test_a_head_rule_refuses_a_kind_or_value_it_cannot_resolve(
    kind: str, value_m: float | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        HeadRule(kind, value_m)


FROZEN_STATES = (
    (HeadRule("top"), "kind"),
    (SteadyStart(), "strategy"),
    (CyclicStart(), "strategy"),
    (PriorState(np.zeros((1, 2)), {}, "store.zarr"), "head"),
    (SolvedState(np.zeros((1, 2)), "modflow6"), "head"),
)


@pytest.mark.parametrize(
    ("state", "field"), FROZEN_STATES, ids=[type(s).__name__ for s, _ in FROZEN_STATES]
)
def test_every_state_is_frozen(state: object, field: str) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(state, field, None)


def test_the_five_states_are_listed_once() -> None:
    assert [cls.__name__ for cls in INITIAL_STATE_TYPES] == [
        "HeadRule",
        "SteadyStart",
        "CyclicStart",
        "PriorState",
        "SolvedState",
    ]
    assert {type(state) for state, _ in FROZEN_STATES} == set(INITIAL_STATE_TYPES)


DEFAULT_STRATEGIES = (
    (SteadyStart().strategy, SteadyStateStrategy("mean_recharge", "time_mean", "first_period")),
    (CyclicStart().strategy, CyclicSpinupStrategy(4, 0.01, "top")),
)


@pytest.mark.parametrize(
    ("strategy", "expected"),
    DEFAULT_STRATEGIES,
    ids=[type(s).__name__ for s, _ in DEFAULT_STRATEGIES],
)
def test_a_start_without_a_strategy_takes_the_toml_defaults(
    strategy: object, expected: object
) -> None:
    assert strategy == expected


def test_the_steady_strategy_keeps_its_field_order_for_the_failure_report() -> None:
    """The stationary failure report writes the strategy as a mapping, field by field."""
    strategy = SteadyStateStrategy(source="prescribed", recharge_statistic=None, rate_m_s=1e-8)

    assert dict(strategy.__dict__) == {
        "source": "prescribed",
        "recharge_statistic": None,
        "boundary_condition_policy": "first_period",
        "rate_m_s": 1e-8,
    }


HEAD_STATES = (
    lambda head: PriorState(head, {"lake": 4.0}, "store.zarr", "run.v1"),
    lambda head: SolvedState(head, "modflow6"),
)


@pytest.mark.parametrize("build", HEAD_STATES, ids=["prior", "solved"])
def test_a_head_state_holds_a_read_only_float64_copy(build) -> None:
    given = np.array([[1, 2, 3]], dtype=np.int32)

    state = build(given)

    assert state.head.dtype == np.float64
    assert state.head is not given
    np.testing.assert_array_equal(state.head, given)
    with pytest.raises(ValueError, match="read-only"):
        state.head[0, 0] = 9.0
    given[0, 0] = 9
    assert state.head[0, 0] == 1.0


def test_a_prior_state_keeps_nan_and_freezes_its_lake_stages() -> None:
    stages = {"lake": 4.0}
    state = PriorState(np.array([[np.nan, 2.0]]), stages, "store.zarr")

    assert np.isnan(state.head[0, 0])
    assert state.sim_id is None
    stages["lake"] = 9.0
    assert state.lake_stages == {"lake": 4.0}
    with pytest.raises(TypeError):
        state.lake_stages["lake"] = 5.0  # type: ignore[index]


def test_a_prior_state_refuses_a_head_that_is_not_layers_by_cells() -> None:
    with pytest.raises(ValueError, match=r"\(nlay, ncpl\)"):
        PriorState(np.zeros(3), {}, "store.zarr")
