"""RootConfig: the frozen record of a root model and its two migration functions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import BaseModel

from hydromodpy.core.config_kit.root import RootConfig


class _DummyModel(BaseModel):
    value: int = 42


def _dummy_migrate_layers(layers):
    return []


def _dummy_migrate_merged(document, layers):
    return []


def make_root() -> RootConfig:
    return RootConfig(
        model=_DummyModel,
        migrate_layers=_dummy_migrate_layers,
        migrate_merged=_dummy_migrate_merged,
    )


def test_root_stores_model_and_migrations() -> None:
    root = make_root()
    assert root.model is _DummyModel
    assert root.migrate_layers([(None, {})]) == []
    assert root.migrate_merged({}, [(None, {})]) == []


def test_root_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        make_root().model = BaseModel  # type: ignore[misc]


def test_roots_with_equal_fields_are_equal() -> None:
    assert make_root() == make_root()
