from types import SimpleNamespace

import pytest

from validity_frame import ValidityFrame, create_validity_frame


def test_verify_raises_on_missing_run_id():
    vf = ValidityFrame(tolerant=False)
    state = SimpleNamespace(data={"a": 1})
    steps = ("s1",)
    with pytest.raises(RuntimeError):
        vf.verify(state, steps)


def test_verify_tolerant_does_not_raise():
    vf = ValidityFrame(tolerant=True)
    state = SimpleNamespace(data={"a": 1})
    steps = ("s1",)
    vf.verify(state, steps)


def test_verify_accepts_valid_state():
    vf = ValidityFrame(tolerant=False)
    state = SimpleNamespace(run_id="r1", data={"a": 1})
    steps = ("s1",)
    vf.verify(state, steps)


def test_create_validity_frame_loads_default_entry_point():
    vf = create_validity_frame(tolerant=False)
    state = SimpleNamespace(run_id="r1", data={"a": 1})
    steps = ("s1",)
    vf.verify(state, steps)
