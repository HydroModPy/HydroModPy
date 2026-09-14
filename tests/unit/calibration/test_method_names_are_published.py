"""Every optimizer the package registers is named in the schema.

``method`` is a free string so an out-of-tree optimizer stays possible, which
means nothing but the description tells a reader which names work. The name of
the stream-network stage, ``bisection``, used to appear in no description, in no
``Literal`` and in no generated page, so the only way to find it was to read the
adapter decorators.
"""

from __future__ import annotations

from hydromodpy.calibration.config import CalibPhaseDecl, CalibrationConfig
from hydromodpy.calibration.optim.optimizer import available_optimizers


def _description(model: type, field_name: str) -> str:
    return model.model_fields[field_name].description or ""


def test_the_section_method_names_every_registered_optimizer() -> None:
    text = _description(CalibrationConfig, "method")

    missing = [name for name in available_optimizers() if f"'{name}'" not in text]
    assert missing == []


def test_the_phase_method_names_every_registered_optimizer() -> None:
    text = _description(CalibPhaseDecl, "method")

    missing = [name for name in available_optimizers() if f"'{name}'" not in text]
    assert missing == []


def test_the_stream_network_stage_is_findable() -> None:
    for model in (CalibrationConfig, CalibPhaseDecl):
        assert "bisection" in _description(model, "method")
