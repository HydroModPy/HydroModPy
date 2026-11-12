"""Runtime settings that the analytical Boussinesq validation cases hand to the solver.

Steady cases run PETSc with the VI obstacle surface model. Transient cases run
PETSc with the time-stepped VI obstacle (backward Euler, 4 steps per period).
"""

from __future__ import annotations

import pytest

from validation_cases.shared.boussinesq_analytical_runtime import (
    apply_analytical_boussinesq_runtime_defaults,
    boussinesq_variant_flow_section,
)

COMPLEMENTARITY = {"backend": "petsc", "surface_interaction_model": "complementarity"}

DEFAULTS = [
    pytest.param(
        {},
        "steady",
        False,
        {"backend": "petsc", "surface_interaction_model": "vi_obstacle"},
        id="steady fills petsc vi",
    ),
    pytest.param(
        {},
        "transient",
        False,
        {
            "backend": "petsc",
            "surface_interaction_model": "ts_vi_obstacle",
            "ts_vi_steps_per_period": 4,
            "ts_vi_type": "beuler",
        },
        id="transient fills petsc ts vi",
    ),
    pytest.param(
        COMPLEMENTARITY, "steady", False, COMPLEMENTARITY, id="explicit surface model is kept"
    ),
    pytest.param(
        COMPLEMENTARITY,
        "steady",
        True,
        {"backend": "petsc", "surface_interaction_model": "vi_obstacle"},
        id="force replaces explicit model",
    ),
]


@pytest.mark.parametrize(("given", "flow_regime", "force", "expected"), DEFAULTS)
def test_runtime_defaults(given, flow_regime, force, expected):
    runtime = apply_analytical_boussinesq_runtime_defaults(
        given, flow_regime=flow_regime, force=force
    )

    assert {key: runtime[key] for key in expected} == expected


def test_variant_flow_section_holds_no_runtime_key():
    section = boussinesq_variant_flow_section(
        {"flow_regime": "steady", "runtime": {"backend": "local"}, "runtime_max_iterations": 5},
        flow_regime="steady",
    )

    assert section == {"flow_regime": "steady"}


def test_transient_flow_section_starts_from_its_initial_condition():
    section = boussinesq_variant_flow_section({"flow_regime": "transient"})

    assert section["first_period_steady"] is False
