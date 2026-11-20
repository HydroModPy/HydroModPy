"""Lake definitions read from the model: which lakes are active and what each declares.

A lake is active when the model boundaries list ``lake`` and the lake table is not empty.
A payload is a mapping or a config object, and a field it does not carry reads as None.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow6.builders._lake_definitions import (
    _active_lake_definitions,
    _lake_attr,
    _scalar,
)
from tests._helpers.model_factory import make_model


def model_with(lakes: dict, *, active: bool = True) -> SimpleNamespace:
    ids = ("lake",) if active else ()
    return SimpleNamespace(
        inputs=make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=ids), lakes=lakes
        )
    )


def test_definitions_of_mapping_and_object_payloads() -> None:
    lakes = {
        1: {"bedleak": 1e-6, "initial_stage": 120.0},
        "res": SimpleNamespace(bedleak=2e-6, outlets=["weir"]),
    }

    definitions = _active_lake_definitions(model_with(lakes))

    assert list(definitions) == ["1", "res"]
    assert definitions["1"]["bedleak"] == 1e-6
    assert definitions["1"]["initial_stage"] == 120.0
    assert definitions["1"]["outlets"] is None
    assert definitions["res"]["bedleak"] == 2e-6
    assert definitions["res"]["outlets"] == ["weir"]
    assert definitions["res"]["polygon"] is None


INACTIVE = [
    pytest.param(model_with({"res": {"bedleak": 1e-6}}, active=False), id="lake not active"),
    pytest.param(model_with({}), id="no lake table"),
]


@pytest.mark.parametrize("model", INACTIVE)
def test_no_active_lake(model) -> None:
    assert _active_lake_definitions(model) == {}


def test_attribute_of_a_payload() -> None:
    assert _lake_attr({"width": 3.0}, "width") == 3.0
    assert _lake_attr({"width": 3.0}, "invert") is None
    assert _lake_attr(SimpleNamespace(width=4.0), "width") == 4.0
    assert _lake_attr(SimpleNamespace(), "width") is None


def test_scalar_of_a_number_or_a_quantity() -> None:
    assert _scalar(3) == 3.0
    assert _scalar(SimpleNamespace(magnitude=2.5)) == 2.5
