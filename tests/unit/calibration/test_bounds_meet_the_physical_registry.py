"""A declared calibration bound must face the same physical ceiling as a literal.

``PHYSICAL_BOUNDS`` refuses a specific yield of 0.8 written as a literal in
``[flow.param.Sy.field]``, because no rock drains 80 percent of its volume by
gravity. It never saw ``[calibration.parameters.Sy] bounds``, so the same 0.8
loaded without a word and the search spent its budget in a region the model
declares impossible. The ceiling that matters is the one on the path a
calibration actually takes.

Checked on the bounds rather than on each sampled value: the search never leaves
its bounds, so refusing the declaration refuses every candidate it could have
produced, once, before the first solve.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.parameters import ParameterSpace


def test_a_bound_above_the_ceiling_is_refused() -> None:
    """0.8 is out of range for a specific yield, declared or written."""
    with pytest.raises(ValueError) as failure:
        ParameterSpace.from_toml_mapping(
            {"Sy": {"bounds": [1e-4, 0.8], "path": "flow.param.Sy.field.value"}}
        )

    message = str(failure.value)
    assert "Sy" in message
    assert "0.8" in message


def test_a_bound_inside_the_ceiling_loads() -> None:
    """The guard only refuses what the registry declares impossible."""
    space = ParameterSpace.from_toml_mapping(
        {"Sy": {"bounds": [1e-4, 0.5], "path": "flow.param.Sy.field.value"}}
    )

    assert space["Sy"].upper == pytest.approx(0.5)


def test_an_uncatalogued_parameter_is_left_alone() -> None:
    """An id the registry does not know keeps working, as it does elsewhere."""
    space = ParameterSpace.from_toml_mapping(
        {"bedleak": {"bounds": [1e-12, 1e-2], "path": "flow.sinks_sources.lakes.a.bedleak"}}
    )

    assert space["bedleak"].upper == pytest.approx(1e-2)


def test_the_name_that_is_checked_is_the_declared_one() -> None:
    """The table key is the parameter id, which is what the registry keys on."""
    with pytest.raises(ValueError, match="Sy"):
        ParameterSpace.from_toml_mapping(
            {"Sy": {"bounds": [0.0, 0.95], "path": "flow.param.Sy.field.value"}}
        )
