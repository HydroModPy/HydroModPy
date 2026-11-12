"""The pipeline state: a frozen record of the run id, the step reached and a payload mapping."""

from __future__ import annotations

import pytest

from hydromodpy.workflow.state import PipelineState


def test_default_payload_is_empty() -> None:
    assert PipelineState(run_id="r").data == {}


@pytest.mark.parametrize("field", ["run_id", "step_index"])
def test_state_is_frozen(field) -> None:
    state = PipelineState(run_id="r", data={"x": 1})
    with pytest.raises(AttributeError):
        setattr(state, field, "other")
