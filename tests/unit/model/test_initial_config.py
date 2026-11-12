"""The ``[flow.ic]`` and ``[spinup]`` sections, and the start state a validated ``[flow.ic]`` asks for."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial.state import (
    CyclicSpinupStrategy,
    CyclicStart,
    HeadRule,
    SteadyStart,
    SteadyStateStrategy,
)
from hydromodpy.model.initial_config import (
    FlowICBottom,
    FlowICCustom,
    FlowICSpinupCyclic,
    FlowICSteadyState,
    FlowICTop,
    FlowICTopOffset,
    FlowInitialConditions,
    cyclic_spinup_strategy_of,
    initial_state_of,
    normalize_flow_initial_conditions,
    steady_state_strategy_of,
)

ACCEPTED_LENGTHS = (
    ("inline unit", {"kind": "custom", "value": "125 cm"}, "custom", 1.25),
    ("top offset", {"kind": "top_offset", "value": "10 m"}, "top_offset", 10.0),
    ("unit alias", {"kind": "custom", "value": 2, "unit": "m"}, "custom", 2.0),
)


@pytest.mark.parametrize(
    ("case", "payload", "kind", "metres"), ACCEPTED_LENGTHS, ids=[c[0] for c in ACCEPTED_LENGTHS]
)
def test_a_length_is_read_in_metres(case, payload, kind, metres) -> None:
    del case
    initial_conditions = normalize_flow_initial_conditions(payload)

    assert initial_conditions is not None
    assert initial_conditions.h.kind == kind
    assert initial_conditions.h.value.to("m").magnitude == pytest.approx(metres)
    assert initial_conditions.h.units == "m"


PASSED_THROUGH = (
    ("none", None, None),
    ("empty mapping", {}, None),
    ("one variant", FlowICTop(), "top"),
    ("h wrapper", {"h": {"kind": "top"}}, "top"),
    ("kind in capitals", {"kind": "TOP"}, "top"),
)


@pytest.mark.parametrize(
    ("case", "given", "kind"), PASSED_THROUGH, ids=[c[0] for c in PASSED_THROUGH]
)
def test_forms_of_a_flow_ic(case, given, kind) -> None:
    del case
    initial_conditions = normalize_flow_initial_conditions(given)

    assert (initial_conditions and initial_conditions.h.kind) == (kind or None)


def test_an_initial_conditions_object_is_kept() -> None:
    held = FlowInitialConditions(h=FlowICTop())

    assert normalize_flow_initial_conditions(held) is held


def test_validating_an_initial_conditions_object_keeps_it() -> None:
    held = FlowInitialConditions(h=FlowICTop())

    assert FlowInitialConditions.model_validate(held) is held
    with pytest.raises(ValueError, match="valid dictionary or instance of FlowInitialConditions"):
        FlowInitialConditions.model_validate(3)


def test_a_flow_ic_that_is_no_mapping_is_refused() -> None:
    with pytest.raises(TypeError, match="flow.ic must be a mapping"):
        normalize_flow_initial_conditions("top")


def test_head_stays_in_metres() -> None:
    with pytest.raises(ValueError, match="must be normalized to 'm'"):
        FlowICTop(units="cm")


def test_flow_config_rejects_steady_state_initial_condition_for_steady() -> None:
    with pytest.raises(ValueError, match="flow.ic.kind='steady_state'"):
        FlowConfig(flow_regime="steady", ic={"kind": "steady_state"})


REFUSED_PAYLOADS = (
    ("no kind", {"value": "10 m"}, "flow.ic.kind is required"),
    ("steady value", {"kind": "steady_state", "value": "1 m"}, "value is not supported"),
    ("top value", {"kind": "top", "value": "1 m"}, "value is only supported"),
    ("bottom value", {"kind": "bottom", "value": "1 m"}, "value is only supported"),
    ("top unit", {"kind": "top", "unit": "m"}, "unit/units is only supported"),
    ("bottom unit", {"kind": "bottom", "unit": "m"}, "unit/units is only supported"),
    ("steady unit", {"kind": "steady_state", "unit": "m"}, "unit/units is not supported"),
    (
        "conflicting units",
        {"kind": "custom", "value": "1.25 m", "unit": "cm"},
        "conflicting units",
    ),
    ("unknown unit", {"kind": "custom", "value": "1.25 qblorp"}, "Unsupported length unit"),
    ("not a length", {"kind": "custom", "value": "1.25 kg"}, "Unsupported length unit"),
    ("unknown key", {"kind": "top", "colour": 1}, "Unknown keys: colour"),
    ("unknown kind", {"kind": "nope"}, "kind must be one of: 'bottom', 'custom'"),
    ("custom without value", {"kind": "custom"}, "value is required when kind='custom'"),
    (
        "top with a rate",
        {"kind": "top", "rate": 1},
        "rate is only supported when kind='steady_state'",
    ),
)


@pytest.mark.parametrize(
    ("case", "payload", "message"), REFUSED_PAYLOADS, ids=[c for c, _, _ in REFUSED_PAYLOADS]
)
def test_a_flow_ic_payload_it_cannot_read_is_refused(case, payload, message) -> None:
    del case
    with pytest.raises(ValueError, match=message):
        normalize_flow_initial_conditions(payload)


REFUSED_STRATEGIES = (
    ("source", SimpleNamespace(source="chronicle"), "flow.ic.source must be"),
    (
        "policy",
        SimpleNamespace(boundary_condition_policy="all_periods"),
        "boundary_condition_policy must be 'first_period'",
    ),
    ("prescribed without rate", SimpleNamespace(source="prescribed"), "flow.ic.rate is required"),
    (
        "rate without prescribed",
        SimpleNamespace(source="recharge", rate=1e-8),
        "flow.ic.rate is only read",
    ),
    (
        "statistic",
        SimpleNamespace(recharge_statistic="median"),
        "recharge_statistic must be 'time_mean'",
    ),
)


@pytest.mark.parametrize(
    ("case", "initial_condition", "message"),
    REFUSED_STRATEGIES,
    ids=[c for c, _, _ in REFUSED_STRATEGIES],
)
def test_a_steady_strategy_outside_the_contract_is_refused(
    case, initial_condition, message
) -> None:
    del case
    with pytest.raises(ValueError, match=message):
        steady_state_strategy_of(initial_condition)


CYCLIC = (
    ("defaults", SimpleNamespace(), CyclicSpinupStrategy(4, 0.01, "top")),
    (
        "from the model",
        FlowICSpinupCyclic(max_cycles=3, tol_head="5 cm", first_cycle_from="steady_state"),
        CyclicSpinupStrategy(3, 0.05, "steady_state"),
    ),
)


@pytest.mark.parametrize(
    ("case", "initial_condition", "expected"), CYCLIC, ids=[c[0] for c in CYCLIC]
)
def test_the_cyclic_strategy_is_read_in_metres(case, initial_condition, expected) -> None:
    del case
    strategy = cyclic_spinup_strategy_of(initial_condition)

    assert (strategy.max_cycles, strategy.first_cycle_from) == (
        expected.max_cycles,
        expected.first_cycle_from,
    )
    assert strategy.tol_head_m == pytest.approx(expected.tol_head_m)


REFUSED_CYCLIC = (
    ("no cycle", SimpleNamespace(max_cycles=-1), "at least one cycle"),
    ("no tolerance", SimpleNamespace(tol_head=-0.01), "strictly positive"),
    ("start", SimpleNamespace(first_cycle_from="bottom"), "'top' or 'steady_state'"),
)


@pytest.mark.parametrize(
    ("case", "initial_condition", "message"), REFUSED_CYCLIC, ids=[c[0] for c in REFUSED_CYCLIC]
)
def test_a_cyclic_strategy_outside_the_contract_is_refused(case, initial_condition, message):
    del case
    with pytest.raises(ValueError, match=message):
        cyclic_spinup_strategy_of(initial_condition)


def test_a_run_without_flow_ic_is_refused() -> None:
    with pytest.raises(ValueError, match="flow.initial_conditions.h is required"):
        initial_state_of(None)


def test_a_start_kind_nothing_defines_is_refused() -> None:
    head = SimpleNamespace(kind="weird")

    with pytest.raises(ValueError, match="flow.ic.kind must be one of: bottom, custom"):
        initial_state_of(SimpleNamespace(h=head))
