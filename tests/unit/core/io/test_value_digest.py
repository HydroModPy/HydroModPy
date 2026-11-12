"""The values/1 rule: one digest for a block of values, whatever their dtype."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.io.value_digest import (
    VALUES_RULE,
    ValueDigester,
    fold_steps,
    value_digest,
)


def test_the_rule_has_one_name():
    assert VALUES_RULE == "values/1"


def test_a_larger_integer_is_held_exactly():
    exact = value_digest(np.asarray([2**64]))
    assert exact == value_digest(np.asarray([2**64]))
    assert exact != value_digest(np.asarray([2**64 - 1]))


def test_a_text_and_a_mapping_are_canonical_json():
    assert value_digest("discharge") == value_digest("discharge")
    assert value_digest({"b": 1, "a": 2}) == value_digest({"a": 2, "b": 1})
    assert value_digest(["a", 1]) != value_digest(["a", 2])


def test_an_object_the_rule_cannot_read_is_refused():
    with pytest.raises(TypeError, match="values/1"):
        value_digest(object())


def test_the_digester_folds_its_steps_in_order_whatever_the_fill_order():
    first = np.arange(6, dtype=np.float64).reshape(3, 2)
    second = first + 10.0
    whole = ValueDigester()
    for step in range(3):
        whole.update(step, [first[step], second[step]])
    out_of_order = ValueDigester()
    out_of_order.update(2, [first[2], second[2]])
    out_of_order.update(0, [first[0], second[0]])
    out_of_order.update(1, [first[1], second[1]])
    assert whole.digest(3) == out_of_order.digest(3)


def test_a_step_with_no_digest_is_refused_by_name():
    with pytest.raises(ValueError, match="step"):
        fold_steps({0: value_digest([1.0])}, 2)
