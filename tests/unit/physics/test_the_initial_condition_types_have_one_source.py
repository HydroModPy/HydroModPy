"""Every list of accepted initial-condition types has to be the same list.

The repository carried three: the config loader's key set, the config loader's type
set, and the solver's tuple. Adding ``spinup_cyclic`` to the union passed validation
and then failed inside ``run_solver`` with a message enumerating the variants the
solver happened to know. That contradiction is invisible to a reader, and it cost a
real model run to find, so it is gated here instead.
"""

from __future__ import annotations

from hydromodpy.physics.flow.initial_conditions import (
    FlowICBottom,
    FlowICCustom,
    FlowICSpinupCyclic,
    FlowICSteadyState,
    FlowICTop,
    FlowICTopOffset,
)
from hydromodpy.physics.flow.initial_conditions_config import known_ic_types
from hydromodpy.solver.initial_conditions import HEAD_INITIAL_CONDITION_TYPES

VARIANTS = (
    FlowICTop,
    FlowICTopOffset,
    FlowICBottom,
    FlowICCustom,
    FlowICSteadyState,
    FlowICSpinupCyclic,
)


def test_the_config_loader_accepts_exactly_the_union_s_discriminators() -> None:
    assert known_ic_types() == {
        str(variant.model_fields["type"].default) for variant in VARIANTS
    }


def test_the_solver_accepts_exactly_the_same_ones() -> None:
    assert set(HEAD_INITIAL_CONDITION_TYPES) == known_ic_types()


def test_every_variant_is_reachable_from_a_toml_payload() -> None:
    # The one check that would have caught it end to end: each discriminator has to
    # survive the flat [flow.ic] form the loader accepts.
    from hydromodpy.physics.flow.initial_conditions_config import (
        normalize_flow_initial_conditions,
    )

    required = {"custom": {"value": 42.0}, "top_offset": {"value": 0.5}}
    for name in sorted(known_ic_types()):
        payload = {"type": name, **required.get(name, {})}
        resolved = normalize_flow_initial_conditions(payload, location_prefix="flow.ic")
        assert resolved is not None
        assert resolved.h.type == name
