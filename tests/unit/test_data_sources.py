"""Unit tests for the DataSource Protocol + registry."""

from __future__ import annotations

import pytest

from hydromodpy.data.sources import (
    DataSource,
    clear_registry,
    get_source,
    list_sources,
    register_source,
)


class FakeSource:
    variable_type = "piezometry"
    source_name = "fake"

    def fetch(self, ctx):
        return {"ctx": ctx}


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    yield
    clear_registry()


def test_registered_source_is_discoverable():
    register_source(FakeSource())
    assert ("piezometry", "fake") in list_sources()
    src = get_source("piezometry", "fake")
    assert src is not None
    assert isinstance(src, DataSource)


def test_decorator_form():
    @register_source
    class DecoratedSource:
        variable_type = "hydrometry"
        source_name = "decorated"

        def fetch(self, ctx):
            return None

    assert ("hydrometry", "decorated") in list_sources()


def test_missing_source_returns_none():
    assert get_source("unknown", "nothing") is None


def test_register_source_requires_protocol_attrs():
    class Broken:
        pass

    with pytest.raises(TypeError):
        register_source(Broken())
