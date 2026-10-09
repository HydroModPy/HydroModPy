"""MODPATH builds starting locations for forward and backward tracking only."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.physics.transport.transport_config import ModpathParametersConfig


def test_custom_track_dir_is_refused_with_the_values_to_write() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ModpathParametersConfig(track_dir="custom")
    message = str(excinfo.value)
    assert "no starting location" in message
    assert "'forward' or 'backward'" in message
    assert "zone_partic" in message


@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_forward_and_backward_are_accepted(direction: str) -> None:
    assert ModpathParametersConfig(track_dir=direction).track_dir == direction
