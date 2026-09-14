"""A regime and a time window are stage boundaries, not axes of a search.

``[calibration.parameters.<name>].path`` takes any dotted path, so nothing
stopped a file from declaring ``flow.flow_regime`` or ``simulation.time.*`` as a
calibrated parameter. Both are refused for the same reason, and it is not a
technical oversight: they say WHICH MODEL a stage runs, and a stage is what a
phase declares in its own ``overrides``. Searching over one of them asks the
optimizer to pick between two different models on a cost that only compares
trials of one.

A regime is also categorical, and every candidate reaches the config through
``float(value)``, so the search would write 0.5 into a field whose two legal
values are two words.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace


def _space(path: str) -> ParameterSpace:
    return ParameterSpace.from_toml_mapping({"p": {"bounds": [0.0, 1.0], "path": path}})


@pytest.mark.parametrize(
    "path",
    [
        "flow.flow_regime",
        "simulation.time.start_datetime",
        "simulation.time.end_datetime",
        "simulation.time.step_value",
        "simulation.time.step_unit",
    ],
)
def test_a_stage_boundary_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match="stage"):
        _space(path)


def test_the_refusal_points_at_the_phase_overrides() -> None:
    with pytest.raises(ValueError) as caught:
        _space("flow.flow_regime")

    message = str(caught.value)
    assert "flow.flow_regime" in message
    assert "overrides" in message


def test_a_hydraulic_property_is_untouched() -> None:
    space = ParameterSpace.from_toml_mapping(
        {"K": {"bounds": [1e-8, 1e-2], "transform": "log", "path": "flow.param.K.field.value"}}
    )

    assert [param.name for param in space] == ["K"]


def test_a_path_that_merely_starts_with_the_word_is_untouched() -> None:
    """The refusal is on the field, not on a prefix of its name."""
    space = ParameterSpace.from_toml_mapping(
        {"c": {"bounds": [1.0, 2.0], "path": "flow.flow_regime_factor"}}
    )

    assert [param.name for param in space] == ["c"]


def test_a_simulation_key_that_is_not_the_time_window_is_untouched() -> None:
    space = ParameterSpace.from_toml_mapping(
        {"c": {"bounds": [1.0, 2.0], "path": "simulation.something_else"}}
    )

    assert [param.name for param in space] == ["c"]
