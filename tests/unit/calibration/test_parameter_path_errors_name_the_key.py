"""A mistyped calibration path must say which TOML key is wrong.

``set_by_path`` walks a dotted string with ``getattr`` and, on a miss, named the
Python class it had reached: ``Path segment 'parem' not found on FlowConfig``.
That sentence carries no file, no TOML key, no fix, and a noun the person who
wrote the file has never seen. It is the only calibration failure that reaches
the CLI's last-resort handler, so it also arrives with no context of its own.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    apply_parameter_to_config,
    set_by_path,
)


class _Field:
    def __init__(self) -> None:
        self.value = 1.0


class _Flow:
    def __init__(self) -> None:
        self.field = _Field()


class _Config:
    def __init__(self) -> None:
        self.flow = _Flow()


def test_the_message_carries_the_whole_path() -> None:
    """Naming the segment alone leaves the reader guessing where it sits."""
    with pytest.raises(ValueError) as failure:
        set_by_path(_Config(), "flow.parem.value", 2.0)

    message = str(failure.value)
    assert "flow.parem.value" in message
    assert "parem" in message


def test_the_message_names_the_parameter_that_declared_it() -> None:
    """The reader looks for a TOML key, so the error has to name one."""
    param = CalibParameter(name="K", lower=1e-8, upper=1e-2, path="flow.parem.value")

    with pytest.raises(ValueError) as failure:
        apply_parameter_to_config(_Config(), param, 1e-5)

    message = str(failure.value)
    assert "calibration.parameters.K" in message
    assert "flow.parem.value" in message


def test_a_good_path_still_writes() -> None:
    """The guard only shapes the failure."""
    config = _Config()
    set_by_path(config, "flow.field.value", 3.0)
    assert config.flow.field.value == 3.0
