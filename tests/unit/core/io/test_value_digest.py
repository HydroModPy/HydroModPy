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


@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param(np.asarray([0.0, 1.5]), np.asarray([-0.0, 1.5]), id="negative-zero"),
        pytest.param(
            np.asarray([np.float64("nan")]),
            np.asarray([np.float64("-nan")]),
            id="nan-payload",
        ),
        pytest.param(
            np.asarray([1.5], dtype="float32"),
            np.asarray([1.5], dtype="float64"),
            id="float32-float64",
        ),
        pytest.param(np.asarray([True, False]), np.asarray([1.0, 0.0]), id="boolean"),
        pytest.param(np.asarray([3]), np.asarray([3.0]), id="integer-below-2-53"),
    ],
)
def test_two_blocks_of_the_same_values_hash_the_same(left, right):
    assert value_digest(left) == value_digest(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        pytest.param(np.asarray([1.0, 2.0]), np.asarray([[1.0, 2.0]]), id="shape"),
        pytest.param(np.asarray([1.0, 2.0]), np.asarray([2.0, 1.0]), id="order"),
        pytest.param(np.asarray([2**53]), np.asarray([2**53 + 1]), id="big-integer-exact"),
        pytest.param(np.asarray([1.0]), np.asarray([1.0000000000000002]), id="one-ulp"),
    ],
)
def test_two_blocks_of_other_values_hash_apart(left, right):
    assert value_digest(left) != value_digest(right)


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


def test_the_fold_of_one_step_is_not_the_digest_of_its_values():
    values = np.asarray([1.0, 2.0])
    digester = ValueDigester()
    digester.update(0, values)
    assert digester.digest(1) != value_digest(values)
