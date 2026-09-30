"""The soil marker on the ETP payload is a private attribute, never a TOML key.

A field would be a second mechanism beside ``"etp"`` in
``flow.active_sinks_sources``; a private attribute enters no TOML, no persisted
config and no doc, and only ``apply_etp_load_result_to_flow`` may set it.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from hydromodpy.physics.flow.sinks_sources.etp import FlowEtpConfig


def test_the_default_etp_is_not_marked() -> None:
    assert FlowEtpConfig().from_soil_reservoir is False


def test_the_marker_survives_a_model_copy() -> None:
    etp = FlowEtpConfig()
    etp._from_soil_reservoir = True

    copied = etp.model_copy(update={"values": 1.0})

    assert copied.from_soil_reservoir is True


def test_the_marker_survives_a_deepcopy() -> None:
    etp = FlowEtpConfig()
    etp._from_soil_reservoir = True

    assert copy.deepcopy(etp).from_soil_reservoir is True


def test_a_toml_key_cannot_set_the_marker() -> None:
    with pytest.raises(ValidationError):
        FlowEtpConfig(from_soil_reservoir=True)
