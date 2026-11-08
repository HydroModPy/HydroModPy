"""The ``[flow.ic]`` and ``[spinup]`` sections, and the start state a validated ``[flow.ic]`` asks for."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial.state import (
    HEAD_RULE_KINDS,
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
    SpinupConfig,
    cyclic_spinup_strategy_of,
    initial_state_of,
    known_ic_types,
    normalize_flow_initial_conditions,
    steady_state_strategy_of,
)

# Every list of accepted initial-condition kinds has to be the same list.
#
# The repository carried three: the config loader's key set, the config loader's type
# set, and the solver's tuple. Adding ``spinup_cyclic`` to the union passed validation
# and then failed inside ``run_solver`` with a message enumerating the variants the
# solver happened to know. That contradiction is invisible to a reader, and it cost a
# real model run to find, so it is gated here instead.

VARIANTS = (
    FlowICTop,
    FlowICTopOffset,
    FlowICBottom,
    FlowICCustom,
    FlowICSteadyState,
    FlowICSpinupCyclic,
)


def test_the_config_loader_accepts_exactly_the_union_s_discriminators() -> None:
    assert known_ic_types() == {str(variant.model_fields["kind"].default) for variant in VARIANTS}


def test_the_start_states_cover_exactly_the_same_kinds() -> None:
    assert set(HEAD_RULE_KINDS) | {"steady_state", "spinup_cyclic"} == known_ic_types()


def test_every_variant_is_reachable_from_a_toml_payload() -> None:
    # The one check that would have caught it end to end: each discriminator has to
    # survive the flat [flow.ic] form the loader accepts.
    required = {"custom": {"value": 42.0}, "top_offset": {"value": 0.5}}
    for name in sorted(known_ic_types()):
        payload = {"kind": name, **required.get(name, {})}
        resolved = normalize_flow_initial_conditions(payload, location_prefix="flow.ic")
        assert resolved is not None
        assert resolved.h.kind == name


def test_normalize_flow_initial_conditions_sets_default_h_id() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {"kind": "custom", "value": 1.0, "unit": "m"}
    )
    assert initial_conditions is not None
    assert initial_conditions.h.id == "h"


ACCEPTED_LENGTHS = (
    ("inline unit", {"kind": "custom", "value": "125 cm"}, "custom", 1.25),
    ("top offset", {"kind": "top_offset", "value": "10 m"}, "top_offset", 10.0),
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


STEADY_PAYLOADS = (
    (
        "explicit",
        {
            "kind": "steady_state",
            "source": "mean_recharge",
            "recharge_statistic": "time_mean",
            "boundary_condition_policy": "first_period",
        },
    ),
    ("defaults", {"kind": "steady_state"}),
)


@pytest.mark.parametrize(("case", "payload"), STEADY_PAYLOADS, ids=[c for c, _ in STEADY_PAYLOADS])
def test_a_steady_state_payload_carries_its_strategy(case, payload) -> None:
    del case
    initial_conditions = normalize_flow_initial_conditions(payload)

    assert initial_conditions is not None
    assert initial_conditions.h.kind == "steady_state"
    assert initial_conditions.h.source == "mean_recharge"
    assert initial_conditions.h.recharge_statistic == "time_mean"
    assert initial_conditions.h.boundary_condition_policy == "first_period"


def test_flow_config_accepts_steady_state_initial_condition_for_transient() -> None:
    flow_config = FlowConfig(flow_regime="transient", ic={"kind": "steady_state"})

    assert flow_config.ic.h.kind == "steady_state"


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
)


@pytest.mark.parametrize(
    ("case", "payload", "message"), REFUSED_PAYLOADS, ids=[c for c, _, _ in REFUSED_PAYLOADS]
)
def test_a_flow_ic_payload_it_cannot_read_is_refused(case, payload, message) -> None:
    del case
    with pytest.raises(ValueError, match=message):
        normalize_flow_initial_conditions(payload)


def _steady(**payload: object) -> FlowICSteadyState:
    return FlowICSteadyState.model_validate({"kind": "steady_state", **payload})


def test_the_recharge_source_reads_the_time_mean_of_the_chronicle() -> None:
    strategy = steady_state_strategy_of(_steady(source="recharge"))

    assert strategy == SteadyStateStrategy("recharge", "time_mean", "first_period", None)


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


STATES = (
    ("top", {"kind": "top"}, HeadRule("top")),
    ("bottom", {"kind": "bottom"}, HeadRule("bottom")),
    ("top offset", {"kind": "top_offset", "value": "50 cm"}, HeadRule("top_offset", 0.5)),
    ("custom", {"kind": "custom", "value": 12.5}, HeadRule("custom", 12.5)),
    ("steady", {"kind": "steady_state"}, SteadyStart(SteadyStateStrategy())),
    (
        "cyclic",
        {"kind": "spinup_cyclic", "max_cycles": 2, "first_cycle_from": "steady_state"},
        CyclicStart(CyclicSpinupStrategy(2, 0.01, "steady_state")),
    ),
)


@pytest.mark.parametrize(("case", "payload", "expected"), STATES, ids=[c[0] for c in STATES])
def test_each_flow_ic_kind_gives_its_start_state(case, payload, expected) -> None:
    del case
    assert initial_state_of(normalize_flow_initial_conditions(payload)) == expected


def test_the_default_flow_ic_starts_at_the_top() -> None:
    assert initial_state_of(FlowInitialConditions()) == HeadRule("top")


def test_a_run_without_flow_ic_is_refused() -> None:
    with pytest.raises(ValueError, match="flow.initial_conditions.h is required"):
        initial_state_of(None)


def test_the_spinup_section_keeps_its_defaults() -> None:
    spinup = SpinupConfig()

    assert (spinup.max_cycles, spinup.tol_head, spinup.tol_stage) == (10, 0.01, 0.01)
    assert (spinup.window_start, spinup.window_end) == (None, None)
