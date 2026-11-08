"""Unit tests for the RootConfig dataclass."""

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


def test_root_config_stores_model_and_migration_callables() -> None:
    root = RootConfig(
        model=_DummyModel,
        migrate_layers=_dummy_migrate_layers,
        migrate_merged=_dummy_migrate_merged,
    )
    assert root.model is _DummyModel
    assert root.migrate_layers([(None, {})]) == []
    assert root.migrate_merged({}, [(None, {})]) == []


def test_root_config_is_frozen() -> None:
    root = RootConfig(
        model=_DummyModel,
        migrate_layers=_dummy_migrate_layers,
        migrate_merged=_dummy_migrate_merged,
    )
    with pytest.raises(FrozenInstanceError):
        root.model = BaseModel  # type: ignore[misc]


def test_root_config_instances_are_equal_when_fields_are_equal() -> None:
    root1 = RootConfig(
        model=_DummyModel,
        migrate_layers=_dummy_migrate_layers,
        migrate_merged=_dummy_migrate_merged,
    )
    root2 = RootConfig(
        model=_DummyModel,
        migrate_layers=_dummy_migrate_layers,
        migrate_merged=_dummy_migrate_merged,
    )
    assert root1 == root2
